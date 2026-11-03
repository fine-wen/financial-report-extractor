from decimal import Decimal

from app.models import ExtractedField
from app.services.evidence_review import field_evidence_risk_reasons
from app.services.financial_indicators import DERIVED_DEFINITIONS, value_in_yuan
from app.services.metric_catalog import finance_wide_field_order


CORE_REVIEW_CODES: frozenset[str] = frozenset(
    {
        "total_assets",
        "total_liabilities",
        "owners_equity",
        "operating_revenue",
        "operating_cost",
        "operating_profit",
        "total_profit",
        "net_profit",
        "selling_expenses",
        "administrative_expenses",
        "rd_expenses",
        "main_business_revenue",
        "main_business_cost",
        "vat_payable_cumulative",
        "corporate_income_tax_payable",
        "corporate_income_tax_prepayment_due",
        "tax_payment_net_total",
    }
)

STATEMENT_REQUIREMENTS: dict[str, tuple[str, ...]] = {
    "balance_sheet": ("total_assets", "total_liabilities", "owners_equity"),
    "income_statement": ("operating_revenue", "net_profit"),
    "cash_flow_statement": ("operating_cash_flow",),
}


def field_risk_reasons(field: ExtractedField) -> list[str]:
    reasons: list[str] = []
    if field.field_code in CORE_REVIEW_CODES or field.field_code.startswith("tax_payment_line_"):
        reasons.append("核心指标")
    if field.confidence < Decimal("0.95"):
        reasons.append("可信度低于95%")
    if field.source_page is None or field.source_quote is None or field.source_quote.strip() == "":
        reasons.append("来源证据不完整")
    if (
        field.source_quote is not None
        and "<table" in field.source_quote.lower()
        and len(field.source_quote) >= 480
    ):
        reasons.append("识别定位范围过大")
    if (
        field.field_code in DERIVED_DEFINITIONS
        and field.normalized_value is not None
        and abs(field.normalized_value) > Decimal("1000")
    ):
        reasons.append("计算结果异常")
    reasons.extend(
        field_evidence_risk_reasons(
            field.field_code,
            field.normalized_value,
            field.unit,
            field.source_quote,
        )
    )
    return list(dict.fromkeys(reasons))


def field_review_priority(field: ExtractedField) -> str:
    if field.field_code in DERIVED_DEFINITIONS:
        return "calculated"
    return "high" if len(field_risk_reasons(field)) > 0 else "normal"


def field_review_sort_key(
    field: ExtractedField,
) -> tuple[int, int, tuple[int, int | str], int, str, int]:
    priority_order = {"high": 0, "normal": 1, "calculated": 2}
    status_order = 0 if field.status == "pending" else 1
    return (
        status_order,
        -int(field.period) if field.period is not None and field.period.isdigit() else 0,
        finance_wide_field_order(field.field_code),
        priority_order[field_review_priority(field)],
        field.label,
        field.id,
    )


def statement_status(fields: list[ExtractedField], required_codes: tuple[str, ...]) -> str:
    base_fields = [field for field in fields if field.field_code not in DERIVED_DEFINITIONS]
    detected_codes = {field.field_code for field in base_fields}
    if len(detected_codes.intersection(required_codes)) == 0:
        return "missing"
    periods = sorted({field.period for field in base_fields if field.period is not None})
    if len(periods) == 0:
        return "partial"
    for period in periods:
        period_codes = {field.field_code for field in base_fields if field.period == period}
        if not set(required_codes).issubset(period_codes):
            return "partial"
    return "complete"


def balance_check(fields: list[ExtractedField]) -> tuple[str, list[str]]:
    balance_codes = ("total_assets", "total_liabilities", "owners_equity")
    values: dict[str, dict[str, tuple[Decimal, str]]] = {}
    for field in fields:
        if (
            field.field_code not in balance_codes
            or field.period is None
            or field.normalized_value is None
            or field.unit is None
        ):
            continue
        values.setdefault(field.period, {})[field.field_code] = (
            field.normalized_value,
            field.unit,
        )
    checked_periods: list[str] = []
    for period, period_values in sorted(values.items(), reverse=True):
        if not set(balance_codes).issubset(period_values):
            continue
        checked_periods.append(period)
        assets = value_in_yuan(*period_values["total_assets"])
        liabilities = value_in_yuan(*period_values["total_liabilities"])
        equity = value_in_yuan(*period_values["owners_equity"])
        if abs(assets - liabilities - equity) > Decimal("1"):
            return "warning", checked_periods
    return ("passed", checked_periods) if len(checked_periods) > 0 else ("unavailable", [])


def document_check_summary(fields: list[ExtractedField], statement_scope: str | None) -> dict[str, object]:
    base_fields = [field for field in fields if field.field_code not in DERIVED_DEFINITIONS]
    calculated_fields = [field for field in fields if field.field_code in DERIVED_DEFINITIONS]
    pending_fields = [field for field in fields if field.status == "pending"]
    reviewed_fields = [field for field in fields if field.status in ("confirmed", "corrected", "missing")]
    risky_pending_fields = [
        field for field in pending_fields if field_review_priority(field) == "high"
    ]
    suspicious_pending_fields = [
        field
        for field in pending_fields
        if any(reason != "核心指标" for reason in field_risk_reasons(field))
    ]
    balance_status, balance_periods = balance_check(base_fields)
    return {
        "periods": sorted(
            {field.period for field in base_fields if field.period is not None}, reverse=True
        ),
        "statement_scope": statement_scope,
        "base_field_count": len(base_fields),
        "calculated_field_count": len(calculated_fields),
        "pending_count": len(pending_fields),
        "reviewed_count": len(reviewed_fields),
        "high_priority_count": len(risky_pending_fields),
        "suspicious_count": len(suspicious_pending_fields),
        "balance_sheet_status": statement_status(base_fields, STATEMENT_REQUIREMENTS["balance_sheet"]),
        "income_statement_status": statement_status(base_fields, STATEMENT_REQUIREMENTS["income_statement"]),
        "cash_flow_statement_status": statement_status(base_fields, STATEMENT_REQUIREMENTS["cash_flow_statement"]),
        "balance_status": balance_status,
        "balance_periods": balance_periods,
    }
