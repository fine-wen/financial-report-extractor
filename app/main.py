import json
import re
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import replace
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path, PurePosixPath
from tempfile import TemporaryDirectory
from threading import Lock, Thread
from time import sleep
from urllib.parse import quote

from fastapi import BackgroundTasks, Depends, FastAPI, File, Form, HTTPException, Query, UploadFile, status
from fastapi.responses import Response
from fastapi.staticfiles import StaticFiles
from sqlalchemy import func, inspect, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, joinedload

from app.config import settings
from app.database import Base, SessionLocal, engine, get_db
from app.models import (
    AuditLog, Company, Document, ExtractedField, ManualMetricDecision,
    MetricRelationException,
)
from app.schemas import (
    BatchConfirm,
    BatchDocumentUploadItem,
    BatchDocumentUploadRead,
    CompanyCreate,
    CompanyBatchCreate,
    CompanyBatchRead,
    CompanyRead,
    DashboardRead,
    DocumentCheckSummary,
    DocumentRead,
    FieldRead,
    FieldReview,
    FinancialSnapshotItem,
    MetricOptionRead,
)
from app.services.exports import build_financial_workbook, build_metric_workbook
from app.services.evidence_review import review_financial_evidence
from app.services.field_preference import preferred_fields, preferred_fields_by_company
from app.services.files import InvalidUploadError, sha256_bytes, store_document, validate_pdf
from app.services.company_identity import match_company_from_pdf
from app.services.financial_indicators import (
    DERIVED_DEFINITIONS,
    HistoricalMetric,
    calculate_financial_indicators,
)
from app.services.historical_consistency import (
    HistoricalReportedMetric,
    historical_consistency_warnings,
    value_in_yuan as historical_value_in_yuan,
)
from app.services.financial_extractor import (
    ExtractedMetric,
    METRICS,
    MetricDefinition,
    ParentCompanyPagesUnavailableError,
    determine_report_period,
    filename_period,
    extract_full_years_from_interim_report,
    extract_financial_metrics,
    find_metric_periods_in_page,
    has_core_statement_text,
    plausible_metric_period,
    plausible_report_year,
    select_parent_company_pages,
    validate_balance,
    validate_metric_relationships,
    validate_statement_reconciliations,
    validate_metric_completeness,
    validate_metric_source_alignment,
)
from app.services.mineru_client import (
    MinerUError,
    MinerUUnavailableError,
    MinerUTaskState,
    clear_mineru_stage_caches,
    extract_scan_pages,
    extract_scan_page,
    mineru_cache_path,
    read_best_mineru_cache,
)
from app.services.pdf_parser import (
    ParsedPage,
    PdfParsingError,
    ScannedPdfDetectedError,
    extract_pdf_pages,
    has_predominantly_landscape_pages,
    write_clockwise_rotated_pdf,
)
from app.services.review_summary import (
    document_check_summary,
    field_review_priority,
    field_review_sort_key,
    field_risk_reasons,
)
from app.services.metric_catalog import finance_display_label, finance_wide_field_order
from app.services.tax_extractor import (
    CORPORATE_INCOME_TAX_RETURN,
    CORPORATE_INCOME_TAX_PAYABLE,
    CORPORATE_INCOME_TAX_PREPAYMENT_DUE,
    TAX_DOCUMENT_TYPES,
    TAX_PAYMENT_CERTIFICATE,
    VAT_RETURN,
    VAT_PAYABLE_CUMULATIVE,
    detect_tax_document_type,
    extract_tax_metrics,
    is_tax_return_page,
    taxpayer_matches_company,
)


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    Path("data").mkdir(parents=True, exist_ok=True)
    settings.storage_dir.mkdir(parents=True, exist_ok=True)
    Base.metadata.create_all(bind=engine)
    document_columns = {column["name"] for column in inspect(engine).get_columns("documents")}
    document_column_migrations = {
        "processing_mode": "ALTER TABLE documents ADD COLUMN processing_mode VARCHAR(32) NOT NULL DEFAULT 'auto'",
        "document_type": "ALTER TABLE documents ADD COLUMN document_type VARCHAR(48) NOT NULL DEFAULT 'financial_statement'",
        "mineru_task_id": "ALTER TABLE documents ADD COLUMN mineru_task_id VARCHAR(64)",
        "mineru_task_status": "ALTER TABLE documents ADD COLUMN mineru_task_status VARCHAR(32)",
        "scan_stage": "ALTER TABLE documents ADD COLUMN scan_stage VARCHAR(32)",
        "scan_source_page_count": "ALTER TABLE documents ADD COLUMN scan_source_page_count INTEGER",
        "mineru_submitted_at": "ALTER TABLE documents ADD COLUMN mineru_submitted_at DATETIME",
        "mineru_heartbeat_at": "ALTER TABLE documents ADD COLUMN mineru_heartbeat_at DATETIME",
    }
    with engine.begin() as connection:
        for column_name, statement in document_column_migrations.items():
            if column_name not in document_columns:
                connection.execute(text(statement))
    with SessionLocal() as db:
        interrupted = db.scalars(
            select(Document).where(Document.status == "processing")
        ).all()
        for document in interrupted:
            document.status = "queued"
            document.error_message = (
                "平台上次关闭时任务尚未完成，已自动续接 MinerU 任务"
                if document.mineru_task_id is not None
                else "平台上次关闭时识别尚未完成，已自动重新排队"
            )
        review_candidates = db.scalars(
            select(Document).where(Document.status == "review_required")
        ).all()
        for document in review_candidates:
            update_document_review_status(db, document.id, "system")
        db.commit()
    Thread(target=monitor_document_queue, daemon=True).start()
    yield


app = FastAPI(title=settings.app_name, version="0.1.0", lifespan=lifespan)
document_processing_lock = Lock()
QUEUE_MONITOR_SECONDS = 60


def add_audit_log(
    db: Session, action: str, entity_type: str, entity_id: str, actor: str, details: dict[str, object]
) -> None:
    db.add(
        AuditLog(
            action=action,
            entity_type=entity_type,
            entity_id=entity_id,
            actor=actor,
            details=json.dumps(details, ensure_ascii=False),
        )
    )


def save_manual_metric_decision(db: Session, field: ExtractedField) -> None:
    if field.period is None or field.reviewed_by is None or field.reviewed_at is None:
        return
    decision = db.scalar(select(ManualMetricDecision).where(
        ManualMetricDecision.document_id == field.document_id,
        ManualMetricDecision.field_code == field.field_code,
        ManualMetricDecision.period == field.period,
    ))
    if decision is None:
        decision = ManualMetricDecision(
            document_id=field.document_id,
            field_code=field.field_code,
            period=field.period,
            status=field.status,
            reviewed_by=field.reviewed_by,
            reviewed_at=field.reviewed_at,
        )
        db.add(decision)
    decision.status = field.status
    decision.value_text = field.value_text
    decision.normalized_value = field.normalized_value
    decision.unit = field.unit
    decision.source_page = field.source_page
    decision.source_quote = field.source_quote
    decision.original_value = field.original_value
    decision.reviewed_by = field.reviewed_by
    decision.reviewed_at = field.reviewed_at


def company_to_read(db: Session, company: Company) -> CompanyRead:
    document_count = db.scalar(select(func.count(Document.id)).where(Document.company_id == company.id)) or 0
    pending_count = db.scalar(
        select(func.count(ExtractedField.id)).where(
            ExtractedField.company_id == company.id, ExtractedField.status == "pending"
        )
    ) or 0
    confirmed_count = db.scalar(
        select(func.count(ExtractedField.id)).where(
            ExtractedField.company_id == company.id,
            ExtractedField.status.in_(("confirmed", "corrected")),
        )
    ) or 0
    return CompanyRead.model_validate(company).model_copy(
        update={
            "document_count": document_count,
            "pending_count": pending_count,
            "confirmed_count": confirmed_count,
        }
    )


def document_to_read(db: Session, document: Document) -> DocumentRead:
    fields = db.scalars(
        select(ExtractedField).where(ExtractedField.document_id == document.id)
    ).all()
    statement_scope = None
    processed_log = db.scalar(
        select(AuditLog)
        .where(
            AuditLog.action == "document_processed",
            AuditLog.entity_type == "document",
            AuditLog.entity_id == str(document.id),
        )
        .order_by(AuditLog.id.desc())
        .limit(1)
    )
    if processed_log is not None:
        details = json.loads(processed_log.details)
        raw_scope = details.get("statement_scope")
        if isinstance(raw_scope, str):
            scope_labels = {
                "original_report": "原报告口径",
                "Ô­±¨¸æ¿Ú¾¶": "原报告口径",
                "Ä¸¹«Ë¾¿Ú¾¶": "母公司口径",
            }
            statement_scope = scope_labels.get(raw_scope, raw_scope)
    summary = (
        DocumentCheckSummary.model_validate(
            document_check_summary(list(fields), statement_scope)
        )
        if len(fields) > 0 and document.document_type == "financial_statement"
        else None
    )
    return DocumentRead.model_validate(document).model_copy(
        update={"field_count": len(fields), "check_summary": summary}
    )


def update_document_review_status(db: Session, document_id: int, reviewer: str) -> None:
    db.flush()
    document = db.get(Document, document_id)
    if document is None:
        raise RuntimeError(f"找不到待更新复核状态的文档，文档编号：{document_id}")
    pending_count = db.scalar(
        select(func.count(ExtractedField.id)).where(
            ExtractedField.document_id == document_id,
            ExtractedField.status == "pending",
        )
    ) or 0
    field_count = db.scalar(
        select(func.count(ExtractedField.id)).where(ExtractedField.document_id == document_id)
    ) or 0
    if field_count > 0 and pending_count == 0 and document.status != "reviewed":
        document.status = "reviewed"
        add_audit_log(
            db,
            "document_review_completed",
            "document",
            str(document_id),
            reviewer,
            {"field_count": field_count},
        )
    if pending_count > 0 and document.status == "reviewed":
        document.status = "review_required"


def field_to_read(field: ExtractedField) -> FieldRead:
    risk_reasons = field_risk_reasons(field)
    if (
        field.normalized_value is not None
        and field.period is not None
        and field.field_code not in DERIVED_DEFINITIONS
        and not field.field_code.startswith("tax_payment_line_")
    ):
        current_value = historical_value_in_yuan(
            field.normalized_value, field.unit or "元"
        )
        if current_value is not None:
            conflicts = any(
                peer.id != field.id
                and peer.field_code == field.field_code
                and peer.period == field.period
                and peer.normalized_value is not None
                and peer.document.status != "voided"
                and (
                    peer_value := historical_value_in_yuan(
                        peer.normalized_value, peer.unit or "元"
                    )
                )
                is not None
                and abs(current_value - peer_value) > Decimal("0.01")
                for peer in field.company.fields
            )
            if conflicts:
                risk_reasons.append("与其他报告同年度数据不一致")
    review_priority = field_review_priority(field)
    if len(risk_reasons) > 0 and review_priority != "calculated":
        review_priority = "high"
    return FieldRead.model_validate(field).model_copy(
        update={
            "label": finance_display_label(field.field_code, field.label),
            "document_filename": field.document.filename,
            "company_name": field.company.name,
            "review_priority": review_priority,
            "risk_reasons": list(dict.fromkeys(risk_reasons)),
        }
    )


def run_mineru_extraction(
    db: Session, document: Document, document_path: Path
) -> list[ParsedPage]:
    if settings.mineru_api_url is None or settings.mineru_api_url.strip() == "":
        raise PdfParsingError("当前没有连接 MinerU，无法识别原文件。")

    def save_task_state(task_state: MinerUTaskState) -> None:
        previous_task_id = document.mineru_task_id
        document.mineru_task_id = task_state.task_id
        document.mineru_task_status = task_state.status
        document.mineru_submitted_at = task_state.created_at
        document.mineru_heartbeat_at = datetime.now(timezone.utc)
        if task_state.status == "pending":
            queued_ahead = task_state.queued_ahead or 0
            document.error_message = (
                f"MinerU 任务已提交，前面还有 {queued_ahead} 份报告"
                if queued_ahead > 0
                else "MinerU 任务已提交，正在等待开始"
            )
        elif task_state.status == "processing":
            document.error_message = "MinerU 正在逐页识别，平台已保存任务进度"
        elif task_state.status == "completed":
            document.error_message = "MinerU 识别已完成，正在接收结果并按规则取数"
        elif task_state.status == "failed":
            document.error_message = f"MinerU 识别失败：{task_state.error or '未提供详细原因'}"
        if previous_task_id is not None and previous_task_id != task_state.task_id:
            add_audit_log(
                db,
                "mineru_task_resubmitted",
                "document",
                str(document.id),
                "system",
                {"previous_task_id": previous_task_id, "task_id": task_state.task_id},
            )
        elif previous_task_id is None:
            add_audit_log(
                db,
                "mineru_task_submitted",
                "document",
                str(document.id),
                "system",
                {"task_id": task_state.task_id},
            )
        db.commit()

    return extract_scan_pages(
        document_path,
        settings.mineru_api_url,
        settings.mineru_timeout_seconds,
        settings.mineru_retry_count,
        settings.storage_dir,
        document.sha256,
        document.mineru_task_id,
        settings.mineru_poll_seconds,
        settings.mineru_max_task_seconds,
        save_task_state,
    )


def run_scan_extraction(
    db: Session, document: Document, document_path: Path
) -> list[ParsedPage]:
    document.scan_stage = None
    document.scan_source_page_count = None
    return run_mineru_extraction(db, document, document_path)


def run_rotated_scan_extraction(
    db: Session, document: Document, document_path: Path
) -> list[ParsedPage]:
    with TemporaryDirectory(prefix="enterprise_knowledge_rotated_") as temporary_directory:
        rotated_path = Path(temporary_directory) / document_path.name
        write_clockwise_rotated_pdf(document_path, rotated_path)
        return run_scan_extraction(db, document, rotated_path)


def financial_metrics_from_pages(
    filename: str, all_pages: list[ParsedPage],
    warnings: list[str] | None = None,
) -> tuple[list[ParsedPage], str, list[ExtractedMetric]]:
    financial_pages = [page for page in all_pages if not is_tax_return_page(page)]
    pages = select_parent_company_pages(financial_pages)
    complete_years = extract_full_years_from_interim_report(pages)
    if complete_years is not None:
        report_period, metrics = complete_years
        return pages, report_period, metrics
    report_period = determine_report_period(filename, pages)
    if report_period is None:
        raise PdfParsingError(f"无法判断报告年度：{filename}")
    try:
        metrics = extract_financial_metrics(pages, report_period, warnings)
    except ValueError as exc:
        raise PdfParsingError(
            f"财务报表取数无法安全判断：{filename}；{exc}。"
            "系统未按默认列顺序猜测年度，请核对原表格。"
        ) from exc
    if len(metrics) == 0:
        raise PdfParsingError(
            f"已读取 PDF，但没有识别到支持的财务指标：{filename}。"
            "请确认文件包含资产负债表、利润表或现金流量表。"
        )
    return pages, report_period, metrics


def apply_manual_metric_decisions(
    metrics: list[ExtractedMetric],
    decisions: list[ManualMetricDecision],
    definitions: dict[str, MetricDefinition] | None = None,
) -> list[ExtractedMetric]:
    selected = {(metric.definition.code, metric.period): metric for metric in metrics}
    available = definitions or {definition.code: definition for definition in METRICS}
    for decision in decisions:
        definition = available.get(decision.field_code)
        if definition is None:
            continue
        key = (decision.field_code, decision.period)
        if decision.status == "missing":
            selected.pop(key, None)
            continue
        if decision.normalized_value is None or decision.source_page is None:
            continue
        selected[key] = ExtractedMetric(
            definition=definition,
            value_text=decision.value_text or str(decision.normalized_value),
            normalized_value=decision.normalized_value,
            unit=decision.unit or "元",
            period=decision.period,
            source_page=decision.source_page,
            source_quote=decision.source_quote or "",
            confidence=Decimal("1"),
        )
    return list(selected.values())


def validate_financial_metrics(
    filename: str,
    metrics: list[ExtractedMetric],
    approved_excesses: dict[tuple[str, str], tuple[Decimal, Decimal]] | None = None,
) -> None:
    invalid_periods = sorted({
        metric.period for metric in metrics
        if metric.period is not None and not plausible_metric_period(metric.period)
    })
    if invalid_periods:
        raise PdfParsingError(
            f"报告年度超出合理范围：{filename}；识别到{'、'.join(invalid_periods)}，"
            "系统未保存疑似日期或编号。"
        )
    completeness_errors = validate_metric_completeness(metrics)
    if len(completeness_errors) > 0:
        raise PdfParsingError(
            f"核心财务报表识别不完整：{filename}；"
            f"{'、'.join(completeness_errors)}。系统未保存不完整数据，请重新处理或检查原文件。"
        )
    relationship_errors = validate_metric_relationships(metrics, approved_excesses)
    if len(relationship_errors) > 0:
        raise PdfParsingError(
            f"财务指标存在明显逻辑冲突：{filename}；"
            f"{'、'.join(relationship_errors)}。系统未保存冲突数据，请检查原文证据。"
        )
    source_errors = validate_metric_source_alignment(metrics)
    if len(source_errors) > 0:
        raise PdfParsingError(
            f"财务指标来源与数值不符：{filename}；"
            f"{'、'.join(source_errors)}。系统未保存疑似附注或行号的数据。"
        )


def validated_financial_metrics_from_pages(
    filename: str,
    all_pages: list[ParsedPage],
    decisions: list[ManualMetricDecision] | None = None,
    approved_excesses: dict[tuple[str, str], tuple[Decimal, Decimal]] | None = None,
    warnings: list[str] | None = None,
) -> tuple[list[ParsedPage], str, list[ExtractedMetric]]:
    pages, report_period, metrics = financial_metrics_from_pages(filename, all_pages, warnings)
    if decisions:
        metrics = apply_manual_metric_decisions(metrics, decisions)
    validate_financial_metrics(filename, metrics, approved_excesses)
    return pages, report_period, metrics


CORE_RESCUE_ANCHORS = {
    "total_assets": ("current_assets", "cash", "total_liabilities"),
    "total_liabilities": ("owners_equity", "total_assets", "current_liabilities"),
    "owners_equity": ("total_liabilities", "total_assets"),
    "operating_revenue": ("net_profit", "operating_cost"),
    "net_profit": ("operating_revenue", "operating_profit"),
}


def missing_core_codes(metrics: list[ExtractedMetric]) -> set[str]:
    present = {metric.definition.code for metric in metrics}
    return {"total_assets", "total_liabilities", "owners_equity", "operating_revenue", "net_profit"} - present


def targeted_rescue_page_numbers(
    all_pages: list[ParsedPage], metrics: list[ExtractedMetric]
) -> list[int]:
    missing = missing_core_codes(metrics)
    candidates: list[int] = []
    for code in sorted(missing):
        anchors = CORE_RESCUE_ANCHORS[code]
        page_number = next(
            (metric.source_page for anchor in anchors for metric in metrics
             if metric.definition.code == anchor),
            None,
        )
        if code == "total_assets" and page_number is not None:
            # A missing asset half commonly precedes the liability half.
            earlier = next(
                (page.page_number for page in all_pages
                 if page.page_number == page_number - 1
                 and "资产负债表" in page.text[:400]
                 and "合并资产负债表" not in page.text[:400]),
                None,
            )
            page_number = earlier or page_number
        if page_number is None:
            title = "利润表" if code in ("operating_revenue", "net_profit") else "资产负债表"
            page_number = next(
                (page.page_number for page in all_pages
                 if title in page.text[:400] and f"合并{title}" not in page.text[:400]),
                None,
            )
        if page_number is not None and page_number not in candidates:
            candidates.append(page_number)
    return candidates[:2]


def recovered_balance_is_exact(metrics: list[ExtractedMetric]) -> bool:
    for period in {metric.period for metric in metrics if metric.period is not None}:
        totals = {
            metric.definition.code: metric
            for metric in metrics
            if metric.period == period and metric.definition.code in (
                "total_assets", "total_liabilities", "owners_equity"
            )
        }
        if len(totals) != 3 or len({metric.unit for metric in totals.values()}) != 1:
            return False
        difference = (
            totals["total_assets"].normalized_value
            - totals["total_liabilities"].normalized_value
            - totals["owners_equity"].normalized_value
        )
        if abs(difference) > Decimal("0.02"):
            return False
    return True


def try_recover_cash_from_page(
    metrics: list[ExtractedMetric],
    report_period: str,
    source_path: Path,
    api_url: str,
    timeout_seconds: int,
) -> tuple[list[ExtractedMetric], str | None]:
    if any(metric.definition.code == "cash" for metric in metrics):
        return metrics, None
    page_number = next(
        (metric.source_page for metric in metrics
         if metric.definition.code in ("current_assets", "total_assets")),
        None,
    )
    if page_number is None:
        return metrics, None
    try:
        page = extract_scan_page(source_path, api_url, timeout_seconds, page_number, "vlm-engine")
    except MinerUError:
        return metrics, None
    definition = next(definition for definition in METRICS if definition.code == "cash")
    current_period, previous_period = report_period, str(int(report_period) - 1)
    candidates = find_metric_periods_in_page(
        definition, page, current_period, previous_period
    )
    if (
        {metric.period for metric in candidates} != {current_period, previous_period}
        or any(abs(metric.normalized_value) < 1000 for metric in candidates)
        or validate_metric_source_alignment(candidates)
    ):
        return metrics, None
    return metrics + candidates, f"第{page_number}页/vlm-engine(货币资金)"


def try_targeted_page_recovery(
    filename: str,
    all_pages: list[ParsedPage],
    source_path: Path,
    api_url: str,
    timeout_seconds: int,
) -> tuple[list[ParsedPage], str, list[ExtractedMetric], str] | None:
    """Accept a second OCR result only if it preserves old fields and all checks pass."""
    try:
        _, original_period, original_metrics = financial_metrics_from_pages(filename, all_pages)
    except (PdfParsingError, ParentCompanyPagesUnavailableError, ValueError):
        return None
    missing = missing_core_codes(original_metrics)
    if not missing:
        return None
    original_values = {
        (metric.definition.code, metric.period): metric.normalized_value
        for metric in original_metrics
    }
    periods = {metric.period for metric in original_metrics if metric.period is not None}
    for page_number in targeted_rescue_page_numbers(all_pages, original_metrics):
        for backend in ("pipeline", "vlm-engine"):
            try:
                recovered_page = extract_scan_page(
                    source_path, api_url, timeout_seconds, page_number, backend
                )
                candidate_pages = [
                    recovered_page if page.page_number == page_number else page
                    for page in all_pages
                ]
                selected, period, metrics = validated_financial_metrics_from_pages(
                    filename, candidate_pages
                )
            except (MinerUError, PdfParsingError, ParentCompanyPagesUnavailableError, ValueError):
                continue
            candidate_values = {
                (metric.definition.code, metric.period): metric.normalized_value
                for metric in metrics
            }
            if period != original_period or any(
                candidate_values.get(key) != value for key, value in original_values.items()
            ):
                continue
            if any(
                (code, metric_period) not in candidate_values
                for code in missing for metric_period in periods
            ):
                continue
            if validate_balance(metrics) or not recovered_balance_is_exact(metrics):
                continue
            metrics, cash_trace = try_recover_cash_from_page(
                metrics, period, source_path, api_url, timeout_seconds
            )
            trace = f"第{page_number}页/{backend}"
            if cash_trace is not None:
                trace += f"；{cash_trace}"
            return selected, period, metrics, trace
    return None


def process_document_queue(_: int | None) -> None:
    with document_processing_lock:
        while True:
            with SessionLocal() as db:
                document_id = db.scalar(
                    select(Document.id)
                    .where(Document.status == "queued")
                    .order_by(Document.created_at, Document.id)
                    .limit(1)
                )
            if document_id is None:
                return
            should_continue = process_document_serially(document_id)
            if not should_continue:
                return


def monitor_document_queue() -> None:
    while True:
        process_document_queue(None)
        sleep(QUEUE_MONITOR_SECONDS)


def complete_tax_document(
    db: Session,
    document: Document,
    all_pages: list[ParsedPage],
    document_type: str,
    processing_mode: str,
) -> None:
    if not taxpayer_matches_company(all_pages, document.company.name):
        raise PdfParsingError(
            f"税务资料中的纳税人名称无法与企业档案“{document.company.name}”核对，已停止入库"
        )
    metrics = extract_tax_metrics(document_type, all_pages, document.filename)
    decisions = list(db.scalars(
        select(ManualMetricDecision).where(ManualMetricDecision.document_id == document.id)
    ).all())
    decisions_by_key = {(item.field_code, item.period): item for item in decisions}
    decisions_by_code = {item.field_code: item for item in decisions}
    if document_type == TAX_PAYMENT_CERTIFICATE:
        selected = []
        for metric in metrics:
            decision = decisions_by_code.get(metric.definition.code)
            if decision is not None and decision.status == "missing":
                continue
            if decision is not None and decision.normalized_value is not None and decision.source_page is not None:
                metric = replace(
                    metric,
                    value_text=decision.value_text or str(decision.normalized_value),
                    normalized_value=decision.normalized_value,
                    unit=decision.unit or "元",
                    period=decision.period,
                    source_page=decision.source_page,
                    source_quote=decision.source_quote or "",
                    confidence=Decimal("1"),
                )
            selected.append(metric)
        metrics = selected
    else:
        metrics = apply_manual_metric_decisions(metrics, decisions, {
            definition.code: definition for definition in (
                VAT_PAYABLE_CUMULATIVE, CORPORATE_INCOME_TAX_PAYABLE,
                CORPORATE_INCOME_TAX_PREPAYMENT_DUE,
            )
        })
    db.query(ExtractedField).filter(ExtractedField.document_id == document.id).delete()
    for metric in metrics:
        decision = (
            decisions_by_code.get(metric.definition.code)
            if document_type == TAX_PAYMENT_CERTIFICATE
            else decisions_by_key.get((metric.definition.code, metric.period))
        )
        db.add(
            ExtractedField(
                company_id=document.company_id,
                document_id=document.id,
                field_code=metric.definition.code,
                label=metric.definition.label,
                value_text=metric.value_text,
                normalized_value=metric.normalized_value,
                unit=metric.unit,
                period=metric.period,
                source_page=metric.source_page,
                source_quote=metric.source_quote,
                confidence=metric.confidence,
                status=decision.status if decision is not None else "pending",
                original_value=decision.original_value if decision is not None else None,
                reviewed_by=decision.reviewed_by if decision is not None else None,
                reviewed_at=decision.reviewed_at if decision is not None else None,
            )
        )
    document.status = "review_required" if any(
        (decisions_by_code.get(metric.definition.code)
         if document_type == TAX_PAYMENT_CERTIFICATE
         else decisions_by_key.get((metric.definition.code, metric.period))) is None
        for metric in metrics
    ) else "reviewed"
    document.processing_mode = "auto"
    document.document_type = document_type
    document.page_count = document.scan_source_page_count or len(all_pages)
    document.processed_at = datetime.now(timezone.utc)
    document.error_message = None
    add_audit_log(
        db,
        "document_processed",
        "document",
        str(document.id),
        "system",
        {
            "field_count": len(metrics),
            "calculated_indicator_count": 0,
            "statement_scope": "税务申报口径",
            "document_type": document_type,
            "processing_mode": processing_mode,
            "validation_errors": [],
        },
    )
    db.commit()


def process_document_serially(document_id: int) -> bool:
    db = SessionLocal()
    processing_mode = "auto"
    tax_document_type: str | None = None
    try:
        document = db.get(Document, document_id)
        if document is None:
            raise RuntimeError(f"找不到待处理文档，文档编号：{document_id}")
        if document.status != "queued":
            return True
        document.status = "processing"
        processing_mode = document.processing_mode
        document.error_message = "正在读取PDF和已有识别结果"
        db.commit()

        document_path = Path(document.stored_path)
        scope_name = "原报告口径"
        used_mineru_result = False
        if processing_mode == "force_mineru":
            if settings.mineru_api_url is None or settings.mineru_api_url.strip() == "":
                raise PdfParsingError("当前没有连接 MinerU，无法重新识别原文件。")
            document.error_message = "MinerU正在重新逐页识别原文件，长报告可能需要较长时间"
            db.commit()
            all_pages = run_scan_extraction(db, document, document_path)
            used_mineru_result = True
        elif (cached_pages := read_best_mineru_cache(
            settings.storage_dir, document.sha256, document.filename
        )) is not None:
            all_pages = cached_pages
            used_mineru_result = True
            if document.mineru_task_id is not None:
                document.mineru_task_status = "completed"
            document.error_message = "正在按最新规则提取数据"
            db.commit()
        else:
            try:
                all_pages = extract_pdf_pages(document_path)
            except ScannedPdfDetectedError as exc:
                if processing_mode == "rules_only":
                    raise PdfParsingError(
                        "这份扫描报告没有可复用的 MinerU 识别结果，请选择“重新识别原文件”。"
                    ) from exc
                if settings.mineru_api_url is None or settings.mineru_api_url.strip() == "":
                    raise PdfParsingError(
                        f"{exc} 当前尚未连接 MinerU 扫描识别服务。请在 .env 中填写 MINERU_API_URL 后重新处理。"
                    ) from exc
                document.error_message = "MinerU正在逐页识别，长报告可能需要较长时间"
                db.commit()
                all_pages = run_scan_extraction(db, document, document_path)
                used_mineru_result = True
        tax_document_type = detect_tax_document_type(all_pages)
        if tax_document_type is not None:
            document.document_type = tax_document_type
            complete_tax_document(
                db, document, all_pages, tax_document_type, processing_mode
            )
            return True
        document.document_type = "financial_statement"
        targeted_recovery: str | None = None
        decisions = list(db.scalars(
            select(ManualMetricDecision).where(ManualMetricDecision.document_id == document.id)
        ).all())
        decisions_by_key = {(item.field_code, item.period): item for item in decisions}
        relation_exceptions = list(db.scalars(
            select(MetricRelationException).where(
                MetricRelationException.document_id == document.id
            )
        ).all())
        approved_excesses = {
            (item.period, item.part_code): (item.part_value, item.total_value)
            for item in relation_exceptions
        }
        if not has_core_statement_text(all_pages):
            if processing_mode == "rules_only":
                raise PdfParsingError(
                    "已有文字不足以读取核心财务报表，请选择“重新识别原文件”。"
                )
            if settings.mineru_api_url is None or settings.mineru_api_url.strip() == "":
                raise PdfParsingError(
                    "PDF 的审计意见或附注可以读取，但核心财务报表是图片。"
                    "当前尚未连接 MinerU 扫描识别服务。"
                )
            cached_pages = read_best_mineru_cache(settings.storage_dir, document.sha256, document.filename)
            if cached_pages is None:
                document.error_message = "MinerU正在逐页识别，长报告可能需要较长时间"
                db.commit()
                all_pages = run_scan_extraction(db, document, document_path)
                used_mineru_result = True
        extraction_warnings: list[str] = []
        try:
            pages, report_period, metrics = validated_financial_metrics_from_pages(
                document.filename, all_pages, decisions, approved_excesses,
                extraction_warnings,
            )
        except (ParentCompanyPagesUnavailableError, PdfParsingError) as exc:
            extraction_error: ParentCompanyPagesUnavailableError | PdfParsingError | None = exc
            can_retry_with_mineru = (
                processing_mode == "auto"
                and not used_mineru_result
                and settings.mineru_api_url is not None
                and settings.mineru_api_url.strip() != ""
            )
            if can_retry_with_mineru:
                document.error_message = "PDF自带文字层不完整，MinerU正在重新识别原文件"
                db.commit()
                all_pages = run_scan_extraction(db, document, document_path)
                used_mineru_result = True
                try:
                    extraction_warnings.clear()
                    pages, report_period, metrics = validated_financial_metrics_from_pages(
                        document.filename, all_pages, decisions, approved_excesses,
                        extraction_warnings,
                    )
                except (ParentCompanyPagesUnavailableError, PdfParsingError) as retry_exc:
                    extraction_error = retry_exc
                else:
                    extraction_error = None
            can_retry_rotated_scan = (
                extraction_error is not None
                and processing_mode in ("auto", "force_mineru")
                and used_mineru_result
                and settings.mineru_api_url is not None
                and settings.mineru_api_url.strip() != ""
                and has_predominantly_landscape_pages(document_path)
            )
            if can_retry_rotated_scan:
                document.error_message = "横向扫描页方向异常，MinerU正在校正方向后重新识别"
                db.commit()
                all_pages = run_rotated_scan_extraction(db, document, document_path)
                try:
                    extraction_warnings.clear()
                    pages, report_period, metrics = validated_financial_metrics_from_pages(
                        document.filename, all_pages, decisions, approved_excesses,
                        extraction_warnings,
                    )
                except (ParentCompanyPagesUnavailableError, PdfParsingError) as rotated_exc:
                    extraction_error = rotated_exc
                else:
                    extraction_error = None
            if (
                extraction_error is not None
                and used_mineru_result
                and processing_mode in ("auto", "force_mineru", "targeted")
                and settings.mineru_api_url is not None
                and settings.mineru_api_url.strip() != ""
            ):
                document.error_message = "核心指标缺失，正在只对疑点页二次识别"
                db.commit()
                recovered = try_targeted_page_recovery(
                    document.filename,
                    all_pages,
                    document_path,
                    settings.mineru_api_url,
                    settings.mineru_timeout_seconds,
                )
                if recovered is not None:
                    extraction_warnings.clear()
                    pages, report_period, metrics, targeted_recovery = recovered
                    try:
                        metrics = apply_manual_metric_decisions(metrics, decisions)
                        validate_financial_metrics(
                            document.filename, metrics, approved_excesses
                        )
                    except PdfParsingError as recovery_exc:
                        extraction_error = recovery_exc
                    else:
                        extraction_error = None
            if isinstance(extraction_error, ParentCompanyPagesUnavailableError):
                raise ParentCompanyPagesUnavailableError(
                    f"{extraction_error}。为避免误取合并口径，系统已停止提取。"
                ) from extraction_error
            if extraction_error is not None:
                if "核心财务报表识别不完整" in str(extraction_error):
                    raise PdfParsingError(
                        f"{extraction_error}；疑点页已尝试局部二次识别，仍无可靠原文证据，"
                        "请对照原PDF核准，不能按勾稽关系猜数。"
                    ) from extraction_error
                raise extraction_error
        if len(pages) < len(all_pages):
            scope_name = "母公司口径"
        history_rows = db.scalars(
            select(ExtractedField)
            .where(
                ExtractedField.company_id == document.company_id,
                ExtractedField.document_id != document.id,
                ExtractedField.normalized_value.is_not(None),
                ExtractedField.period.is_not(None),
                ExtractedField.status != "missing",
            )
            .order_by(ExtractedField.id.desc())
        ).all()
        history = [
            HistoricalMetric(
                code=row.field_code,
                value=row.normalized_value,
                unit=row.unit or "元",
                period=row.period or "",
                source_page=row.source_page,
                source_quote=row.source_quote,
            )
            for row in history_rows
        ]
        history_years: dict[int, str] = {}
        for row in history_rows:
            if row.period is not None and row.period.isdigit():
                history_years[row.document_id] = max(
                    history_years.get(row.document_id, row.period), row.period
                )
        reported_history = [
            HistoricalReportedMetric(
                code=row.field_code,
                label=row.label,
                value=row.normalized_value,
                unit=row.unit or "元",
                period=row.period or "",
                document_filename=row.document.filename,
                report_year=filename_period(row.document.filename) or history_years.get(row.document_id),
            )
            for row in history_rows
            if row.normalized_value is not None and row.period is not None
        ]
        consistency_warnings = historical_consistency_warnings(
            metrics, reported_history, document.filename, report_period
        )
        evidence_findings = review_financial_evidence(metrics)
        derived_metrics = calculate_financial_indicators(metrics, history)
        derived_metrics = apply_manual_metric_decisions(
            derived_metrics, decisions, DERIVED_DEFINITIONS
        )
        all_metrics = metrics + derived_metrics
        db.query(ExtractedField).filter(ExtractedField.document_id == document.id).delete()
        for metric in all_metrics:
            decision = decisions_by_key.get((metric.definition.code, metric.period))
            db.add(
                ExtractedField(
                    company_id=document.company_id,
                    document_id=document.id,
                    field_code=metric.definition.code,
                    label=metric.definition.label,
                    value_text=metric.value_text,
                    normalized_value=metric.normalized_value,
                    unit=metric.unit,
                    period=metric.period,
                    source_page=metric.source_page,
                    source_quote=metric.source_quote,
                    confidence=metric.confidence,
                    status=decision.status if decision is not None else "pending",
                    original_value=decision.original_value if decision is not None else None,
                    reviewed_by=decision.reviewed_by if decision is not None else None,
                    reviewed_at=decision.reviewed_at if decision is not None else None,
                )
            )
        validation_errors = list(dict.fromkeys(extraction_warnings)) + consistency_warnings + validate_statement_reconciliations(metrics, pages) + [
            finding.message for finding in evidence_findings
        ] + [
            f"{item.period}年{item.part_code}已按原PDF第{item.source_page}页核准为单份报告特例：{item.reason}"
            for item in relation_exceptions
        ]
        document.status = "review_required"
        document.processing_mode = "auto"
        document.page_count = document.scan_source_page_count or len(all_pages)
        document.processed_at = datetime.now(timezone.utc)
        document.error_message = "；".join(validation_errors) if validation_errors else None
        add_audit_log(
            db,
            "document_processed",
            "document",
            str(document.id),
            "system",
            {
                "field_count": len(all_metrics),
                "calculated_indicator_count": len(derived_metrics),
                "statement_scope": scope_name,
                "processing_mode": processing_mode,
                "targeted_recovery": targeted_recovery,
                "relation_exception_ids": [item.id for item in relation_exceptions],
                "validation_errors": validation_errors,
                "evidence_findings": [
                    {
                        "code": finding.code,
                        "period": finding.period,
                        "field_codes": list(finding.field_codes),
                        "message": finding.message,
                    }
                    for finding in evidence_findings
                ],
            },
        )
        db.commit()
        return True
    except MinerUUnavailableError as exc:
        db.rollback()
        document = db.get(Document, document_id)
        if document is not None:
            document.status = "queued"
            document.error_message = (
                "MinerU服务暂时不可用，识别队列已暂停；启动MinerU后将从当前文件继续"
            )
            document.processed_at = None
            add_audit_log(
                db,
                "document_processing_paused",
                "document",
                str(document.id),
                "system",
                {
                    "reason": str(exc),
                    "processing_mode": processing_mode,
                    "scan_stage": document.scan_stage,
                    "mineru_task_id": document.mineru_task_id,
                },
            )
            db.commit()
        return False
    except (PdfParsingError, OSError, RuntimeError, ValueError) as exc:
        db.rollback()
        document = db.get(Document, document_id)
        if document is not None:
            if tax_document_type is not None or document.document_type in TAX_DOCUMENT_TYPES:
                db.query(ExtractedField).filter(
                    ExtractedField.document_id == document.id
                ).delete()
                if tax_document_type is not None:
                    document.document_type = tax_document_type
            if isinstance(exc, ParentCompanyPagesUnavailableError):
                db.query(ExtractedField).filter(
                    ExtractedField.document_id == document.id
                ).delete()
            document.status = "failed"
            document.processing_mode = "auto"
            document.error_message = str(exc)
            document.processed_at = datetime.now(timezone.utc)
            add_audit_log(
                db,
                "document_failed",
                "document",
                str(document.id),
                "system",
                {"error": str(exc), "processing_mode": processing_mode},
            )
            db.commit()
        return True
    finally:
        db.close()


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok", "name": settings.app_name}


@app.get("/api/dashboard", response_model=DashboardRead)
def dashboard(db: Session = Depends(get_db)) -> DashboardRead:
    return DashboardRead(
        company_count=db.scalar(select(func.count(Company.id))) or 0,
        document_count=db.scalar(select(func.count(Document.id))) or 0,
        processing_count=db.scalar(
            select(func.count(Document.id)).where(Document.status.in_(("queued", "processing")))
        )
        or 0,
        failed_count=db.scalar(select(func.count(Document.id)).where(Document.status == "failed")) or 0,
        pending_field_count=db.scalar(
            select(func.count(ExtractedField.id)).where(ExtractedField.status == "pending")
        )
        or 0,
        confirmed_field_count=db.scalar(
            select(func.count(ExtractedField.id)).where(
                ExtractedField.status.in_(("confirmed", "corrected"))
            )
        )
        or 0,
    )


@app.post("/api/companies", response_model=CompanyRead, status_code=status.HTTP_201_CREATED)
def create_company(payload: CompanyCreate, db: Session = Depends(get_db)) -> CompanyRead:
    company = Company(**payload.model_dump())
    db.add(company)
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail=f"企业名称已经存在：{payload.name}") from exc
    add_audit_log(db, "company_created", "company", str(company.id), "当前用户", {"name": company.name})
    db.commit()
    db.refresh(company)
    return company_to_read(db, company)


@app.post("/api/companies/batch", response_model=CompanyBatchRead, status_code=status.HTTP_201_CREATED)
def create_companies_batch(
    payload: CompanyBatchCreate, db: Session = Depends(get_db)
) -> CompanyBatchRead:
    requested_names: set[str] = set()
    unique_payloads: list[CompanyCreate] = []
    skipped_names: list[str] = []
    for company_payload in payload.companies:
        normalized_name = company_payload.name.strip()
        if len(normalized_name) < 2:
            raise HTTPException(status_code=422, detail="企业名称至少需要两个字符")
        if normalized_name in requested_names:
            skipped_names.append(normalized_name)
            continue
        requested_names.add(normalized_name)
        unique_payloads.append(company_payload.model_copy(update={"name": normalized_name}))

    existing_names = set(
        db.scalars(select(Company.name).where(Company.name.in_(requested_names))).all()
    )
    created_companies: list[Company] = []
    for company_payload in unique_payloads:
        if company_payload.name in existing_names:
            skipped_names.append(company_payload.name)
            continue
        company = Company(**company_payload.model_dump())
        db.add(company)
        db.flush()
        created_companies.append(company)
        add_audit_log(
            db,
            "company_created",
            "company",
            str(company.id),
            "当前用户",
            {"name": company.name, "source": "batch"},
        )
    db.commit()
    for company in created_companies:
        db.refresh(company)
    return CompanyBatchRead(
        created=[company_to_read(db, company) for company in created_companies],
        skipped_names=skipped_names,
    )


@app.get("/api/companies", response_model=list[CompanyRead])
def list_companies(db: Session = Depends(get_db)) -> list[CompanyRead]:
    companies = db.scalars(select(Company).order_by(Company.created_at.desc())).all()
    return [company_to_read(db, company) for company in companies]


@app.get("/api/companies/{company_id}", response_model=CompanyRead)
def get_company(company_id: int, db: Session = Depends(get_db)) -> CompanyRead:
    company = db.get(Company, company_id)
    if company is None:
        raise HTTPException(status_code=404, detail=f"找不到企业，企业编号：{company_id}")
    return company_to_read(db, company)


@app.post("/api/companies/{company_id}/documents", response_model=DocumentRead, status_code=202)
async def upload_document(
    company_id: int,
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
) -> DocumentRead:
    company = db.get(Company, company_id)
    if company is None:
        raise HTTPException(status_code=404, detail=f"找不到企业，企业编号：{company_id}")
    content = await file.read()
    try:
        filename = validate_pdf(file.filename, content, settings.max_upload_mb)
    except InvalidUploadError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    digest = sha256_bytes(content)
    duplicate = db.scalar(
        select(Document).where(
            Document.company_id == company_id,
            Document.sha256 == digest,
            Document.status != "voided",
        )
    )
    if duplicate is not None:
        raise HTTPException(
            status_code=409,
            detail=f"该企业已经上传过相同文件：{duplicate.filename}，文档编号：{duplicate.id}",
        )
    stored_path = store_document(settings.storage_dir, company_id, digest, filename, content)
    document = Document(
        company_id=company_id,
        filename=filename,
        stored_path=str(stored_path.resolve()),
        sha256=digest,
        status="queued",
    )
    db.add(document)
    db.flush()
    add_audit_log(
        db,
        "document_uploaded",
        "document",
        str(document.id),
        "当前用户",
        {"filename": filename, "sha256": digest},
    )
    db.commit()
    db.refresh(document)
    response = document_to_read(db, document)
    background_tasks.add_task(process_document_queue, document.id)
    return response


@app.post("/api/documents/auto-upload", response_model=DocumentRead, status_code=202)
async def auto_upload_document(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
) -> DocumentRead:
    content = await file.read()
    try:
        filename = validate_pdf(file.filename, content, settings.max_upload_mb)
        companies = db.execute(select(Company.id, Company.name)).all()
        company_id = match_company_from_pdf(content, [(row.id, row.name) for row in companies])
    except (InvalidUploadError, PdfParsingError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    digest = sha256_bytes(content)
    duplicate = db.scalar(
        select(Document).where(
            Document.company_id == company_id,
            Document.sha256 == digest,
            Document.status != "voided",
        )
    )
    if duplicate is not None:
        raise HTTPException(
            status_code=409,
            detail=f"该企业已经上传过相同文件：{duplicate.filename}，文档编号：{duplicate.id}",
        )
    stored_path = store_document(settings.storage_dir, company_id, digest, filename, content)
    document = Document(
        company_id=company_id,
        filename=filename,
        stored_path=str(stored_path.resolve()),
        sha256=digest,
        status="queued",
    )
    db.add(document)
    db.flush()
    add_audit_log(
        db, "document_uploaded", "document", str(document.id), "当前用户",
        {"filename": filename, "sha256": digest, "source": "auto_company_match"},
    )
    db.commit()
    db.refresh(document)
    response = document_to_read(db, document)
    background_tasks.add_task(process_document_queue, document.id)
    return response


def company_name_from_relative_path(relative_path: str) -> str:
    normalized_path = relative_path.replace("\\", "/").strip("/")
    parts = PurePosixPath(normalized_path).parts
    if len(parts) < 2 or any(part in ("", ".", "..") for part in parts):
        raise InvalidUploadError(
            f"批量上传文件必须放在企业子文件夹中：{relative_path}"
        )
    folder_name = parts[0].strip()
    without_sequence = re.sub(r"^\d+(?:\.\d+)*[\s、._-]*", "", folder_name).strip()
    company_suffixes = ("有限公司", "股份有限公司", "集团有限公司")
    company_name = (
        without_sequence
        if without_sequence.endswith(company_suffixes)
        else folder_name
    )
    if len(company_name) < 2:
        raise InvalidUploadError(f"无法从文件夹识别企业名称：{folder_name}")
    return company_name


@app.post(
    "/api/documents/batch-upload",
    response_model=BatchDocumentUploadRead,
    status_code=202,
)
async def batch_upload_documents(
    background_tasks: BackgroundTasks,
    files: list[UploadFile] = File(...),
    relative_paths: list[str] = Form(...),
    db: Session = Depends(get_db),
) -> BatchDocumentUploadRead:
    if len(files) != len(relative_paths):
        raise HTTPException(status_code=422, detail="文件数量与相对路径数量不一致")
    if len(files) == 0 or len(files) > 500:
        raise HTTPException(status_code=422, detail="一次批量上传需要 1至500 个文件")

    items: list[BatchDocumentUploadItem] = []
    created_company_names: set[str] = set()
    uploaded_count = 0
    duplicate_count = 0
    failed_count = 0
    for upload_file, relative_path in zip(files, relative_paths, strict=True):
        filename = Path(upload_file.filename or "").name
        company_name: str | None = None
        created_company_this_file = False
        try:
            company_name = company_name_from_relative_path(relative_path)
            content = await upload_file.read()
            filename = validate_pdf(filename, content, settings.max_upload_mb)
            company = db.scalar(select(Company).where(Company.name == company_name))
            if company is None:
                company = Company(
                    name=company_name,
                    unified_code=None,
                    industry=None,
                    contact_name=None,
                )
                db.add(company)
                db.flush()
                add_audit_log(
                    db,
                    "company_created",
                    "company",
                    str(company.id),
                    "当前用户",
                    {"name": company.name, "source": "batch_folder_upload"},
                )
                created_company_names.add(company_name)
                created_company_this_file = True
            digest = sha256_bytes(content)
            duplicate = db.scalar(
                select(Document).where(
                    Document.company_id == company.id,
                    Document.sha256 == digest,
                    Document.status != "voided",
                )
            )
            if duplicate is not None:
                duplicate_count += 1
                items.append(
                    BatchDocumentUploadItem(
                        relative_path=relative_path,
                        company_name=company_name,
                        filename=filename,
                        status="duplicate",
                        document_id=duplicate.id,
                        message=f"已存在相同文件：{duplicate.filename}",
                    )
                )
                db.commit()
                continue
            stored_path = store_document(
                settings.storage_dir, company.id, digest, filename, content
            )
            document = Document(
                company_id=company.id,
                filename=filename,
                stored_path=str(stored_path.resolve()),
                sha256=digest,
                status="queued",
            )
            db.add(document)
            db.flush()
            add_audit_log(
                db,
                "document_uploaded",
                "document",
                str(document.id),
                "当前用户",
                {
                    "filename": filename,
                    "sha256": digest,
                    "source": "batch_folder_upload",
                    "relative_path": relative_path,
                },
            )
            db.commit()
            uploaded_count += 1
            items.append(
                BatchDocumentUploadItem(
                    relative_path=relative_path,
                    company_name=company_name,
                    filename=filename,
                    status="uploaded",
                    document_id=document.id,
                    message=None,
                )
            )
        except (InvalidUploadError, OSError) as exc:
            db.rollback()
            if created_company_this_file and company_name in created_company_names:
                created_company_names.remove(company_name)
            failed_count += 1
            items.append(
                BatchDocumentUploadItem(
                    relative_path=relative_path,
                    company_name=company_name,
                    filename=filename,
                    status="failed",
                    document_id=None,
                    message=str(exc),
                )
            )
    if uploaded_count > 0:
        background_tasks.add_task(process_document_queue, None)
    return BatchDocumentUploadRead(
        created_company_count=len(created_company_names),
        uploaded_count=uploaded_count,
        duplicate_count=duplicate_count,
        failed_count=failed_count,
        items=items,
    )


@app.post("/api/documents/{document_id}/void", response_model=DocumentRead)
def void_document(document_id: int, db: Session = Depends(get_db)) -> DocumentRead:
    document = db.get(Document, document_id)
    if document is None:
        raise HTTPException(status_code=404, detail=f"找不到文档，文档编号：{document_id}")
    if document.status == "processing":
        raise HTTPException(status_code=409, detail="文件正在识别中，请等待处理结束后再作废")
    if document.status == "voided":
        raise HTTPException(status_code=409, detail="该文件已经作废")
    deleted_field_count = db.query(ExtractedField).filter(
        ExtractedField.document_id == document.id
    ).delete()
    document.status = "voided"
    document.error_message = "已由用户作废，对应字段数据已删除"
    add_audit_log(
        db,
        "document_voided",
        "document",
        str(document.id),
        "当前用户",
        {"filename": document.filename, "deleted_field_count": deleted_field_count},
    )
    db.commit()
    db.refresh(document)
    return document_to_read(db, document)


@app.get("/api/documents", response_model=list[DocumentRead])
def list_documents(company_id: int | None = None, db: Session = Depends(get_db)) -> list[DocumentRead]:
    query = select(Document).order_by(Document.created_at.desc())
    if company_id is not None:
        query = query.where(Document.company_id == company_id)
    documents = db.scalars(query).all()
    return [document_to_read(db, document) for document in documents]


@app.get("/api/documents/{document_id}", response_model=DocumentRead)
def get_document(document_id: int, db: Session = Depends(get_db)) -> DocumentRead:
    document = db.get(Document, document_id)
    if document is None:
        raise HTTPException(status_code=404, detail=f"找不到文档，文档编号：{document_id}")
    return document_to_read(db, document)


@app.post("/api/documents/{document_id}/retry", response_model=DocumentRead, status_code=202)
def retry_document(
    document_id: int, background_tasks: BackgroundTasks, db: Session = Depends(get_db)
) -> DocumentRead:
    document = db.get(Document, document_id)
    if document is None:
        raise HTTPException(status_code=404, detail=f"找不到文档，文档编号：{document_id}")
    if document.status not in ("failed", "review_required", "reviewed"):
        raise HTTPException(status_code=409, detail=f"当前状态不能重新处理：{document.status}")
    document.status = "queued"
    document.processing_mode = "rules_only"
    document.error_message = None
    add_audit_log(
        db,
        "document_retried",
        "document",
        str(document.id),
        "当前用户",
        {"processing_mode": "rules_only"},
    )
    db.commit()
    response = document_to_read(db, document)
    background_tasks.add_task(process_document_queue, document.id)
    return response


@app.post("/api/documents/{document_id}/retry-targeted", response_model=DocumentRead, status_code=202)
def retry_document_targeted(
    document_id: int, background_tasks: BackgroundTasks, db: Session = Depends(get_db)
) -> DocumentRead:
    document = db.get(Document, document_id)
    if document is None:
        raise HTTPException(status_code=404, detail=f"找不到文档，文档编号：{document_id}")
    can_retry = (
        document.status == "failed"
        and "核心财务报表识别不完整" in (document.error_message or "")
    ) or (
        document.status == "review_required"
        and "疑似行号或附注号" in (document.error_message or "")
    )
    if not can_retry:
        raise HTTPException(status_code=409, detail="当前文件不适用疑点页补读")
    if not mineru_cache_path(settings.storage_dir, document.sha256).exists():
        raise HTTPException(status_code=409, detail="没有已有 MinerU 识别结果，请重新识别原文件")
    if not settings.mineru_api_url:
        raise HTTPException(status_code=409, detail="MinerU 服务尚未配置，无法补读疑点页")
    document.status = "queued"
    document.processing_mode = "targeted"
    document.error_message = None
    add_audit_log(
        db, "document_retried", "document", str(document.id), "当前用户",
        {"processing_mode": "targeted"},
    )
    db.commit()
    response = document_to_read(db, document)
    background_tasks.add_task(process_document_queue, document.id)
    return response


@app.post(
    "/api/documents/{document_id}/recognize-again",
    response_model=DocumentRead,
    status_code=202,
)
def recognize_document_again(
    document_id: int, background_tasks: BackgroundTasks, db: Session = Depends(get_db)
) -> DocumentRead:
    document = db.get(Document, document_id)
    if document is None:
        raise HTTPException(status_code=404, detail=f"找不到文档，文档编号：{document_id}")
    if document.status not in ("failed", "review_required", "reviewed"):
        raise HTTPException(status_code=409, detail=f"当前状态不能重新识别：{document.status}")
    document.status = "queued"
    document.processing_mode = "force_mineru"
    document.mineru_task_id = None
    document.mineru_task_status = None
    document.scan_stage = None
    document.scan_source_page_count = None
    document.mineru_submitted_at = None
    document.mineru_heartbeat_at = None
    document.error_message = None
    clear_mineru_stage_caches(settings.storage_dir, document.sha256)
    plan_file = settings.storage_dir / "_mineru_cache" / f"{document.sha256}.plan.json"
    if plan_file.exists():
        plan_file.unlink()
    add_audit_log(
        db,
        "document_recognition_restarted",
        "document",
        str(document.id),
        "当前用户",
        {"processing_mode": "force_mineru"},
    )
    db.commit()
    response = document_to_read(db, document)
    background_tasks.add_task(process_document_queue, document.id)
    return response


@app.get("/api/fields", response_model=list[FieldRead])
def list_fields(
    company_id: int | None = None,
    document_id: int | None = None,
    field_status: str | None = None,
    db: Session = Depends(get_db),
) -> list[FieldRead]:
    query = (
        select(ExtractedField)
        .options(joinedload(ExtractedField.document), joinedload(ExtractedField.company))
        .order_by(ExtractedField.id.desc())
    )
    if company_id is not None:
        query = query.where(ExtractedField.company_id == company_id)
    if document_id is not None:
        query = query.where(ExtractedField.document_id == document_id)
    if field_status is not None:
        query = query.where(ExtractedField.status == field_status)
    fields = list(db.scalars(query).all())
    return [field_to_read(field) for field in sorted(fields, key=field_review_sort_key)]


@app.patch("/api/fields/{field_id}", response_model=FieldRead)
def review_field(field_id: int, payload: FieldReview, db: Session = Depends(get_db)) -> FieldRead:
    allowed_statuses = {"confirmed", "corrected", "missing"}
    if payload.status not in allowed_statuses:
        raise HTTPException(status_code=422, detail=f"无效复核状态：{payload.status}")
    field = db.scalar(
        select(ExtractedField)
        .options(joinedload(ExtractedField.document), joinedload(ExtractedField.company))
        .where(ExtractedField.id == field_id)
    )
    if field is None:
        raise HTTPException(status_code=404, detail=f"找不到待复核字段，字段编号：{field_id}")
    source_page = payload.source_page if "source_page" in payload.model_fields_set else field.source_page
    source_quote = payload.source_quote if "source_quote" in payload.model_fields_set else field.source_quote
    if payload.status in {"confirmed", "corrected"} and source_page is None:
        raise HTTPException(status_code=422, detail="来源页码已撤销，须先按原件重新定位后才能确认")
    if payload.status in {"confirmed", "corrected"} and not (source_quote or "").strip():
        raise HTTPException(status_code=422, detail="确认字段时必须填写原文证据")
    if payload.status in {"confirmed", "corrected"} and field.source_page is None and source_quote == field.source_quote:
        raise HTTPException(status_code=422, detail="原来源说明已撤销，须填写单体报表原文证据")
    previous_value = field.value_text
    if payload.status == "missing":
        field.value_text = None
        field.normalized_value = None
    else:
        if payload.value_text is None or payload.value_text.strip() == "":
            raise HTTPException(status_code=422, detail="确认或修改字段时必须填写数值")
        field.value_text = payload.value_text.strip()
        try:
            field.normalized_value = Decimal(
                payload.value_text.replace(",", "").replace("，", "").strip()
            )
        except InvalidOperation as exc:
            raise HTTPException(status_code=422, detail=f"数值格式无效：{payload.value_text}") from exc
    if payload.status == "corrected" and field.original_value is None:
        field.original_value = previous_value
    field.unit = payload.unit
    field.period = payload.period
    field.source_page = source_page
    field.source_quote = source_quote
    field.status = payload.status
    field.reviewed_by = payload.reviewer
    field.reviewed_at = datetime.now(timezone.utc)
    save_manual_metric_decision(db, field)
    add_audit_log(
        db,
        "field_reviewed",
        "field",
        str(field.id),
        payload.reviewer,
        {"status": payload.status, "before": previous_value, "after": field.value_text},
    )
    update_document_review_status(db, field.document_id, payload.reviewer)
    db.commit()
    db.refresh(field)
    return field_to_read(field)


@app.post("/api/fields/batch-confirm", response_model=list[FieldRead])
def batch_confirm(payload: BatchConfirm, db: Session = Depends(get_db)) -> list[FieldRead]:
    fields = db.scalars(
        select(ExtractedField)
        .options(joinedload(ExtractedField.document), joinedload(ExtractedField.company))
        .where(ExtractedField.id.in_(payload.field_ids))
    ).all()
    if len(fields) != len(set(payload.field_ids)):
        raise HTTPException(status_code=404, detail="部分待复核字段不存在")
    non_pending_ids = [field.id for field in fields if field.status != "pending"]
    if len(non_pending_ids) > 0:
        raise HTTPException(status_code=409, detail=f"只能批量确认待复核字段：{non_pending_ids}")
    incomplete_ids = [
        field.id for field in fields
        if field.normalized_value is None or field.source_page is None or not field.source_quote
    ]
    if incomplete_ids:
        raise HTTPException(status_code=422, detail=f"这些字段缺少数值或来源，不能批量确认：{incomplete_ids}")
    reviewed_at = datetime.now(timezone.utc)
    for field in fields:
        field.status = "confirmed"
        field.reviewed_by = payload.reviewer
        field.reviewed_at = reviewed_at
        save_manual_metric_decision(db, field)
        add_audit_log(
            db, "field_reviewed", "field", str(field.id), payload.reviewer, {"status": "confirmed"}
        )
    for document_id in {field.document_id for field in fields}:
        update_document_review_status(db, document_id, payload.reviewer)
    db.commit()
    return [field_to_read(field) for field in fields]


@app.get("/api/companies/{company_id}/financial-snapshot", response_model=list[FinancialSnapshotItem])
def financial_snapshot(company_id: int, db: Session = Depends(get_db)) -> list[FinancialSnapshotItem]:
    if db.get(Company, company_id) is None:
        raise HTTPException(status_code=404, detail=f"找不到企业，企业编号：{company_id}")
    fields = db.scalars(
        select(ExtractedField)
        .join(ExtractedField.document)
        .options(joinedload(ExtractedField.document))
        .where(ExtractedField.company_id == company_id,
               Document.document_type == "financial_statement")
        .order_by(ExtractedField.period.desc(), ExtractedField.label)
    ).all()
    return [
        FinancialSnapshotItem.model_validate(field, from_attributes=True).model_copy(
            update={
                "label": finance_display_label(field.field_code, field.label),
                "document_filename": field.document.filename,
            }
        )
        for field in preferred_fields(list(fields))
    ]


@app.get("/api/companies/{company_id}/tax-snapshot", response_model=list[FinancialSnapshotItem])
def tax_snapshot(company_id: int, db: Session = Depends(get_db)) -> list[FinancialSnapshotItem]:
    if db.get(Company, company_id) is None:
        raise HTTPException(status_code=404, detail=f"找不到企业，企业编号：{company_id}")
    fields = db.scalars(
        select(ExtractedField)
        .join(ExtractedField.document)
        .options(joinedload(ExtractedField.document))
        .where(ExtractedField.company_id == company_id,
               Document.document_type.in_(TAX_DOCUMENT_TYPES))
        .order_by(Document.id.desc(), ExtractedField.id)
    ).all()
    return [
        FinancialSnapshotItem.model_validate(field, from_attributes=True).model_copy(
            update={"document_filename": field.document.filename}
        )
        for field in fields if field.status != "missing" and field.normalized_value is not None
    ]


@app.get("/api/metrics", response_model=list[MetricOptionRead])
def list_available_metrics(db: Session = Depends(get_db)) -> list[MetricOptionRead]:
    rows = db.execute(
        select(ExtractedField.field_code, ExtractedField.label)
        .join(ExtractedField.document)
        .where(Document.document_type == "financial_statement")
        .distinct()
    ).all()
    labels = {
        str(code): finance_display_label(str(code), str(label))
        for code, label in sorted(rows)
    }
    return [
        MetricOptionRead(code=code, label=labels[code])
        for code in sorted(labels, key=finance_wide_field_order)
    ]


def metric_export_response(field_codes: list[str], db: Session) -> Response:
    selected_codes = list(dict.fromkeys(field_codes))
    if len(selected_codes) == 0:
        raise HTTPException(status_code=422, detail="请至少选择一个指标")
    fields = list(
        db.scalars(
            select(ExtractedField)
            .options(joinedload(ExtractedField.document), joinedload(ExtractedField.company))
            .where(ExtractedField.field_code.in_(selected_codes))
        ).all()
    )
    found_codes = {field.field_code for field in fields}
    missing_codes = [code for code in selected_codes if code not in found_codes]
    if len(missing_codes) > 0:
        raise HTTPException(
            status_code=404,
            detail=f"没有找到指标数据：{'、'.join(missing_codes)}",
        )
    balance_fields = list(db.scalars(
        select(ExtractedField)
        .options(joinedload(ExtractedField.document), joinedload(ExtractedField.company))
        .where(
            ExtractedField.document_id.in_({field.document_id for field in fields}),
            ExtractedField.field_code.in_(("total_assets", "total_liabilities", "owners_equity")),
        )
    ).all())
    candidates = {field.id: field for field in fields + balance_fields}
    selected_fields = [
        field for field in preferred_fields_by_company(list(candidates.values()))
        if field.field_code in selected_codes
    ]
    content = build_metric_workbook(selected_fields)
    labels_by_code = {
        field.field_code: finance_display_label(field.field_code, field.label)
        for field in fields
    }
    selected_labels = [labels_by_code[code] for code in selected_codes]
    export_label = selected_labels[0] if len(selected_labels) == 1 else f"{len(selected_labels)}项指标"
    safe_label = "".join(
        character for character in export_label if character not in '\\/:*?\"<>|'
    )
    encoded_name = quote(f"全部企业-{safe_label}.xlsx")
    headers = {"Content-Disposition": f"attachment; filename*=UTF-8''{encoded_name}"}
    return Response(
        content=content,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers=headers,
    )


@app.get("/api/metrics/export.xlsx")
def export_metrics(
    field_codes: list[str] = Query(...), db: Session = Depends(get_db)
) -> Response:
    return metric_export_response(field_codes, db)


@app.get("/api/metrics/{field_code}/export.xlsx")
def export_metric(field_code: str, db: Session = Depends(get_db)) -> Response:
    return metric_export_response([field_code], db)


@app.get("/api/companies/{company_id}/export.xlsx")
def export_company(company_id: int, db: Session = Depends(get_db)) -> Response:
    company = db.get(Company, company_id)
    if company is None:
        raise HTTPException(status_code=404, detail=f"找不到企业，企业编号：{company_id}")
    fields = db.scalars(
        select(ExtractedField)
        .join(ExtractedField.document)
        .options(joinedload(ExtractedField.document))
        .where(ExtractedField.company_id == company_id,
               Document.document_type == "financial_statement")
        .order_by(ExtractedField.period, ExtractedField.label)
    ).all()
    if len(fields) == 0:
        raise HTTPException(status_code=409, detail="该企业还没有可导出的财务数据")
    content = build_financial_workbook(company, preferred_fields(list(fields)))
    safe_name = "".join(character for character in company.name if character not in '\\/:*?\"<>|')
    encoded_name = quote(f"{safe_name}财务数据.xlsx")
    headers = {"Content-Disposition": f"attachment; filename*=UTF-8''{encoded_name}"}
    return Response(
        content=content,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers=headers,
    )


@app.get("/api/companies/{company_id}/tax-export.xlsx")
def export_company_tax(company_id: int, db: Session = Depends(get_db)) -> Response:
    company = db.get(Company, company_id)
    if company is None:
        raise HTTPException(status_code=404, detail=f"找不到企业，企业编号：{company_id}")
    fields = db.scalars(
        select(ExtractedField)
        .join(ExtractedField.document)
        .options(joinedload(ExtractedField.document))
        .where(ExtractedField.company_id == company_id,
               Document.document_type.in_(TAX_DOCUMENT_TYPES))
        .order_by(Document.id.desc(), ExtractedField.id)
    ).all()
    usable_fields = [
        field for field in fields
        if field.status != "missing" and field.normalized_value is not None
    ]
    if len(usable_fields) == 0:
        raise HTTPException(status_code=409, detail="该企业还没有可导出的税务数据")
    content = build_financial_workbook(
        company, usable_fields, "税务数据",
    )
    safe_name = "".join(character for character in company.name if character not in '\\/:*?"<>|')
    encoded_name = quote(f"{safe_name}税务数据.xlsx")
    return Response(
        content=content,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{encoded_name}"},
    )


static_dir = Path(__file__).parent / "static"
app.mount("/", StaticFiles(directory=static_dir, html=True), name="static")
