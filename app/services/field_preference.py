from decimal import Decimal

from app.models import ExtractedField
from app.services.financial_extractor import filename_period
from app.services.metric_catalog import finance_wide_field_order


def report_year(field: ExtractedField) -> int:
    period = filename_period(field.document.filename)
    return int(period) if period is not None else 0


def grossly_unbalanced_sources(fields: list[ExtractedField]) -> set[tuple[int, str | None]]:
    grouped: dict[tuple[int, str | None], dict[str, Decimal]] = {}
    multipliers = {"元": Decimal("1"), "千元": Decimal("1000"), "万元": Decimal("10000")}
    for field in fields:
        if field.normalized_value is None or field.status == "missing":
            continue
        if field.field_code not in {"total_assets", "total_liabilities", "owners_equity"}:
            continue
        multiplier = multipliers.get(field.unit or "元")
        if multiplier is None:
            continue
        grouped.setdefault((field.document_id, field.period), {})[field.field_code] = (
            field.normalized_value * multiplier
        )
    rejected: set[tuple[int, str | None]] = set()
    for key, amounts in grouped.items():
        if len(amounts) != 3:
            continue
        assets = amounts["total_assets"]
        funding = amounts["total_liabilities"] + amounts["owners_equity"]
        if abs(assets - funding) > max(Decimal("100000"), max(abs(assets), abs(funding)) * Decimal("0.1")):
            rejected.add(key)
    return rejected


def preferred_fields(fields: list[ExtractedField]) -> list[ExtractedField]:
    selected: dict[tuple[str, str | None], ExtractedField] = {}
    rejected_sources = grossly_unbalanced_sources(fields)
    for field in fields:
        if field.status == "missing" or field.normalized_value is None:
            continue
        if (field.document_id, field.period) in rejected_sources:
            continue
        key = (field.field_code, field.period)
        existing = selected.get(key)
        if existing is None or (report_year(field), field.document_id, field.id) > (
            report_year(existing),
            existing.document_id,
            existing.id,
        ):
            selected[key] = field
    result = list(selected.values())
    result.sort(key=lambda field: (finance_wide_field_order(field.field_code), field.label))
    result.sort(key=lambda field: field.period or "", reverse=True)
    return result


def preferred_fields_by_company(fields: list[ExtractedField]) -> list[ExtractedField]:
    grouped: dict[int, list[ExtractedField]] = {}
    for field in fields:
        grouped.setdefault(field.company_id, []).append(field)
    selected = [
        field
        for company_fields in grouped.values()
        for field in preferred_fields(company_fields)
    ]
    return sorted(
        selected,
        key=lambda field: (
            field.company.name,
            -(int(field.period) if field.period is not None and field.period.isdigit() else 0),
            finance_wide_field_order(field.field_code),
            field.document_id,
        ),
    )
