import re
from dataclasses import dataclass
from decimal import Decimal

from app.services.financial_extractor import (
    ExtractedMetric,
    MIXED_GROUPED_AMOUNT_PATTERN,
    NUMBER_PATTERN,
    normalize_number,
)


@dataclass(frozen=True)
class EvidenceFinding:
    code: str
    period: str | None
    field_codes: tuple[str, ...]
    message: str


MONETARY_EXCLUSIONS: frozenset[str] = frozenset(
    {
        "vat_payable_cumulative",
        "corporate_income_tax_payable",
        "corporate_income_tax_prepayment_due",
        "tax_payment_net_total",
    }
)
TOTAL_ASSET_LABELS = ("资产总计", "资产总额", "totalassets")
SUBTOTAL_ASSET_LABELS = ("流动资产合计", "非流动资产合计")
CURRENT_ASSET_COMPONENT_CODES = (
    "cash", "short_term_investments", "trading_financial_assets", "notes_receivable",
    "receivables_financing", "accounts_receivable", "contract_assets", "prepayments",
    "other_receivables", "centralized_fund_receivables", "inventory", "current_portion_noncurrent_assets", "other_current_assets",
)
NOTE_REFERENCE_PATTERN = re.compile(
    r"(?:附注)?[一二三四五六七八九十百]+[、.．]\s*(\d{1,3})(?:\s+|\s*\|\s*)"
    r"[-（(]?[\d,，]+\.\d+"
)
TOC_PAGE_PATTERN = re.compile(r"(?:表|附注)\s*[.．…·]{2,}\s*\d{1,3}(?:[-—]\d{1,3})?")


def quote_amounts(source_quote: str) -> list[Decimal]:
    amounts: list[Decimal] = []
    for raw_value in NUMBER_PATTERN.findall(source_quote):
        try:
            amounts.append(normalize_number(raw_value))
        except ValueError:
            continue
    return amounts


def field_evidence_risk_reasons(
    field_code: str,
    normalized_value: Decimal | None,
    unit: str | None,
    source_quote: str | None,
) -> list[str]:
    if normalized_value is None or source_quote is None or source_quote.strip() == "":
        return []
    reasons: list[str] = []
    quote = re.sub(r"\s+", " ", source_quote).strip()
    absolute_value = abs(normalized_value)
    if unit == "元" and normalized_value < 0 and field_code in {
        "operating_cost", "main_business_cost", "taxes_surcharges",
        "selling_expenses", "administrative_expenses", "rd_expenses",
    }:
        reasons.append("成本费用为负数，需核对括号减项列示或真实冲回")
    if (
        field_code not in MONETARY_EXCLUSIONS
        and not field_code.startswith("tax_payment_line_")
        and unit == "元"
        and Decimal("0") < absolute_value <= Decimal("100")
    ):
        larger_amounts = [amount for amount in quote_amounts(quote) if abs(amount) >= Decimal("1000")]
        if len(larger_amounts) > 0:
            reasons.append("小额数值旁存在大额金额，疑似行号或附注号")
        else:
            reasons.append("金额异常偏小，需核对是否为行号或附注号")
    note_match = NOTE_REFERENCE_PATTERN.search(quote)
    if note_match is not None and absolute_value == Decimal(note_match.group(1)):
        reasons.append("识别值与原文附注序号相同")
    if "目录" in quote or TOC_PAGE_PATTERN.search(quote) is not None:
        reasons.append("来源疑似目录页码")
    if any(
        "." in match.group(0)[: match.group(0).rfind(".")]
        for match in MIXED_GROUPED_AMOUNT_PATTERN.finditer(quote)
    ):
        reasons.append("原文金额分隔符异常，需核对原件")
    normalized_quote = re.sub(r"\s+", "", quote).lower()
    has_asset_total = any(label in normalized_quote for label in TOTAL_ASSET_LABELS) or (
        re.search(r"(?:^|\|)资产合计", normalized_quote) is not None
    )
    if field_code == "total_assets" and any(
        subtotal in normalized_quote for subtotal in SUBTOTAL_ASSET_LABELS
    ) and not has_asset_total:
        reasons.append("资产总额来源疑似资产小计")
    return list(dict.fromkeys(reasons))


def metric_value_map(
    metrics: list[ExtractedMetric], period: str
) -> dict[str, ExtractedMetric]:
    return {
        metric.definition.code: metric
        for metric in metrics
        if metric.period == period
    }


def balance_difference_finding(
    metrics: list[ExtractedMetric], period: str
) -> EvidenceFinding | None:
    values = metric_value_map(metrics, period)
    required = ("total_assets", "total_liabilities", "owners_equity")
    if not all(code in values for code in required):
        return None
    difference = (
        values["total_assets"].normalized_value
        - values["total_liabilities"].normalized_value
        - values["owners_equity"].normalized_value
    )
    # Yuan totals must balance within rounding, regardless of company size.
    if all(values[code].unit == "元" for code in required):
        tolerance = Decimal("1")
    else:
        tolerance = max(abs(values["total_assets"].normalized_value) * Decimal("0.001"), Decimal("1"))
    if abs(difference) <= tolerance:
        return None
    excluded_codes = {
        "total_assets",
        "total_liabilities",
        "owners_equity",
        "current_assets",
        "current_liabilities",
        "long_term_liabilities",
    }
    matching = next(
        (
            metric
            for code, metric in values.items()
            if code not in excluded_codes
            and abs(abs(metric.normalized_value) - abs(difference)) <= Decimal("1")
        ),
        None,
    )
    if matching is None:
        return EvidenceFinding(
            code="balance_mismatch",
            period=period,
            field_codes=required,
            message=f"{period}年资产负债表相差{difference}，暂未找到对应差额项目",
        )
    return EvidenceFinding(
        code="balance_difference_matches_metric",
        period=period,
        field_codes=("total_assets", "total_liabilities", "owners_equity", matching.definition.code),
        message=(
            f"{period}年资产负债表相差{difference}，差额与{matching.definition.label}"
            f"{matching.normalized_value}相同，疑似总计误取小计或漏计该项目"
        ),
    )


def current_assets_components_finding(
    metrics: list[ExtractedMetric], period: str
) -> EvidenceFinding | None:
    """Warn when the extracted current-asset lines do not explain the subtotal.

    This is a completeness check only: the difference is never assigned to a
    metric because it could represent one or more undisclosed or missed rows.
    """
    values = metric_value_map(metrics, period)
    total = values.get("current_assets")
    components = [values[code] for code in CURRENT_ASSET_COMPONENT_CODES if code in values]
    if total is None or not components:
        return None
    difference = total.normalized_value - sum(
        (metric.normalized_value for metric in components), Decimal("0")
    )
    tolerance = Decimal("1") if total.unit == "元" and all(item.unit == "元" for item in components) else max(abs(total.normalized_value) * Decimal("0.001"), Decimal("1"))
    if abs(difference) <= tolerance:
        return None
    return EvidenceFinding(
        code="current_assets_components_mismatch",
        period=period,
        field_codes=("current_assets", *(item.definition.code for item in components)),
        message=(
            f"{period}年流动资产合计与已提取的流动资产明细相差{difference}，"
            "可能有明细漏提或原件口径差异；请回看资产负债表，不按差额补数"
        ),
    )


def review_financial_evidence(metrics: list[ExtractedMetric]) -> list[EvidenceFinding]:
    findings: list[EvidenceFinding] = []
    for metric in metrics:
        reasons = field_evidence_risk_reasons(
            metric.definition.code,
            metric.normalized_value,
            metric.unit,
            metric.source_quote,
        )
        for reason in reasons:
            findings.append(
                EvidenceFinding(
                    code="field_source_anomaly",
                    period=metric.period,
                    field_codes=(metric.definition.code,),
                    message=f"{metric.period or '未知年度'}年{metric.definition.label}：{reason}",
                )
            )
    periods = sorted({metric.period for metric in metrics if metric.period is not None})
    for period in periods:
        finding = balance_difference_finding(metrics, period)
        if finding is not None:
            findings.append(finding)
        finding = current_assets_components_finding(metrics, period)
        if finding is not None:
            findings.append(finding)
    unique: dict[tuple[str, str], EvidenceFinding] = {}
    for finding in findings:
        unique[(finding.code, finding.message)] = finding
    return list(unique.values())
