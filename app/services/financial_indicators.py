from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

from app.services.financial_extractor import ExtractedMetric, MetricDefinition


@dataclass(frozen=True)
class HistoricalMetric:
    code: str
    value: Decimal
    unit: str
    period: str
    source_page: int | None
    source_quote: str | None


DERIVED_DEFINITIONS: dict[str, MetricDefinition] = {
    "operating_revenue_yoy": MetricDefinition(
        "operating_revenue_yoy", "营业收入同比增长率", (), "计算指标"
    ),
    "main_business_revenue_yoy": MetricDefinition(
        "main_business_revenue_yoy", "主营业务收入同比增长率", (), "计算指标"
    ),
    "net_profit_yoy": MetricDefinition("net_profit_yoy", "净利润同比增长率", (), "计算指标"),
    "operating_revenue_cagr": MetricDefinition(
        "operating_revenue_cagr", "营业收入复合增长率", (), "计算指标"
    ),
    "main_business_revenue_cagr": MetricDefinition(
        "main_business_revenue_cagr", "主营业务收入复合增长率", (), "计算指标"
    ),
    "rd_to_revenue": MetricDefinition(
        "rd_to_revenue", "研发费用占营业收入比例", (), "计算指标"
    ),
    "rd_to_main_revenue": MetricDefinition(
        "rd_to_main_revenue", "研发费用占主营业务收入比例", (), "计算指标"
    ),
    "asset_liability_ratio": MetricDefinition(
        "asset_liability_ratio", "资产负债率", (), "计算指标"
    ),
    "net_margin": MetricDefinition("net_margin", "净利率", (), "计算指标"),
}


def value_in_yuan(value: Decimal, unit: str) -> Decimal:
    multipliers = {"元": Decimal("1"), "千元": Decimal("1000"), "万元": Decimal("10000")}
    multiplier = multipliers.get(unit)
    if multiplier is None:
        raise ValueError(f"不支持用于指标计算的单位：{unit}")
    return value * multiplier


def format_percentage(value: Decimal) -> str:
    rounded = value.quantize(Decimal("0.0001"))
    return format(rounded, "f").rstrip("0").rstrip(".") or "0"


def build_derived_metric(
    code: str, value: Decimal, period: str | None, source_page: int, source_quote: str
) -> ExtractedMetric:
    return ExtractedMetric(
        definition=DERIVED_DEFINITIONS[code],
        value_text=format_percentage(value),
        normalized_value=value,
        unit="%",
        period=period,
        source_page=source_page,
        source_quote=source_quote[:500],
        confidence=Decimal("1"),
    )


def current_metric_index(metrics: list[ExtractedMetric]) -> dict[str, ExtractedMetric]:
    indexed: dict[str, ExtractedMetric] = {}
    for metric in metrics:
        existing = indexed.get(metric.definition.code)
        if existing is None or (metric.period or "") > (existing.period or ""):
            indexed[metric.definition.code] = metric
    return indexed


def historical_index(
    history: list[HistoricalMetric], metrics: list[ExtractedMetric]
) -> dict[str, dict[int, tuple[Decimal, str]]]:
    indexed: dict[str, dict[int, tuple[Decimal, str]]] = {}
    for item in history:
        try:
            year = int(item.period)
            value = value_in_yuan(item.value, item.unit)
        except (ValueError, InvalidOperation):
            continue
        indexed.setdefault(item.code, {}).setdefault(year, (value, item.period))
    for metric in metrics:
        if metric.period is None:
            continue
        try:
            year = int(metric.period)
            value = value_in_yuan(metric.normalized_value, metric.unit)
        except (ValueError, InvalidOperation):
            continue
        indexed.setdefault(metric.definition.code, {})[year] = (value, metric.period)
    return indexed


def calculate_ratio(
    result_code: str,
    numerator_code: str,
    denominator_code: str,
    current: dict[str, ExtractedMetric],
) -> ExtractedMetric | None:
    numerator = current.get(numerator_code)
    denominator = current.get(denominator_code)
    if numerator is None or denominator is None:
        return None
    numerator_value = value_in_yuan(numerator.normalized_value, numerator.unit)
    denominator_value = value_in_yuan(denominator.normalized_value, denominator.unit)
    if denominator_value == 0:
        return None
    percentage = numerator_value / denominator_value * Decimal("100")
    quote = (
        f"按已提取值计算：{numerator.definition.label} {numerator.value_text}{numerator.unit} ÷ "
        f"{denominator.definition.label} {denominator.value_text}{denominator.unit} × 100"
    )
    return build_derived_metric(
        result_code, percentage, numerator.period, numerator.source_page, quote
    )


def calculate_yoy(
    result_code: str,
    base_code: str,
    current: dict[str, ExtractedMetric],
    indexed: dict[str, dict[int, tuple[Decimal, str]]],
) -> ExtractedMetric | None:
    metric = current.get(base_code)
    if metric is None or metric.period is None:
        return None
    current_year = int(metric.period)
    values = indexed.get(base_code, {})
    current_item = values.get(current_year)
    previous_item = values.get(current_year - 1)
    if current_item is None or previous_item is None or previous_item[0] == 0:
        return None
    if base_code == "net_profit" and (current_item[0] <= 0 or previous_item[0] <= 0):
        return None
    percentage = (current_item[0] / previous_item[0] - Decimal("1")) * Decimal("100")
    quote = (
        f"按已提取值计算：{metric.definition.label} {current_year}年 {current_item[0]}元，"
        f"{current_year - 1}年 {previous_item[0]}元"
    )
    return build_derived_metric(result_code, percentage, metric.period, metric.source_page, quote)


def calculate_cagr(
    result_code: str,
    base_code: str,
    current: dict[str, ExtractedMetric],
    indexed: dict[str, dict[int, tuple[Decimal, str]]],
) -> ExtractedMetric | None:
    metric = current.get(base_code)
    if metric is None or metric.period is None:
        return None
    current_year = int(metric.period)
    values = indexed.get(base_code, {})
    earlier_years = sorted(year for year in values if year < current_year)
    if len(earlier_years) == 0:
        return None
    start_year = earlier_years[0]
    start_value = values[start_year][0]
    end_value = values[current_year][0]
    year_count = current_year - start_year
    # A one-year CAGR is indistinguishable from YoY and was previously able to
    # hide a missing historical base as a multi-year growth metric.
    if start_value <= 0 or end_value <= 0 or year_count < 2:
        return None
    percentage = Decimal(str(((float(end_value / start_value) ** (1 / year_count)) - 1) * 100))
    quote = (
        f"按已提取值计算：{metric.definition.label} {start_year}年 {start_value}元，"
        f"{current_year}年 {end_value}元，跨度 {year_count} 年"
    )
    return build_derived_metric(result_code, percentage, metric.period, metric.source_page, quote)


def calculate_financial_indicators(
    metrics: list[ExtractedMetric], history: list[HistoricalMetric]
) -> list[ExtractedMetric]:
    current = current_metric_index(metrics)
    indexed = historical_index(history, metrics)
    candidates = [
        calculate_yoy("operating_revenue_yoy", "operating_revenue", current, indexed),
        calculate_yoy(
            "main_business_revenue_yoy", "main_business_revenue", current, indexed
        ),
        calculate_yoy("net_profit_yoy", "net_profit", current, indexed),
        calculate_cagr("operating_revenue_cagr", "operating_revenue", current, indexed),
        calculate_cagr(
            "main_business_revenue_cagr", "main_business_revenue", current, indexed
        ),
        calculate_ratio("rd_to_revenue", "rd_expenses", "operating_revenue", current),
        calculate_ratio(
            "rd_to_main_revenue", "rd_expenses", "main_business_revenue", current
        ),
        calculate_ratio(
            "asset_liability_ratio", "total_liabilities", "total_assets", current
        ),
        calculate_ratio("net_margin", "net_profit", "operating_revenue", current),
    ]
    return [candidate for candidate in candidates if candidate is not None]
