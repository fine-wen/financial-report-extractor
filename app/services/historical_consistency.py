from dataclasses import dataclass
from decimal import Decimal

from app.services.financial_extractor import ExtractedMetric, filename_period


@dataclass(frozen=True)
class HistoricalReportedMetric:
    code: str
    label: str
    value: Decimal
    unit: str
    period: str
    document_filename: str
    report_year: str | None = None


UNIT_MULTIPLIERS: dict[str, Decimal] = {
    "元": Decimal("1"),
    "千元": Decimal("1000"),
    "万元": Decimal("10000"),
}


def value_in_yuan(value: Decimal, unit: str) -> Decimal | None:
    multiplier = UNIT_MULTIPLIERS.get(unit)
    return value * multiplier if multiplier is not None else None


def historical_consistency_warnings(
    metrics: list[ExtractedMetric], history: list[HistoricalReportedMetric],
    current_document_filename: str | None = None,
    current_report_year: str | None = None,
) -> list[str]:
    current_report_year = current_report_year or (
        filename_period(current_document_filename) if current_document_filename is not None else None
    )
    history_by_key: dict[tuple[str, str], list[HistoricalReportedMetric]] = {}
    for item in history:
        source_year = item.report_year or filename_period(item.document_filename)
        if (
            current_report_year is not None and source_year is not None
            and int(source_year) > int(current_report_year)
        ):
            continue
        if source_year is not None and item.period.isdigit() and int(item.period) > int(source_year):
            # A report cannot establish figures for a future financial year.
            continue
        history_by_key.setdefault((item.code, item.period), []).append(item)
    warnings: list[str] = []
    warned_keys: set[tuple[str, str]] = set()
    for metric in metrics:
        if metric.period is None:
            continue
        key = (metric.definition.code, metric.period)
        if key in warned_keys:
            continue
        current_value = value_in_yuan(metric.normalized_value, metric.unit)
        if current_value is None:
            continue
        for previous in history_by_key.get(key, []):
            previous_value = value_in_yuan(previous.value, previous.unit)
            if previous_value is None or abs(current_value - previous_value) <= Decimal("0.01"):
                continue
            warnings.append(
                f"{metric.period}年{metric.definition.label}与{previous.document_filename}不一致"
                f"（本次{current_value}元，原记录{previous_value}元）"
            )
            warned_keys.add(key)
            break
    return warnings
