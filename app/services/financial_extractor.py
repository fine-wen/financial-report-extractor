import re
from dataclasses import dataclass, replace
from datetime import datetime
from decimal import Decimal, InvalidOperation

from app.services.pdf_parser import ParsedPage


class ParentCompanyPagesUnavailableError(RuntimeError):
    pass


@dataclass(frozen=True)
class MetricDefinition:
    code: str
    label: str
    aliases: tuple[str, ...]
    category: str


@dataclass(frozen=True)
class ExtractedMetric:
    definition: MetricDefinition
    value_text: str
    normalized_value: Decimal
    unit: str
    period: str | None
    source_page: int
    source_quote: str
    confidence: Decimal


METRICS: tuple[MetricDefinition, ...] = (
    MetricDefinition(
        "operating_revenue",
        "营业收入",
        ("营业收入", "营业总收入", "营业收", "营业收人", "Operating Revenue", "Total Operating Revenue"),
        "利润表",
    ),
    MetricDefinition("main_business_revenue", "主营业务收入", ("主营业务收入", "Main Business Revenue"), "利润表"),
    MetricDefinition("operating_cost", "营业成本", ("营业成本", "Operating Cost"), "利润表"),
    MetricDefinition("main_business_cost", "主营业务成本", ("主营业务成本", "Main Business Cost"), "利润表"),
    MetricDefinition("other_business_revenue", "其他业务收入", ("其他业务收入", "Other Business Revenue"), "利润表"),
    MetricDefinition("other_business_cost", "其他业务成本", ("其他业务成本", "Other Business Cost"), "利润表"),
    MetricDefinition("taxes_surcharges", "税金及附加", ("税金及附加", "营业税金及附加", "Taxes and Surcharges"), "利润表"),
    MetricDefinition("selling_expenses", "销售费用", ("销售费用", "营业费用", "Selling Expenses"), "利润表"),
    MetricDefinition("administrative_expenses", "管理费用", ("管理费用", "Administrative Expenses"), "利润表"),
    MetricDefinition("rd_expenses", "研发费用", ("研发费用", "研发费", "研究费用", "研究开发费", "R&D Expenses"), "利润表"),
    MetricDefinition("financial_expenses", "财务费用", ("财务费用", "Financial Expenses"), "利润表"),
    MetricDefinition("interest_expense", "利息费用", ("利息费用", "Interest Expense"), "利润表"),
    MetricDefinition("interest_income", "利息收入", ("利息收入", "Interest Income"), "利润表"),
    MetricDefinition("other_income", "其他收益", ("其他收益", "Other Income"), "利润表"),
    MetricDefinition("investment_income", "投资收益", ("投资收益", "Investment Income"), "利润表"),
    MetricDefinition("fair_value_change_income", "公允价值变动收益", ("公允价值变动收益", "公允价值变动损益", "Fair Value Change Income"), "利润表"),
    MetricDefinition("credit_impairment_loss", "信用减值损失", ("信用减值损失", "Credit Impairment Loss"), "利润表"),
    MetricDefinition("asset_impairment_loss", "资产减值损失", ("资产减值损失", "Asset Impairment Loss"), "利润表"),
    MetricDefinition("asset_disposal_income", "资产处置收益", ("资产处置收益", "资产处置损益", "Gain on Disposal of Assets"), "利润表"),
    MetricDefinition("non_operating_revenue", "营业外收入", ("营业外收入", "Non-operating Income"), "利润表"),
    MetricDefinition("non_operating_expense", "营业外支出", ("营业外支出", "Non-operating Expenses"), "利润表"),
    MetricDefinition("operating_profit", "营业利润", ("营业利润", "Operating Profit"), "利润表"),
    MetricDefinition("total_profit", "利润总额", ("利润总额", "Total Profit"), "利润表"),
    MetricDefinition("income_tax_expense", "所得税费用", ("所得税费用", "Income Tax Expense"), "利润表"),
    MetricDefinition("net_profit", "净利润", ("净利润", "Net Profit"), "利润表"),
    MetricDefinition("cash", "货币资金", ("货币资金", "Cash and Cash Equivalents"), "资产负债表"),
    MetricDefinition("short_term_investments", "短期投资", ("短期投资", "Short-term Investments"), "资产负债表"),
    MetricDefinition("accounts_receivable", "应收账款", ("应收账款", "Accounts Receivable"), "资产负债表"),
    MetricDefinition("notes_receivable", "应收票据", ("应收票据", "Notes Receivable"), "资产负债表"),
    MetricDefinition("receivables_financing", "应收款项融资", ("应收款项融资", "Financing Receivables"), "资产负债表"),
    MetricDefinition("contract_assets", "合同资产", ("合同资产", "Contract Assets"), "资产负债表"),
    MetricDefinition("prepayments", "预付款项", ("预付款项", "预付账款", "Prepayments"), "资产负债表"),
    MetricDefinition("other_receivables", "其他应收款", ("其他应收款", "Other Receivables"), "资产负债表"),
    MetricDefinition("centralized_fund_receivables", "应收资金集中管理款", ("应收资金集中管理款", "资金集中管理款", "Receivable from Centralized Fund Management"), "资产负债表"),
    MetricDefinition("inventory", "存货", ("存货", "Inventory"), "资产负债表"),
    MetricDefinition("current_assets", "流动资产合计", ("流动资产合计", "Total Current Assets"), "资产负债表"),
    MetricDefinition("noncurrent_assets", "非流动资产合计", ("非流动资产合计", "非流动资产总额", "Total Non-current Assets"), "资产负债表"),
    MetricDefinition("current_portion_noncurrent_assets", "一年内到期的非流动资产", ("一年内到期的非流动资产", "Current Portion of Non-current Assets"), "资产负债表"),
    MetricDefinition("trading_financial_assets", "交易性金融资产", ("交易性金融资产", "Trading Financial Assets"), "资产负债表"),
    MetricDefinition("other_current_assets", "其他流动资产", ("其他流动资产", "Other Current Assets"), "资产负债表"),
    MetricDefinition("trading_financial_liabilities", "交易性金融负债", ("交易性金融负债", "Trading Financial Liabilities"), "资产负债表"),
    MetricDefinition("construction_in_progress", "在建工程", ("在建工程", "Construction in Progress"), "资产负债表"),
    MetricDefinition("investment_property", "投资性房地产", ("投资性房地产", "Investment Property"), "资产负债表"),
    MetricDefinition("long_term_deferred_expenses", "长期待摊费用", ("长期待摊费用", "Long-term Deferred Expenses"), "资产负债表"),
    MetricDefinition("long_term_equity_investments", "长期股权投资", ("长期股权投资", "Long-term Equity Investments"), "资产负债表"),
    MetricDefinition("other_equity_instrument_investments", "其他权益工具投资", ("其他权益工具投资", "Other Equity Instrument Investments"), "资产负债表"),
    MetricDefinition("fixed_assets", "固定资产", ("固定资产", "固定资产账面价值", "固定资产净值", "Fixed Assets"), "资产负债表"),
    MetricDefinition("right_of_use_assets", "使用权资产", ("使用权资产", "Right-of-use Assets"), "资产负债表"),
    MetricDefinition("intangible_assets", "无形资产", ("无形资产", "Intangible Assets"), "资产负债表"),
    MetricDefinition("deferred_tax_assets", "递延所得税资产", ("递延所得税资产", "Deferred Tax Assets"), "资产负债表"),
    MetricDefinition("other_noncurrent_financial_assets", "其他非流动金融资产", ("其他非流动金融资产", "Other Non-current Financial Assets"), "资产负债表"),
    MetricDefinition("other_noncurrent_assets", "其他非流动资产", ("其他非流动资产", "Other Non-current Assets"), "资产负债表"),
    MetricDefinition("total_assets", "资产总额", ("资产总额", "资产总计", "资产合计", "Total Assets"), "资产负债表"),
    MetricDefinition("short_term_loans", "短期借款", ("短期借款", "Short-term Loans"), "资产负债表"),
    MetricDefinition("notes_payable", "应付票据", ("应付票据", "Notes Payable"), "资产负债表"),
    MetricDefinition("accounts_payable", "应付账款", ("应付账款", "应付帐款", "Accounts Payable"), "资产负债表"),
    MetricDefinition("long_term_payables", "长期应付款", ("长期应付款", "Long-term Payables"), "资产负债表"),
    MetricDefinition("deferred_income", "递延收益", ("递延收益", "Deferred Income"), "资产负债表"),
    MetricDefinition("other_payables", "其他应付款", ("其他应付款", "Other Payables"), "资产负债表"),
    MetricDefinition("dividend_payable", "应付股利/应付利润", ("应付股利", "应付利润", "Dividends Payable"), "资产负债表"),
    # Older accounting reports used "预收账款/预收款项" before contract
    # liabilities became the standard label. Preserve that source term while
    # mapping it to the same comparable customer-advance indicator.
    MetricDefinition("contract_liabilities", "合同负债", ("合同负债", "预收账款", "预收款项", "Contract Liabilities"), "资产负债表"),
    # Some reports list legacy customer advances and contract liabilities as
    # separate rows. In that case retain the legacy row separately so it is
    # not silently folded into the explicit contract-liabilities amount.
    MetricDefinition("advance_receipts", "预收款项", ("预收款项", "预收账款"), "资产负债表"),
    MetricDefinition("current_portion_noncurrent_liabilities", "一年内到期的非流动负债", ("一年内到期的非流动负债", "Current Portion of Non-current Liabilities"), "资产负债表"),
    MetricDefinition("held_for_sale_liabilities", "持有待售负债", ("持有待售负债", "Liabilities Held for Sale"), "资产负债表"),
    MetricDefinition("other_current_liabilities", "其他流动负债", ("其他流动负债", "Other Current Liabilities"), "资产负债表"),
    MetricDefinition("provisions", "预计负债", ("预计负债", "预计负债合计", "Provisions"), "资产负债表"),
    MetricDefinition("employee_compensation_payable", "应付职工薪酬", ("应付职工薪酬", "Employee Compensation Payable"), "资产负债表"),
    MetricDefinition("taxes_payable", "应交税费", ("应交税费", "Taxes Payable"), "资产负债表"),
    MetricDefinition("current_liabilities", "流动负债合计", ("短期负债", "流动负债合计", "流动负债总额", "流动负债及负债合计", "Total Current Liabilities"), "资产负债表"),
    MetricDefinition("long_term_liabilities", "非流动负债合计", ("长期负债", "非流动负债合计", "非流动负债总额", "Total Non-current Liabilities"), "资产负债表"),
    MetricDefinition("long_term_loans", "长期借款", ("长期借款", "Long-term Loans"), "资产负债表"),
    MetricDefinition("lease_liabilities", "租赁负债", ("租赁负债", "Lease Liabilities"), "资产负债表"),
    MetricDefinition("deferred_tax_liabilities", "递延所得税负债", ("递延所得税负债", "Deferred Tax Liabilities"), "资产负债表"),
    MetricDefinition("total_liabilities", "负债总额", ("负债总额", "负债合计", "负债总计", "流动负债及负债合计", "Total Liabilities"), "资产负债表"),
    MetricDefinition("paid_in_capital", "实收资本", ("实收资本", "股本", "Paid-in Capital"), "资产负债表"),
    MetricDefinition("capital_reserve", "资本公积", ("资本公积", "Capital Reserve"), "资产负债表"),
    MetricDefinition("special_reserve", "专项储备", ("专项储备", "Special Reserve"), "资产负债表"),
    MetricDefinition("surplus_reserve", "盈余公积", ("盈余公积", "Surplus Reserve"), "资产负债表"),
    MetricDefinition("undistributed_profit", "未分配利润", ("未分配利润", "Undistributed Profit"), "资产负债表"),
    MetricDefinition("owners_equity", "所有者权益", ("所有者权益", "所有者权益合计", "股东权益合计", "股东权益计", "股东(或所有者)权益合计", "所有者权益(或股东权益)合计", "所有者权益（或股东权益）合计", "Total Owners' Equity"), "资产负债表"),
    MetricDefinition("operating_cash_flow", "经营活动产生的现金流量净额", ("经营活动产生的现金流量净额", "Net Cash Flow from Operating Activities"), "现金流量表"),
    MetricDefinition("investing_cash_flow", "投资活动产生的现金流量净额", ("投资活动产生的现金流量净额", "Net Cash Flow from Investing Activities"), "现金流量表"),
    MetricDefinition("financing_cash_flow", "筹资活动产生的现金流量净额", ("筹资活动产生的现金流量净额", "Net Cash Flow from Financing Activities"), "现金流量表"),
    MetricDefinition("cash_increase", "现金及现金等价物净增加额", ("现金及现金等价物净增加额", "现金净增加额", "Net Increase in Cash"), "现金流量表"),
    MetricDefinition("effect_of_exchange_rate", "汇率变动对现金及现金等价物的影响", ("汇率变动对现金及现金等价物的影响", "汇率变动对现金的影响", "Effect of Exchange Rate Changes on Cash and Cash Equivalents"), "现金流量表"),
    MetricDefinition("cash_beginning", "期初现金及现金等价物余额", ("期初现金及现金等价物余额", "现金及现金等价物期初余额", "期初现金余额", "Beginning Cash and Cash Equivalents"), "现金流量表"),
    MetricDefinition("cash_ending", "期末现金及现金等价物余额", ("期末现金及现金等价物余额", "现金及现金等价物期末余额", "期末现金余额", "Ending Cash and Cash Equivalents"), "现金流量表"),
    MetricDefinition("tax_paid", "支付的各项税费", ("支付的各项税费", "支付的税费", "Taxes Paid"), "现金流量表"),
)

NUMBER_PATTERN = re.compile(r"(?<![\d.])[-（(]?[\d,，]+(?:\.\d+)?[）)]?(?![\d.])")
MIXED_GROUPED_AMOUNT_PATTERN = re.compile(
    r"(?<!\d)-?\d{1,3}(?:[,.]\d{3})+\.\d{2}(?!\d)"
)
SPACED_GROUPED_CENTS_PATTERN = re.compile(
    r"(?<!\d)-?\d{1,3}(?:,\d{3})+\s+\d{2}(?!\d)"
)
YEAR_PATTERN = re.compile(r"(?<!\d)(20\d{2})(?!\d)\s*年?")
REPORT_DATE_PATTERN = re.compile(
    r"(20\d{2})\s*年\s*(?:12\s*月\s*31\s*日|度)"
)

SECTION_RULES: dict[str, tuple[tuple[str, ...], str, int]] = {
    "operating_revenue": (("营业收入和营业成本", "营业收入及营业成本", "营业收入、营业成本", "营业收入/营业成本"), "合计", 0),
    "main_business_revenue": (("营业收入和营业成本", "营业收入及营业成本", "营业收入、营业成本", "营业收入/营业成本"), "主营业务", 0),
    "operating_cost": (("营业收入和营业成本", "营业收入及营业成本", "营业收入、营业成本", "营业收入/营业成本"), "合计", 1),
    "main_business_cost": (("营业收入和营业成本", "营业收入及营业成本", "营业收入、营业成本", "营业收入/营业成本"), "主营业务", 1),
    "other_business_revenue": (("营业收入和营业成本", "营业收入及营业成本", "营业收入、营业成本", "营业收入/营业成本"), "其他业务", 0),
    "other_business_cost": (("营业收入和营业成本", "营业收入及营业成本", "营业收入、营业成本", "营业收入/营业成本"), "其他业务", 1),
    "rd_expenses": (("研发费用",), "合计", 0),
}

# Core financial-statement indicators shown in the workbench. The separate
# other-business rows are useful for reconciling operating totals, but are not
# themselves workbench core indicators.
CORE_FINANCIAL_METRIC_CODES = frozenset(
    {
        "total_assets", "total_liabilities", "owners_equity", "current_assets", "noncurrent_assets", "notes_receivable", "receivables_financing",
        "contract_assets", "notes_payable", "other_payables", "trading_financial_assets",
        "other_current_assets", "centralized_fund_receivables", "long_term_equity_investments", "right_of_use_assets", "investment_property", "dividend_payable",
        "other_equity_instrument_investments", "trading_financial_liabilities",
        "long_term_payables", "deferred_income", "provisions", "special_reserve",
        "deferred_tax_assets", "other_noncurrent_financial_assets", "other_noncurrent_assets",
        "current_portion_noncurrent_liabilities", "held_for_sale_liabilities",
        "current_portion_noncurrent_assets", "effect_of_exchange_rate", "cash_increase",
        "cash_beginning", "cash_ending",
        "interest_expense", "interest_income", "fair_value_change_income",
        "other_current_liabilities", "lease_liabilities", "deferred_tax_liabilities",
        "operating_revenue", "operating_cost", "operating_profit",
        "total_profit", "net_profit", "selling_expenses", "non_operating_revenue",
        "non_operating_expense", "credit_impairment_loss", "asset_impairment_loss",
        "asset_disposal_income", "short_term_investments", "construction_in_progress",
        "long_term_deferred_expenses", "investment_property", "centralized_fund_receivables",
        "administrative_expenses", "rd_expenses",
        "main_business_revenue", "main_business_cost",
        "accounts_payable", "contract_liabilities", "advance_receipts",
    }
)

# These detail rows are not shown as high-level KPIs, but omissions matter for
# a usable audit extraction and must be surfaced when the source statement has
# the row but no amount was extracted.
REQUIRED_COMPLETENESS_METRIC_CODES = CORE_FINANCIAL_METRIC_CODES | {
    "prepayments", "tax_paid",
}


def normalize_number(raw_value: str) -> Decimal:
    cleaned = raw_value.strip()
    is_negative = cleaned.startswith("-") or (cleaned.startswith("(") and cleaned.endswith(")")) or (
        cleaned.startswith("（") and cleaned.endswith("）")
    )
    # OCR occasionally reads a decimal point as a comma, yielding values such
    # as ``6,657,968,47``. Treat the final two-digit group as decimals only
    # when no decimal separator is already present; ordinary thousands groups
    # such as ``6,657,968`` remain integers.
    if "." not in cleaned and "．" not in cleaned:
        comma_normalized = cleaned.replace("，", ",")
        unsigned = comma_normalized.lstrip("-+（(").rstrip("）)")
        groups = unsigned.split(",")
        if len(groups) >= 2 and len(groups[-1]) == 2 and all(group.isdigit() for group in groups):
            cleaned = "".join(groups[:-1]) + "." + groups[-1]
        else:
            cleaned = comma_normalized.replace(",", "")
    else:
        cleaned = cleaned.replace(",", "").replace("，", "").replace("．", ".")
    cleaned = cleaned.strip("+-()（）")
    try:
        number = Decimal(cleaned)
    except InvalidOperation as exc:
        raise ValueError(f"无法将金额转换为数字：{raw_value}") from exc
    return -number if is_negative else number


def table_cell_numbers(cell: str) -> list[str]:
    # A standalone dash is the accounting convention for an explicit zero.
    # Blank cells remain empty, and a minus sign attached to an amount is
    # handled by NUMBER_PATTERN below.
    if re.fullmatch(r"[\s\-−–—－﹣﹘―]+", cell):
        return ["0"]

    # An internal sign after a grouping comma is ambiguous OCR, not two amounts.
    if re.search(r"\d[,，]\s*[-−]\s*\d", cell):
        return []

    def repair_grouping(match: re.Match[str]) -> str:
        value = match.group(0)
        decimal_point = value.rfind(".")
        whole_part = value[:decimal_point]
        if "." not in whole_part:
            return value
        return whole_part.replace(",", "").replace(".", "") + value[decimal_point:]

    def repair_spaced_cents(match: re.Match[str]) -> str:
        return re.sub(r"\s+(\d{2})$", r".\1", match.group(0))

    normalized = MIXED_GROUPED_AMOUNT_PATTERN.sub(repair_grouping, cell)
    normalized = SPACED_GROUPED_CENTS_PATTERN.sub(repair_spaced_cents, normalized)
    return NUMBER_PATTERN.findall(normalized)


def detect_unit(text: str) -> str:
    if "单位：万元" in text or "单位:万元" in text:
        return "万元"
    if "单位：千元" in text or "单位:千元" in text:
        return "千元"
    return "元"


def detect_period(text: str) -> str | None:
    match = REPORT_DATE_PATTERN.search(text[:3000])
    if match is None:
        match = YEAR_PATTERN.search(text[:1000])
    return match.group(1) if match is not None and plausible_report_year(match.group(1)) else None


def plausible_report_year(year: str) -> bool:
    return year.isdigit() and 2000 <= int(year) <= datetime.now().year + 1


def plausible_metric_period(period: str) -> bool:
    """Accept a report year, an explicit month range, or a statement date."""
    if plausible_report_year(period):
        return True
    date_match = re.fullmatch(r"(20\d{2})年(\d{1,2})月(\d{1,2})日", period)
    if date_match is not None and plausible_report_year(date_match.group(1)):
        try:
            datetime.strptime(period, "%Y年%m月%d日")
            return True
        except ValueError:
            return False
    match = re.fullmatch(r"(20\d{2})年(\d{1,2})[-—至](\d{1,2})月", period)
    if match is None or not plausible_report_year(match.group(1)):
        return False
    start_month, end_month = int(match.group(2)), int(match.group(3))
    return 1 <= start_month <= end_month <= 12


def filename_period(filename: str) -> str | None:
    range_match = re.search(
        r"(?<!\d)(20\d{2})\s*[-—–至~～]\s*(20\d{2})(?:年|年度)?",
        filename,
    )
    if range_match is not None:
        start, end = range_match.groups()
        if plausible_report_year(start) and plausible_report_year(end) and int(start) <= int(end):
            return end
    match = re.search(r"(20\d{2})\s*年(?:度)?", filename)
    if match is not None:
        return match.group(1) if plausible_report_year(match.group(1)) else None
    leading_match = re.match(r"^\s*(20\d{2})(?!\d)", filename)
    if leading_match is not None and plausible_report_year(leading_match.group(1)):
        return leading_match.group(1)
    contextual_match = re.search(
        r"(?<!\d)(20\d{2})(?!\d)[-_ ]*(?=(?:年度)?(?:financial|audit|财务|审计))",
        filename,
        flags=re.IGNORECASE,
    )
    if contextual_match is not None:
        return contextual_match.group(1) if plausible_report_year(contextual_match.group(1)) else None
    short_match = re.search(r"(?<!\d)(2\d)\s*年(?:度)?", filename)
    if short_match is None:
        return None
    year = f"20{short_match.group(1)}"
    return year if plausible_report_year(year) else None


def statement_page_period(page: ParsedPage) -> str | None:
    if is_table_of_contents_page(page):
        return None
    text = searchable_line(page.text[:3000])
    statement_titles = (
        "资产负债表",
        "利润表",
        "现金流量表",
    )
    if "<table" not in page.text.lower() or not any(title in text for title in statement_titles):
        return None
    patterns = (
        r"(?:母公司|合并)?资产负债表(20\d{2})年12月31日",
        r"(?:母公司|合并)?利润表(20\d{2})年度",
        r"(?:母公司|合并)?现金流量表(20\d{2})年度",
        r"(20\d{2})年度(?:母公司|合并)?利润表",
        r"(20\d{2})年度(?:母公司|合并)?现金流量表",
    )
    for pattern in patterns:
        match = re.search(pattern, text)
        if match is not None and plausible_report_year(match.group(1)):
            return match.group(1)
    return None


def audit_opinion_periods(pages: list[ParsedPage]) -> set[str]:
    periods: set[str] = set()
    patterns = (
        r"(?:审计了|包括)[^。；]{0,160}?(20\d{2})年12月31日[^。；]{0,80}?资产负债表",
        r"公允反映[^。；]{0,120}?(20\d{2})年12月31日[^。；]{0,80}?财务状况",
    )
    for page in pages[:6]:
        text = searchable_line(page.text[:6000])
        for pattern in patterns:
            periods.update(year for year in re.findall(pattern, text) if plausible_report_year(year))
    return periods


def determine_report_period(filename: str, pages: list[ParsedPage]) -> str | None:
    partial_years = {
        year for page in pages
        if any(title in searchable_line(page.text[:3000]) for title in ("利润表", "现金流量表"))
        for year in re.findall(
            r"<td[^>]*>(20\d{2})年\d{1,2}[-—至]\d{1,2}月</td>",
            searchable_line(page.text[:3000]),
        )
    }
    statement_periods = {
        period for page in pages if (period := statement_page_period(page)) is not None
    }
    opinion_periods = audit_opinion_periods(pages)
    if len(opinion_periods) > 1:
        raise ValueError(
            f"审计意见出现多个报告年度：{filename}；"
            f"识别到的年度：{'、'.join(sorted(opinion_periods))}"
        )
    statement_period = next(iter(statement_periods), None)
    opinion_period = next(iter(opinion_periods), None)
    name_period = filename_period(filename)
    if len(statement_periods) > 1:
        if opinion_period is not None and opinion_period in statement_periods:
            return opinion_period
        if name_period is not None and name_period in statement_periods:
            return name_period
        raise ValueError(
            f"主财务报表出现多个报告年度：{filename}；"
            f"识别到的年度：{'、'.join(sorted(statement_periods))}"
        )
    if (
        statement_period is not None
        and opinion_period is not None
        and statement_period != opinion_period
    ):
        if name_period == opinion_period:
            return opinion_period
        raise ValueError(
            f"报告年度证据相互冲突：{filename}；"
            f"主财务报表为{statement_period}年，审计意见为{opinion_period}年"
        )
    selected_period = statement_period or opinion_period or name_period
    if partial_years and (
        selected_period is None
        or any(int(year) != int(selected_period) - 1 for year in partial_years)
    ):
        raise ValueError(
            f"报告包含非全年期间及多个年度：{filename}；"
            "当前年度财务档案不能安全保存月度区间数据"
        )
    return selected_period


def compact_line(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def searchable_line(text: str) -> str:
    return re.sub(r"(?<!\d)\s+|\s+(?!\d)", "", text).lower()


def document_search_text(pages: list[ParsedPage]) -> str:
    return "\n".join(searchable_line(page.text) for page in pages)


def has_core_statement_text(pages: list[ParsedPage]) -> bool:
    text = document_search_text(pages)
    balance_sheet = (
        any(label in text for label in ("资产总计", "资产合计", "资产总额", "totalassets"))
        and any(
            label in text
            for label in (
                "负债合计", "负债总计", "所有者权益合计",
                "totalliabilities", "totalowners'equity",
            )
        )
    )
    income_statement = (
        any(label in text for label in ("营业收入", "主营业务收入", "operatingrevenue"))
        and any(
            label in text
            for label in ("营业利润", "利润总额", "净利润", "operatingprofit", "totalprofit", "netprofit")
        )
    )
    return balance_sheet and income_statement


def is_table_of_contents_page(page: ParsedPage) -> bool:
    text = searchable_line(page.text)
    if "目录" not in text:
        return False
    statement_labels = (
        "审计报告",
        "财务报表",
        "资产负债表",
        "利润表",
        "现金流量表",
        "所有者权益变动表",
        "财务报表附注",
    )
    return sum(label in text for label in statement_labels) >= 3


def validate_metric_completeness(metrics: list[ExtractedMetric]) -> list[str]:
    codes = {metric.definition.code for metric in metrics}
    errors: list[str] = []
    if "total_assets" not in codes:
        errors.append("缺少资产总额")
    if "total_liabilities" not in codes:
        errors.append("缺少负债总额")
    if "owners_equity" not in codes:
        errors.append("缺少所有者权益")
    if "operating_revenue" not in codes:
        errors.append("缺少营业收入")
    if "net_profit" not in codes:
        errors.append("缺少净利润")
    return errors


def is_parent_statement_page(page: ParsedPage) -> bool:
    text = searchable_line(page.text)
    parent_titles = ("母公司资产负债表", "母公司利润表", "母公司现金流量表")
    consolidated_titles = ("合并资产负债表", "合并利润表", "合并现金流量表")
    parent_title_count = sum(title in text for title in parent_titles)
    all_title_count = parent_title_count + sum(title in text for title in consolidated_titles)
    return parent_title_count == 1 and all_title_count == 1 and len(NUMBER_PATTERN.findall(text)) >= 3


def is_company_statement_page(page: ParsedPage) -> bool:
    text = searchable_line(page.text)
    consolidated_titles = (
        "合并及公司资产负债表",
        "合并及公司利润表",
        "合并及公司现金流量表",
        "合并资产负债表",
        "合并利润表",
        "合并现金流量表",
        "并资产负债表",
        "并利润表",
        "并现金流量表",
    )
    if "<table" not in page.text.lower() or any(title in text for title in consolidated_titles):
        return False
    company_titles = (
        "公司资产负债表",
        "公司利润表",
        "公司现金流量表",
        "司资产负债表",
        "司利润表",
        "司现金流量表",
    )
    has_company_title = any(title in text for title in company_titles)
    has_truncated_balance_title = "产负债表" in text and any(
        marker in text for marker in ("流动资产", "非流动资产", "资产总计")
    )
    return (has_company_title or has_truncated_balance_title) and len(NUMBER_PATTERN.findall(text)) >= 3


def has_combined_statement_content(page: ParsedPage) -> bool:
    text = searchable_line(page.text)
    fingerprints = (
        ("资产总计", ("负债合计", "所有者权益合计", "负债和所有者权益总计")),
        ("营业收入", ("净利润",)),
        ("经营活动产生的现金流量", ("现金及现金等价物", "现金净增加额")),
    )
    return any(
        first_marker in text and any(marker in text for marker in alternatives)
        for first_marker, alternatives in fingerprints
    ) and len(NUMBER_PATTERN.findall(text)) >= 3


def is_parent_primary_statement_content(page: ParsedPage) -> bool:
    text = searchable_line(page.text)
    consolidated_titles = (
        "合并资产负债表",
        "合并利润表",
        "合并现金流量表",
        "并资产负债表",
        "并利润表",
        "并现金流量表",
    )
    if any(title in text for title in consolidated_titles):
        return False
    fingerprints = (
        (("负债和所有者权益", "负债及所有者权益", "负债和股东权益", "负债和股东(或所有者)权益"), ("流动负债",)),
        (("营业收入",), ("利润总额",), ("净利润",)),
        (("经营活动产生的现金流量",), ("现金及现金等价物", "现金净增加额")),
    )
    matches_statement = any(
        all(any(marker in text for marker in alternatives) for alternatives in fingerprint)
        for fingerprint in fingerprints
    )
    return matches_statement and len(NUMBER_PATTERN.findall(text)) >= 3


def is_asset_primary_statement_content(page: ParsedPage) -> bool:
    text = searchable_line(page.text)
    consolidated_titles = (
        "合并资产负债表",
        "并资产负债表",
    )
    if (
        "<table" not in page.text.lower()
        or any(title in text for title in consolidated_titles)
    ):
        return False
    markers = ("流动资产合计", "非流动资产合计", "资产总计")
    return all(marker in text for marker in markers) and len(NUMBER_PATTERN.findall(text)) >= 3


def is_liability_primary_statement_content(page: ParsedPage) -> bool:
    text = searchable_line(page.text)
    return (
        any(marker in text for marker in ("负债和所有者权益", "负债及所有者权益", "负债和股东权益", "负债和股东(或所有者)权益"))
        and "流动负债" in text
        and is_parent_primary_statement_content(page)
    )


def general_note_start_index(pages: list[ParsedPage]) -> int | None:
    for index, page in enumerate(pages):
        text = searchable_line(page.text)
        if "财务报表附注" in text and "公司基本情况" in text:
            return index
    return None


def parent_note_start_index(pages: list[ParsedPage]) -> int | None:
    for index, page in enumerate(pages):
        text = searchable_line(page.text)
        if "母公司财务报表附注" in text and "公司基本情况" in text:
            return index
    titles = (
        "母公司财务报表主要项目注释",
        "母公司财务报表项目注释",
        "公司财务报表主要项目注释",
        "公司财务报表项目注释",
    )
    matches = [
        index
        for index, page in enumerate(pages)
        if any(title in searchable_line(page.text) for title in titles)
    ]
    return matches[-1] if len(matches) > 0 else None


def select_parent_company_pages(pages: list[ParsedPage]) -> list[ParsedPage]:
    full_text = document_search_text(pages)
    parent_titles = ("母公司资产负债表", "母公司利润表", "母公司现金流量表")
    combined_markers = (
        "合并及母公司",
        "合并及公司",
        "合并资产负债表和母公司资产负债表",
        "合并利润表和母公司利润表",
        "合并现金流量表和母公司现金流量表",
    )
    has_parent_scope = any(title in full_text for title in parent_titles)
    has_combined_scope = any(marker in full_text for marker in combined_markers)
    has_consolidated_statements = any(
        title in full_text
        for title in ("合并资产负债表", "合并利润表", "合并现金流量表")
    )
    if not has_parent_scope and not has_combined_scope and not has_consolidated_statements:
        return pages

    notes_start = general_note_start_index(pages)
    primary_region = pages if notes_start is None else pages[:notes_start]
    combined_statement_titles = (
        "合并及公司资产负债表",
        "合并及公司利润表",
        "合并及公司现金流量表",
        "合并及母公司资产负债表",
        "合并及母公司利润表",
        "合并及母公司现金流量表",
    )
    combined_pages = [
        page
        for page in primary_region
        if "<table" in page.text.lower()
        and any(title in searchable_line(page.text) for title in combined_statement_titles)
        and has_combined_statement_content(page)
    ]
    if len(combined_pages) > 0:
        note_start = parent_note_start_index(pages)
        selected_page_numbers = {page.page_number for page in combined_pages}
        if note_start is not None:
            selected_page_numbers.update(page.page_number for page in pages[note_start:])
        return [page for page in pages if page.page_number in selected_page_numbers]
    explicit_parent_pages = [
        page
        for page in primary_region
        if is_parent_statement_page(page)
        or is_company_statement_page(page)
    ]
    content_parent_pages = [
        page for page in primary_region if is_parent_primary_statement_content(page)
    ]
    parent_pages = list(explicit_parent_pages)
    if len(explicit_parent_pages) > 0:
        first_explicit_page = min(page.page_number for page in explicit_parent_pages)
        # In scanned reports the title can disappear while the table header survives.
        # Keep the note column used by the parent balance sheet and exclude later
        # income/cash tables that still use the consolidated note column.
        def note_header(page: ParsedPage) -> str | None:
            match = re.search(r"<td[^>]*>附注([^<]*)</td>", page.text)
            return match.group(1).strip() if match is not None else None

        parent_note_headers = {
            header for page in explicit_parent_pages
            if (header := note_header(page))
        }
        consolidated_note_headers = {
            header for page in primary_region
            if page.page_number < first_explicit_page
            and any(title in searchable_line(page.text) for title in (
                "合并资产负债表", "合并利润表", "合并现金流量表"
            ))
            if (header := note_header(page))
        } - parent_note_headers
        content_parent_pages = [
            page for page in content_parent_pages
            if not (
                page.page_number >= first_explicit_page
                and note_header(page) in consolidated_note_headers
            )
        ]
        primary_page_end = max(page.page_number for page in explicit_parent_pages) + 6
        for fingerprints in (
            (("营业收入",), ("利润总额",), ("净利润",)),
            (("经营活动产生的现金流量",),
             ("现金及现金等价物", "现金净增加额")),
        ):
            candidates = [
                page for page in content_parent_pages
                if first_explicit_page <= page.page_number <= primary_page_end
                and all(
                    any(marker in searchable_line(page.text) for marker in alternatives)
                    for alternatives in fingerprints
                )
            ]
            if len(candidates) > 1:
                raise ParentCompanyPagesUnavailableError(
                    "报表标题缺失，无法区分合并与母公司结果页"
                )
        parent_pages.extend(
            page for page in content_parent_pages if page.page_number >= first_explicit_page
        )
        first_explicit_result_page = min(
            (
                page.page_number
                for page in explicit_parent_pages
                if any(
                    title in searchable_line(page.text)
                    for title in ("利润表", "现金流量表")
                )
            ),
            default=None,
        )
        if first_explicit_result_page is not None:
            earlier_liability_pages = [
                page
                for page in content_parent_pages
                if page.page_number < first_explicit_result_page
                and is_liability_primary_statement_content(page)
            ]
            if len(earlier_liability_pages) > 0:
                liability_page = max(earlier_liability_pages, key=lambda page: page.page_number)
                parent_pages.append(liability_page)
                earlier_asset_pages = [
                    page
                    for page in primary_region
                    if page.page_number < liability_page.page_number
                    and is_asset_primary_statement_content(page)
                ]
                if len(earlier_asset_pages) > 0:
                    parent_pages.append(
                        max(earlier_asset_pages, key=lambda page: page.page_number)
                    )
    else:
        parent_pages.extend(content_parent_pages)
    if len(parent_pages) > 0:
        note_start = parent_note_start_index(pages)
        selected_page_numbers = {page.page_number for page in parent_pages}
        if note_start is not None:
            selected_page_numbers.update(page.page_number for page in pages[note_start:])
        return [page for page in pages if page.page_number in selected_page_numbers]
    if has_combined_scope or has_consolidated_statements:
        raise ParentCompanyPagesUnavailableError(
            "报告包含合并报表，但当前文字层没有可靠读到公司单体主表页面"
        )
    return pages


def find_metric_in_section(
    definition: MetricDefinition, page: ParsedPage, lines: list[str]
) -> ExtractedMetric | None:
    rule = SECTION_RULES.get(definition.code)
    if rule is None:
        return None
    headings, target_row, number_index = rule
    searchable_headings = tuple(searchable_line(heading) for heading in headings)
    for heading_index, line in enumerate(lines):
        normalized_line = searchable_line(line)
        if not any(heading in normalized_line for heading in searchable_headings):
            continue
        for candidate_line in lines[heading_index + 1 : heading_index + 16]:
            candidate = searchable_line(candidate_line)
            target_position = candidate.find(searchable_line(target_row))
            if target_position < 0:
                continue
            numbers = NUMBER_PATTERN.findall(candidate[target_position + len(searchable_line(target_row)) :])
            if len(numbers) <= number_index:
                continue
            raw_value = numbers[number_index]
            try:
                normalized = normalize_number(raw_value)
            except ValueError:
                continue
            return ExtractedMetric(
                definition=definition,
                value_text=raw_value,
                normalized_value=normalized,
                unit=detect_unit(page.text),
                period=detect_period(page.text),
                source_page=page.page_number,
                source_quote=candidate_line[:500],
                confidence=Decimal("0.90"),
            )
    return None


def metric_for_period(
    definition: MetricDefinition,
    raw_value: str,
    unit: str,
    period: str,
    page_number: int,
    source_quote: str,
    confidence: Decimal,
) -> ExtractedMetric | None:
    try:
        normalized = normalize_number(raw_value)
    except ValueError:
        return None
    return ExtractedMetric(
        definition=definition,
        value_text=raw_value,
        normalized_value=normalized,
        unit=unit,
        period=period,
        source_page=page_number,
        source_quote=source_quote[:500],
        confidence=confidence,
    )


def report_periods(report_period: str) -> tuple[str, str]:
    try:
        current_year = int(report_period)
    except ValueError as exc:
        raise ValueError(f"报告年度必须是四位数字：{report_period}") from exc
    return str(current_year), str(current_year - 1)


def partial_comparative_period(page: ParsedPage, previous_period: str) -> str | None:
    """Return a distinct year-range label for a partial comparative column."""
    match = re.search(
        rf"(?<!\d){previous_period}\s*年\s*(\d{{1,2}})\s*[-—至－~～]\s*(\d{{1,2}})\s*月",
        page.text[:5000],
    )
    if match is None:
        return None
    start_month, end_month = (int(value) for value in match.groups())
    if not (1 <= start_month <= end_month <= 12):
        return None
    return f"{previous_period}年{start_month}-{end_month}月"


def html_table_rows(text: str) -> list[list[str]]:
    rows: list[list[str]] = []
    for row_html in re.findall(r"<tr[^>]*>(.*?)</tr>", text, flags=re.IGNORECASE | re.DOTALL):
        cells = [
            compact_line(re.sub(r"<[^>]+>", "", cell_html))
            for cell_html in re.findall(
                r"<t[dh][^>]*>(.*?)</t[dh]>", row_html, flags=re.IGNORECASE | re.DOTALL
            )
        ]
        if len(cells) > 0:
            rows.append(cells)
    return rows


def period_column_role(header: str, current_period: str, previous_period: str) -> str | None:
    label = searchable_line(header)
    if re.search(rf"(?<!\d){previous_period}(?:年|年度)?(?!\d)", label):
        return "previous"
    if re.search(rf"(?<!\d){current_period}(?:年|年度)?(?!\d)", label):
        return "current"
    if label.startswith(("上年", "上期", "去年", "期初", "年初")):
        return "previous"
    if label.startswith(("本年", "本期", "当期", "期末", "年末", "年累计数")):
        return "current"
    return None


def expanded_table_row(row_html: str) -> list[str]:
    cells: list[str] = []
    for match in re.finditer(
        r"<t[dh]([^>]*)>(.*?)</t[dh]>", row_html, flags=re.IGNORECASE | re.DOTALL
    ):
        span_match = re.search(r'colspan\s*=\s*["\']?(\d+)', match.group(1), re.IGNORECASE)
        span = min(int(span_match.group(1)), 20) if span_match is not None else 1
        cell = compact_line(re.sub(r"<[^>]+>", "", match.group(2)))
        cells.extend([cell] * span)
    return cells


def table_period_columns(
    row_htmls: list[str], row_index: int, current_period: str, previous_period: str
) -> dict[int, str]:
    roles: dict[int, str] = {}
    for row_html in row_htmls[: min(row_index, 3)]:
        cells = expanded_table_row(row_html)
        if len({cell for cell in cells if cell}) == 1 and len(cells) > 1:
            continue
        if sum(
            bool(table_cell_numbers(cell))
            and period_column_role(cell, current_period, previous_period) is None
            for cell in cells
        ) >= 2:
            continue
        for column, cell in enumerate(cells):
            role = period_column_role(cell, current_period, previous_period)
            if role is None:
                continue
            if column in roles and roles[column] != role:
                raise ValueError("同一表格的年度列头相互冲突，无法安全归属年度")
            roles[column] = role
    return roles


def metric_amount_columns(
    row_html: str, definition: MetricDefinition | None, values: list[str],
    roles: dict[int, str] | None = None,
) -> tuple[int, int] | None:
    cells = expanded_table_row(row_html)
    aliases = (
        {searchable_line(alias) for alias in definition.aliases}
        if definition is not None else set()
    )
    label_indices = [
        index for index, cell in enumerate(cells)
        if aliases and any(
            canonical_table_label(cell) == alias
            or canonical_table_label(cell).startswith(alias + "（")
            or canonical_table_label(cell).startswith(alias + "(")
            for alias in aliases
        )
    ]
    if definition is not None and definition.code == "total_assets" and not label_indices:
        label_indices = [
            index for index, cell in enumerate(cells)
            if canonical_table_label(cell) == "合计"
        ][:1]
    if not label_indices and definition is None:
        label_indices = [0]
    candidates: list[tuple[int, int]] = []
    for label_index in label_indices:
        end = next(
            (
                index for index in range(label_index + 1, len(cells))
                if cells[index] != cells[label_index]
                and cells[index].strip() != ""
                and not table_cell_numbers(cells[index])
                and cells[index].strip() not in ("-", "—", "－")
                and not is_explicit_note_reference(cells[index])
            ),
            len(cells),
        )
        for first_column in range(label_index + 1, end - 1):
            columns = (first_column, first_column + 1)
            amounts = [
                table_cell_numbers(cells[column])[0] if table_cell_numbers(cells[column]) else ""
                for column in columns
            ]
            if all(
                actual == expected or (actual == "" and expected in ("0", "0.00"))
                for actual, expected in zip(amounts, values, strict=True)
            ):
                candidates.append(columns)
    if not candidates:
        return None
    return max(candidates, key=lambda pair: sum(column in (roles or {}) for column in pair))


def order_values_by_table_header(
    page_text: str,
    source_quote: str,
    values: list[str],
    current_period: str,
    previous_period: str,
    definition: MetricDefinition | None = None,
) -> list[str]:
    if len(values) != 2:
        return values
    orders: set[tuple[str, str]] = set()
    matched_table = False
    for table_html in re.findall(
        r"<table[^>]*>.*?</table>", page_text, flags=re.IGNORECASE | re.DOTALL
    ):
        row_htmls = re.findall(r"<tr[^>]*>(.*?)</tr>", table_html, flags=re.IGNORECASE | re.DOTALL)
        rows = html_table_rows(table_html)
        for row_index, row in enumerate(rows):
            if " | ".join(row) != source_quote:
                continue
            matched_table = True
            roles = table_period_columns(row_htmls, row_index, current_period, previous_period)
            columns = metric_amount_columns(row_htmls[row_index], definition, values, roles)
            if columns is None:
                raise ValueError("金额列与原表格结构无法对齐，不能安全归属年度")
            pair = [roles.get(column) for column in columns]
            if pair == [None, None] and len(roles) == 2:
                ordered_roles = [role for _, role in sorted(roles.items())]
                numeric_cells = [
                    cell for cell in expanded_table_row(row_htmls[row_index])
                    if table_cell_numbers(cell)
                ]
                if len(numeric_cells) == 2 and set(ordered_roles) == {"current", "previous"}:
                    pair = ordered_roles
            if pair == [None, None] or pair[0] == pair[1]:
                raise ValueError("原表格年度列头缺失或冲突，不能安全归属年度")
            if pair[0] is None:
                pair[0] = "previous" if pair[1] == "current" else "current"
            if pair[1] is None:
                pair[1] = "previous" if pair[0] == "current" else "current"
            orders.add((pair[0], pair[1]))
    if len(orders) > 1:
        raise ValueError("同页相同金额行的年度列顺序相互冲突，无法安全归属年度")
    if matched_table and not orders:
        raise ValueError("原表格年度列位无法确认，不能安全归属年度")
    return list(reversed(values)) if orders == {("previous", "current")} else values


def canonical_table_label(text: str) -> str:
    label = searchable_line(text)
    # Keep numerals that belong to labels such as \u4e00\u5e74\u5185\u5230\u671f\u7684\u975e\u6d41\u52a8\u8d1f\u503a.
    # Strip a leading numeral only when punctuation marks a numbered list item.
    label = re.sub(r"^[\uff08(]?[\u4e00\u4e8c\u4e09\u56db\u4e94\u516d\u4e03\u516b\u4e5d\u5341\u767e0-9]+[\uff09)\u3001.\uff0e]", "", label)
    label = re.sub(r"^[、.．]+", "", label)
    label = re.sub(r"^(加|减|其中)[:：]", "", label)
    # OCR can repeat this word at a merged cell boundary. Keep the source quote intact.
    label = label.replace("所有者权益权益合计", "所有者权益合计")
    return re.sub(r"[:：]$", "", label)


def is_explicit_note_reference(text: str) -> bool:
    normalized = searchable_line(text)
    if "," in normalized or "，" in normalized:
        parts = re.split(r"[,，]", normalized)
        return all(is_explicit_note_reference(part) for part in parts)
    normalized = re.sub(r"[（(][a-z][）)]$", "", normalized)
    patterns = (
        r"(?:附注|注释)\d{1,3}(?:[.．]\d{1,3})?",
        r"[（(][一二三四五六七八九十百]+[）)]",
        r"\d{1,3}[.．]\d{1,3}",
        r"(?:附注)?[一二三四五六七八九十百]+[、.．]\d{1,3}",
        r"(?:附注)?[一二三四五六七八九十百]+[、.．]?[（(][一二三四五六七八九十百0-9、.．]+[）)](?:[、.．]?\d{1,3})?",
        r"(?:附注)?[（(][一二三四五六七八九十百]+[）)]\d{1,3}",
        r"\d{1,3}[（(]\d{1,3}[）)]",
        r"[（(]\d{1,3}[）)]\d{0,3}",
        r"\d{1,3}[、．]\d{1,3}",
    )
    return any(re.fullmatch(pattern, normalized) is not None for pattern in patterns)


def validate_metric_source_alignment(metrics: list[ExtractedMetric]) -> list[str]:
    errors: list[str] = []
    for metric in metrics:
        if abs(metric.normalized_value) > Decimal("100"):
            continue
        if (
            metric.normalized_value != 0
            and re.fullmatch(r"-?\d{1,3}", metric.value_text) is not None
            and "<table" in metric.source_quote.lower()
            and len(metric.source_quote) >= 480
        ):
            errors.append(
                f"{metric.period or '未知年度'}年{metric.definition.label}来源范围过大且金额异常偏小"
            )
            continue
        if " | " not in metric.source_quote:
            continue
        if any(
            match.group(0).startswith(metric.value_text)
            and match.group(0) != metric.value_text
            for match in MIXED_GROUPED_AMOUNT_PATTERN.finditer(metric.source_quote)
        ):
            errors.append(
                f"{metric.period or '未知年度'}年{metric.definition.label}取到了残缺金额"
            )
            continue
        cells = [cell.strip() for cell in metric.source_quote.split(" | ")]
        aliases = {searchable_line(alias) for alias in metric.definition.aliases}
        label_index = next(
            (index for index, cell in enumerate(cells) if canonical_table_label(cell) in aliases),
            None,
        )
        if label_index is None:
            continue
        value_cells = cells[label_index + 1 :]
        if len(value_cells) < 2:
            continue
        first_cell = value_cells[0]
        first_values = [normalize_number(value) for value in NUMBER_PATTERN.findall(first_cell)]
        if metric.normalized_value not in first_values:
            continue
        later_values = [table_cell_numbers(cell) for cell in value_cells[1:3]]
        decimal_only = re.fullmatch(r"\d{1,3}[.．]\d{1,3}", first_cell) is not None
        is_note = (
            is_explicit_note_reference(first_cell)
            and any(later_values)
            and (
                not decimal_only
                or (len(later_values) == 2 and all(len(values) == 1 for values in later_values))
            )
        )
        is_row_number = (
            len(value_cells) >= 2
            and re.fullmatch(r"\d{1,3}", first_cell) is not None
            and metric.normalized_value != 0
            and any(
                abs(normalize_number(value)) >= Decimal("1000")
                for values in later_values
                for value in values
            )
        )
        if is_note or is_row_number:
            errors.append(
                f"{metric.period or '未知年度'}年{metric.definition.label}取到了附注或行号"
            )
    return list(dict.fromkeys(errors))


def values_from_named_table_row(
    definition: MetricDefinition, page: ParsedPage
) -> tuple[list[str], str] | None:
    searchable_aliases = tuple(searchable_line(alias) for alias in definition.aliases)
    matched_quote: str | None = None
    rows = html_table_rows(page.text)
    has_row_number_column = any(
        "行次" in searchable_line(cell) for row in rows[:3] for cell in row
    ) or sum(
        len(row) >= 3
        and re.fullmatch(r"\d{1,3}", row[1].strip()) is not None
        and len(NUMBER_PATTERN.findall(row[2])) == 1
        for row in rows
    ) >= 3
    for cells in rows:
        if len(cells) < 2:
            continue
        label_index: int | None = None
        for index, cell in enumerate(cells):
            label = canonical_table_label(cell)
            if any(
                label == alias
                or label.startswith(alias + "（")
                or label.startswith(alias + "(")
                for alias in searchable_aliases
            ):
                label_index = index
                break
        if label_index is None:
            continue
        # Notes can contain counterparty/subsidiary detail rows such as
        # ``subsidiary name | accounts receivable | amount``. Those rows are
        # not the reporting entity's balance-sheet total and must never be a
        # fallback source for the corresponding core metric.
        if label_index > 0 and any(
            re.search(r"(?:有限公司|有限责任公司|股份有限公司|集团公司|科技公司|实业公司)$", searchable_line(cell))
            for cell in cells[:label_index]
        ):
            continue
        matched_quote = " | ".join(cells)
        original_value_cells = cells[label_index + 1 :]
        value_cells = original_value_cells
        while len(value_cells) >= 3 and value_cells[0].strip() == "":
            value_cells = value_cells[1:]
        if len(value_cells) >= 3 and is_explicit_note_reference(value_cells[0]):
            value_cells = value_cells[1:]
        while len(value_cells) >= 3 and value_cells[0].strip() == "":
            value_cells = value_cells[1:]
        if (len(value_cells) >= 3 or has_row_number_column) and len(value_cells) >= 1 and re.fullmatch(r"\d{1,3}", value_cells[0].strip()):
            value_cells = value_cells[1:]
        while len(value_cells) >= 3 and value_cells[0].strip() == "":
            value_cells = value_cells[1:]
        if any(
            cell.strip() not in ("", "-", "—") and not table_cell_numbers(cell)
            for cell in value_cells[:2]
        ):
            # A label from the opposite half of a paired table is not an amount.
            continue
        # The opposite half can start a numbered supplementary heading.
        for column, cell in enumerate(value_cells):
            if re.match(r"^\s*\d+[、．]\s*[\u4e00-\u9fff]", cell):
                value_cells = value_cells[:column]
                break
        two_columns = [table_cell_numbers(cell) for cell in value_cells[:2]]
        if len(two_columns) == 2 and all(len(numbers) <= 1 for numbers in two_columns):
            values = [numbers[0] if numbers else "" for numbers in two_columns]
            if any(values):
                return values, matched_quote
        values = [number for cell in value_cells[:2] for number in table_cell_numbers(cell)]
        if len(values) > 0:
            return values, matched_quote
    return ([], matched_quote) if matched_quote is not None else None


def values_from_paired_balance_total_row(
    definition: MetricDefinition, page: ParsedPage
) -> tuple[list[str], str] | None:
    if definition.code != "total_assets":
        return None
    for cells in html_table_rows(page.text):
        normalized_cells = [canonical_table_label(cell) for cell in cells]
        right_total_index = next(
            (
                index
                for index, label in enumerate(normalized_cells)
                if "负债和所有者权益" in label and label.endswith("总计")
            ),
            None,
        )
        if right_total_index is None:
            continue
        left_total_index = next(
            (
                index
                for index, label in enumerate(normalized_cells[:right_total_index])
                if label == "合计"
            ),
            None,
        )
        if left_total_index is None:
            continue
        value_cells = cells[left_total_index + 1 : right_total_index]
        if len(value_cells) >= 3 and re.fullmatch(r"\d{1,3}", value_cells[0].strip()):
            value_cells = value_cells[1:]
        values = [number for cell in value_cells[:2] for number in table_cell_numbers(cell)]
        if len(values) == 2:
            return values, " | ".join(cells)
        return [], " | ".join(cells)
    return None


def values_from_combined_company_table(
    definition: MetricDefinition, page: ParsedPage,
    current_period: str, previous_period: str,
) -> tuple[list[str], str] | None:
    page_text = searchable_line(page.text)
    if "合并及公司" not in page_text and "合并及母公司" not in page_text:
        return None
    rows = html_table_rows(page.text)
    has_company_columns = any(
        [searchable_line(cell) for cell in row[-4:]]
        in (["合并", "公司", "合并", "公司"], ["合并", "母公司", "合并", "母公司"])
        for row in rows
        if len(row) >= 4
    )
    if not has_company_columns:
        return None
    searchable_aliases = tuple(searchable_line(alias) for alias in definition.aliases)
    matched_quote: str | None = None
    for row_index, cells in enumerate(rows):
        if len(cells) < 5:
            continue
        label = canonical_table_label(cells[0])
        if not any(
            label == alias
            or label.startswith(alias + "（")
            or label.startswith(alias + "(")
            for alias in searchable_aliases
        ):
            continue
        matched_quote = " | ".join(cells)
        value_cells = cells[-4:]
        company_cells = (value_cells[1], value_cells[3])
        company_values = [table_cell_numbers(cell) for cell in company_cells]
        if any(len(values) != 1 for values in company_values):
            return [], matched_quote
        header_pairs = [
            [period_column_role(cell, current_period, previous_period) for cell in row[-4:]]
            for row in rows[:row_index] if len(row) >= 6
        ]
        period_roles = next((
            [pair[0], pair[2]] for pair in header_pairs
            if pair[0] == pair[1] and pair[2] == pair[3]
            and {pair[0], pair[2]} == {"current", "previous"}
        ), None)
        if period_roles is None:
            raise ValueError("合并及公司表年度列头缺失，不能安全归属年度")
        return [
            company_values[period_roles.index("current")][0],
            company_values[period_roles.index("previous")][0],
        ], matched_quote
    return ([], matched_quote) if matched_quote is not None else None


def values_from_business_category_columns(
    definition: MetricDefinition,
    page: ParsedPage,
    current_period: str,
    previous_period: str,
) -> tuple[list[str], str] | None:
    """Read notes that place business categories in columns and revenue/cost in rows."""
    category_index = {
        "main_business_revenue": 0,
        "other_business_revenue": 1,
        "operating_revenue": 2,
        "main_business_cost": 0,
        "other_business_cost": 1,
        "operating_cost": 2,
    }.get(definition.code)
    if category_index is None:
        return None

    category_headers = {
        "主营业务": "main",
        "其他业务": "other",
        "合计": "total",
    }
    expected_categories = ["main", "other", "total", "main", "other", "total"]
    for table_html in re.findall(
        r"<table[^>]*>.*?</table>", page.text, flags=re.IGNORECASE | re.DOTALL
    ):
        table_row_htmls = re.findall(
            r"<tr[^>]*>.*?</tr>", table_html, flags=re.IGNORECASE | re.DOTALL
        )
        for row_index, row_html in enumerate(table_row_htmls):
            cells = expanded_table_row(row_html)
            if len(cells) != 7:
                continue
            row_label = canonical_table_label(cells[0])
            if row_label not in {"营业收入", "营业成本"}:
                continue
            expected_row_label = (
                "营业收入" if definition.code.endswith("revenue") else "营业成本"
            )
            if row_label != expected_row_label:
                continue
            amounts = [table_cell_numbers(cell) for cell in cells[1:]]
            if any(len(values) > 1 for values in amounts):
                continue

            category_row = next(
                (
                    expanded_table_row(header_html)
                    for header_html in reversed(table_row_htmls[max(0, row_index - 3) : row_index])
                    if len(expanded_table_row(header_html)) == 7
                    and [
                        category_headers.get(searchable_line(cell))
                        for cell in expanded_table_row(header_html)[1:]
                    ] == expected_categories
                ),
                None,
            )
            if category_row is None:
                continue

            roles_by_column = table_period_columns(
                table_row_htmls, row_index, current_period, previous_period
            )
            roles = [roles_by_column.get(column) for column in range(1, 7)]
            if roles not in (
                ["current"] * 3 + ["previous"] * 3,
                ["previous"] * 3 + ["current"] * 3,
            ):
                continue

            quote = " | ".join(
                cell
                for header_html in table_row_htmls[max(0, row_index - 3) : row_index + 1]
                for cell in expanded_table_row(header_html)
            )
            values = [numbers[0] if numbers else "" for numbers in amounts]
            current_group = 0 if roles[0] == "current" else 1
            previous_group = 1 - current_group
            return [
                values[current_group * 3 + category_index],
                values[previous_group * 3 + category_index],
            ], quote
    return None


def values_from_business_detail_table(
    definition: MetricDefinition, page: ParsedPage
) -> tuple[list[str], str] | None:
    if definition.code in {"operating_revenue", "operating_cost"}:
        rows = html_table_rows(page.text)
        for row_index, cells in enumerate(rows):
            if len(cells) != 5 or canonical_table_label(cells[0]) != "合计":
                continue
            # Only use a total row directly preceded by both business categories and
            # the expected four-column revenue/cost header. This avoids unrelated totals.
            prior_rows = rows[max(0, row_index - 4):row_index]
            category_labels = [canonical_table_label(row[0]) for row in prior_rows if row]
            if not all(label in category_labels for label in ("主营业务", "其他业务")):
                continue
            column_header = next(
                (
                    row for row in reversed(prior_rows)
                    if [
                        searchable_line(cell).replace("营业", "")
                        for cell in row if searchable_line(cell) != ""
                    ] == ["收入", "成本", "收入", "成本"]
                ),
                None,
            )
            period_header = next(
                (
                    row for row in prior_rows
                    if sum(period_column_role(cell, "9999", "0000") is not None for cell in row) >= 2
                    and any("本期" in searchable_line(cell) or "本年" in searchable_line(cell) for cell in row)
                    and any("上期" in searchable_line(cell) or "上年" in searchable_line(cell) for cell in row)
                ),
                None,
            )
            partial_period_header = next(
                (
                    row for row in prior_rows
                    if any("本期" in searchable_line(cell) or "本年" in searchable_line(cell) for cell in row)
                    and any(re.search(r"20\d{2}年", searchable_line(cell)) for cell in row)
                    and not any("上期" in searchable_line(cell) or "上年" in searchable_line(cell) for cell in row)
                ),
                None,
            )
            if column_header is None:
                continue
            if period_header is None and partial_period_header is not None:
                # A comparative stub such as “2022年8-12月” is not a full prior year.
                # Keep only the current-period values; never turn the blank stub into zero.
                current_values = [table_cell_numbers(cell) for cell in cells[1:3]]
                prior_values = [table_cell_numbers(cell) for cell in cells[3:5]]
                if all(len(values) == 1 for values in current_values) and all(not values for values in prior_values):
                    value_offset = 0 if definition.code == "operating_revenue" else 1
                    return [current_values[value_offset][0]], " | ".join(cells)
                continue
            if period_header is None:
                continue
            # A grouped current/previous revenue/cost table has four amount cells.
            roles = []
            for cell in period_header:
                role = (
                    "current" if any(token in searchable_line(cell) for token in ("本期", "本年", "当期"))
                    else "previous" if any(token in searchable_line(cell) for token in ("上期", "上年"))
                    else None
                )
                if role:
                    roles.append(role)
            if roles == ["current", "previous"]:
                roles = ["current", "current", "previous", "previous"]
            # The HTML table parser expands colspan cells, so a typical header yields
            # current/current/previous/previous. Only that unambiguous layout is used.
            if roles != ["current", "current", "previous", "previous"]:
                continue
            amounts = [table_cell_numbers(cell) for cell in cells[1:]]
            if len(amounts) != 4 or any(len(values) != 1 for values in amounts):
                continue
            value_offset = 0 if definition.code == "operating_revenue" else 1
            return [amounts[value_offset][0], amounts[value_offset + 2][0]], " | ".join(cells)
        return None

    value_offsets = {
        "main_business_revenue": 0,
        "main_business_cost": 1,
        "other_business_revenue": 2,
        "other_business_cost": 3,
    }
    offset = value_offsets.get(definition.code)
    if offset is None:
        return None
    # Some audit notes put several product/service rows under the main-business
    # income/cost headers and print the classification total at the bottom. Prefer
    # that explicit total so the first product row is not mistaken for all main
    # business activity.
    for table_html in re.findall(
        r"<table[^>]*>.*?</table>", page.text, flags=re.IGNORECASE | re.DOTALL
    ):
        table_rows = html_table_rows(table_html)
        for header_index, header in enumerate(table_rows):
            header_text = "".join(searchable_line(cell) for cell in header)
            if "主营业务收入" not in header_text or "主营业务成本" not in header_text:
                continue
            period_row = next(
                (
                    row
                    for row in table_rows[header_index + 1 : header_index + 5]
                    if len(row) >= 5
                    and sum(
                        any(token in searchable_line(cell) for token in ("本期", "本年", "上期", "上年"))
                        for cell in row
                    ) >= 4
                ),
                None,
            )
            if period_row is None:
                continue
            period_roles = [
                "current" if any(token in searchable_line(cell) for token in ("本期", "本年"))
                else "previous" if any(token in searchable_line(cell) for token in ("上期", "上年"))
                else None
                for cell in period_row[1:5]
            ]
            if len(period_roles) != 4 or any(role is None for role in period_roles):
                continue
            total_row = next(
                (
                    row
                    for row in table_rows[table_rows.index(period_row) + 1 :]
                    if row and canonical_table_label(row[0]) in {"合计", "小计"}
                ),
                None,
            )
            if total_row is None or len(total_row) < 5:
                continue
            amount_cells = [table_cell_numbers(cell) for cell in total_row[1:5]]
            if any(len(values) != 1 for values in amount_cells):
                continue
            amounts = [values[0] for values in amount_cells]
            group_start = 0 if offset == 0 else 2
            selected_roles = period_roles[group_start : group_start + 2]
            if set(selected_roles) != {"current", "previous"}:
                continue
            group_values = amounts[group_start : group_start + 2]
            return [
                group_values[selected_roles.index("current")],
                group_values[selected_roles.index("previous")],
            ], " | ".join(header + period_row + total_row)
    rows = html_table_rows(page.text)
    business_type = "主营业务" if offset < 2 else "其他业务"
    business_component = "收入" if offset % 2 == 0 else "成本"
    specific_label = searchable_line(f"{business_type}{business_component}")
    target_labels = {specific_label, searchable_line(business_type)}
    for row_index, cells in enumerate(rows):
        if len(cells) < 3 or canonical_table_label(cells[0]) not in target_labels:
            continue
        quote = " | ".join(cells)
        # A classification row can follow several business rows after its headers.
        header_rows = rows[max(0, row_index - 8) : row_index]
        if len(cells) == 3:
            if canonical_table_label(cells[0]) == specific_label:
                period_roles = [
                    role
                    for row in header_rows
                    for cell in row
                    if (role := (
                        "previous" if searchable_line(cell).startswith(("上年", "上期", "去年", "期初", "年初"))
                        else "current" if searchable_line(cell).startswith(("本年", "本期", "当期", "期末", "年末", "年累计数"))
                        else None
                    )) is not None
                ]
                if len(period_roles) == 2 and set(period_roles) == {"current", "previous"}:
                    amounts = [table_cell_numbers(cell) for cell in cells[1:]]
                    if all(len(values) == 1 for values in amounts):
                        return [amounts[period_roles.index("current")][0], amounts[period_roles.index("previous")][0]], " | ".join(cells)
            column_roles = [searchable_line(cell) for row in header_rows for cell in row
                            if searchable_line(cell) in {"收入", "成本"}]
            if len(column_roles) == 2 and set(column_roles) == {"收入", "成本"}:
                period_headers = [searchable_line(cell) for row in header_rows for cell in row
                                  if any(word in searchable_line(cell) for word in ("本期", "本年", "上期", "上年"))]
                if len(period_headers) != 1 or not any(word in period_headers[0] for word in ("本期", "本年")):
                    return [], quote
                values = table_cell_numbers(cells[1 + column_roles.index(business_component)])
                return (values, quote) if len(values) == 1 else ([], quote)
            continue
        if len(cells) < 5:
            continue
        period_row = next(
            (
                row
                for row in reversed(header_rows)
                if any(
                    "本期" in searchable_line(cell)
                    or "本年" in searchable_line(cell)
                    or "上期" in searchable_line(cell)
                    or "上年" in searchable_line(cell)
                    for cell in row
                )
            ),
            None,
        )
        if period_row is None:
            return [], quote
        partial_period_row = next(
            (
                row for row in reversed(header_rows)
                if any("本期" in searchable_line(cell) or "本年" in searchable_line(cell) for cell in row)
                and any(re.search(r"20\d{2}年", searchable_line(cell)) for cell in row)
                and not any("上期" in searchable_line(cell) or "上年" in searchable_line(cell) for cell in row)
            ),
            None,
        )
        period_cells = [
            searchable_line(cell)
            for cell in period_row
            if "本期" in searchable_line(cell)
            or "本年" in searchable_line(cell)
            or "上期" in searchable_line(cell)
            or "上年" in searchable_line(cell)
        ]
        partial_comparative_period = partial_period_row is not None or any(
            re.search(r"20\d{2}年", searchable_line(cell))
            and not any(token in searchable_line(cell) for token in ("本期", "本年", "上期", "上年"))
            for row in header_rows for cell in row
        )
        if partial_comparative_period:
            value_cells = cells[1:]
            amounts = [table_cell_numbers(cell) for cell in value_cells]
            if len(value_cells) == 4 and all(len(values) == 1 for values in amounts[:2]) and all(not values for values in amounts[2:]):
                # The comparison is a partial reporting period, so extract only the current year.
                return [amounts[offset % 2][0]], quote
        if len(period_cells) == 4:
            # Notes may group columns by revenue/cost, each with both years.
            headers = "".join(searchable_line(cell) for row in header_rows for cell in row)
            if "营业收入" not in headers or "营业成本" not in headers:
                return [], quote
            roles = ["current" if "本期" in cell or "本年" in cell else "previous" for cell in period_cells]
            if roles[:2] != roles[2:] or set(roles[:2]) != {"current", "previous"}:
                return [], quote
            column_offset = offset % 2
            if headers.index("营业收入") > headers.index("营业成本"):
                column_offset = 1 - column_offset
            numbers = [table_cell_numbers(cell) for cell in cells[1:]]
            if len(numbers) != 4 or any(len(values) != 1 for values in numbers):
                return [], quote
            start = column_offset * 2
            return [numbers[start + roles[:2].index("current")][0], numbers[start + roles[:2].index("previous")][0]], quote
        if len(period_cells) != 2:
            return [], quote
        current_group = next(
            (
                index
                for index, cell in enumerate(period_cells)
                if "本期" in cell or "本年" in cell
            ),
            None,
        )
        previous_group = next(
            (
                index
                for index, cell in enumerate(period_cells)
                if "上期" in cell or "上年" in cell
            ),
            None,
        )
        value_cells = cells[1:]
        if current_group is None or previous_group is None or len(value_cells) != 4:
            return [], quote
        cell_values = [table_cell_numbers(cell) for cell in value_cells]
        if any(len(values) != 1 for values in cell_values):
            return [], quote
        values = [numbers[0] for numbers in cell_values]
        column_offset = offset % 2
        return [values[current_group * 2 + column_offset], values[previous_group * 2 + column_offset]], quote
    return None


def values_from_business_category_row_with_revenue_cost_columns(
    definition: MetricDefinition, page: ParsedPage,
    current_period: str, previous_period: str,
) -> tuple[list[str], str] | None:
    """Read category rows whose four amount columns are revenue/current/prior and cost/current/prior."""
    category = {
        "main_business_revenue": "主营业务",
        "main_business_cost": "主营业务",
        "other_business_revenue": "其他业务",
        "other_business_cost": "其他业务",
    }.get(definition.code)
    if category is None:
        return None
    cost_metric = definition.code.endswith("cost")

    for table_html in re.findall(
        r"<table[^>]*>.*?</table>", page.text, flags=re.IGNORECASE | re.DOTALL
    ):
        rows = html_table_rows(table_html)
        for row_index, row in enumerate(rows):
            if len(row) != 5 or canonical_table_label(row[0]) != category:
                continue
            preceding = rows[:row_index]
            period_row = next(
                (
                    candidate for candidate in reversed(preceding)
                    if sum(
                        period_column_role(cell, current_period, previous_period) is not None
                        for cell in candidate
                    ) >= 4
                ),
                None,
            )
            if period_row is None:
                continue
            period_roles = [
                period_column_role(cell, current_period, previous_period)
                for cell in period_row
                if period_column_role(cell, current_period, previous_period) is not None
            ]
            if period_roles not in (
                ["current", "previous", "current", "previous"],
                ["previous", "current", "previous", "current"],
                ["current", "current", "previous", "previous"],
                ["previous", "previous", "current", "current"],
            ):
                continue
            headers = "".join(
                searchable_line(cell) for header in preceding for cell in header
            )
            revenue_position = headers.find("营业收入")
            cost_position = headers.find("营业成本")
            if revenue_position < 0 or cost_position < 0 or revenue_position > cost_position:
                continue
            amount_cells = row[1:]
            parsed = [table_cell_numbers(cell) for cell in amount_cells]
            if any(len(values) > 1 for values in parsed):
                continue
            roles_for_values = period_roles
            if roles_for_values[0] == roles_for_values[1]:
                # Columns are grouped by period: current revenue/cost, then previous revenue/cost.
                selected_columns = (1, 3) if cost_metric else (0, 2)
            else:
                # Columns are grouped by statement line: revenue current/previous, then cost current/previous.
                selected_columns = (2, 3) if cost_metric else (0, 1)
            dash_values = {"-", "−", "–", "—", "－"}
            ordered_by_role: dict[str, str] = {}
            for column in selected_columns:
                raw = amount_cells[column].strip()
                if searchable_line(raw) in dash_values:
                    value = "0"
                elif parsed[column]:
                    value = parsed[column][0]
                else:
                    value = ""
                ordered_by_role[roles_for_values[column]] = value
            ordered = [ordered_by_role["current"], ordered_by_role["previous"]]
            quote = " | ".join(row)
            return ordered, quote
    return None


def values_from_product_material_detail_table(
    definition: MetricDefinition, page: ParsedPage,
    current_period: str, previous_period: str,
) -> tuple[list[str], str] | None:
    """Map explicit product/material sales rows only when each table reconciles."""
    code_kind = {
        "main_business_revenue": ("revenue", "product"),
        "main_business_cost": ("cost", "product"),
        "other_business_revenue": ("revenue", "material"),
        "other_business_cost": ("cost", "material"),
        "operating_revenue": ("revenue", "total"),
        "operating_cost": ("cost", "total"),
    }.get(definition.code)
    if code_kind is None:
        return None
    target_kind, target_row = code_kind
    labels = {
        "product": {"销售产品", "销售商品"},
        "material": {"销售材料"},
        "total": {"合计"},
    }
    for table_match in re.finditer(
        r"<table[^>]*>.*?</table>", page.text, flags=re.IGNORECASE | re.DOTALL
    ):
        table_html = table_match.group(0)
        rows = html_table_rows(table_html)
        row_map = {
            canonical_table_label(row[0]): row
            for row in rows
            if len(row) == 3 and canonical_table_label(row[0])
        }
        product_row = next((row_map[label] for label in labels["product"] if label in row_map), None)
        material_row = next((row_map[label] for label in labels["material"] if label in row_map), None)
        total_row = row_map.get("合计")
        if product_row is None or material_row is None or total_row is None:
            continue

        nearby_text = searchable_line(page.text[max(0, table_match.start() - 300):table_match.start()])
        revenue_pos = nearby_text.rfind("营业收入")
        cost_pos = nearby_text.rfind("营业成本")
        nearest_kind = "revenue" if revenue_pos > cost_pos else "cost"
        if max(revenue_pos, cost_pos) < 0 or nearest_kind != target_kind:
            continue

        header_rows = rows[:rows.index(product_row)]
        period_roles: list[str] = []
        for row in header_rows:
            for cell in row:
                role = period_column_role(cell, current_period, previous_period)
                if role is not None and (not period_roles or period_roles[-1] != role):
                    period_roles.append(role)
        if period_roles not in (["current", "previous"], ["previous", "current"]):
            continue

        values: dict[str, dict[str, Decimal]] = {}
        for kind, row in (("product", product_row), ("material", material_row), ("total", total_row)):
            parsed = [table_cell_numbers(cell) for cell in row[1:]]
            if any(len(cell_values) != 1 for cell_values in parsed):
                values = {}
                break
            ordered = [cell_values[0] for cell_values in parsed]
            if period_roles == ["previous", "current"]:
                ordered.reverse()
            values[kind] = {
                "current": normalize_number(ordered[0]),
                "previous": normalize_number(ordered[1]),
            }
        if not values:
            continue
        if any(
            values["product"][period] + values["material"][period] != values["total"][period]
            for period in ("current", "previous")
        ):
            continue

        selected = values[target_row]
        quote = " | ".join(
            cell for kind in ("product", "material", "total")
            for cell in row_map[next(label for label in labels[kind] if label in row_map)]
        )
        return [str(selected["current"]), str(selected["previous"])], quote
    return None


def values_from_product_scrap_business_table(
    definition: MetricDefinition, page: ParsedPage,
    current_period: str, previous_period: str,
) -> tuple[list[str], str] | None:
    """Read product/scrap classifications from four-column revenue/cost notes."""
    target = {
        "main_business_revenue": ("product", 0),
        "other_business_revenue": ("scrap", 0),
        "main_business_cost": ("product", 1),
        "other_business_cost": ("scrap", 1),
        "operating_revenue": ("total", 0),
        "operating_cost": ("total", 1),
    }.get(definition.code)
    if target is None:
        return None

    labels = {
        "product": {"产品销售", "产品销售收入", "商品销售", "商品销售收入"},
        "scrap": {"废品销售", "废品销售收入", "废料销售", "废料销售收入"},
        "total": {"合计", "总计"},
    }
    for table_match in re.finditer(
        r"<table[^>]*>.*?</table>", page.text, flags=re.IGNORECASE | re.DOTALL
    ):
        nearby = searchable_line(page.text[max(0, table_match.start() - 500):table_match.start()])
        if not any(title in nearby for title in ("营业收入、营业成本", "营业收入及营业成本", "营业收入和营业成本")):
            continue
        rows = html_table_rows(table_match.group(0))
        period_row = next(
            (
                row for row in rows
                if len(row) >= 5
                and sum(period_column_role(cell, current_period, previous_period) is not None for cell in row) >= 4
            ),
            None,
        )
        if period_row is None:
            continue
        roles = [period_column_role(cell, current_period, previous_period) for cell in period_row[1:]]
        roles = [role for role in roles if role is not None]
        if roles not in (["current", "previous", "current", "previous"], ["previous", "current", "previous", "current"]):
            continue
        data_rows = {}
        for kind, accepted in labels.items():
            data_rows[kind] = next(
                (row for row in rows if row and canonical_table_label(row[0]) in accepted),
                None,
            )
        if any(row is None or len(row) < 5 for row in data_rows.values()):
            continue

        parsed = {}
        for kind, row in data_rows.items():
            amount_cells = [table_cell_numbers(cell) for cell in row[1:5]]
            if any(len(amounts) != 1 for amounts in amount_cells):
                parsed = {}
                break
            amounts = [normalize_number(amounts[0]) for amounts in amount_cells]
            if roles[0] == "previous":
                amounts = [amounts[1], amounts[0], amounts[3], amounts[2]]
            parsed[kind] = amounts
        if not parsed:
            continue
        if any(parsed["product"][index] + parsed["scrap"][index] != parsed["total"][index] for index in range(4)):
            continue

        kind, measure = target
        group = measure * 2
        current_index = 0 if roles[0] == "current" else 1
        previous_index = 1 - current_index
        values = parsed[kind]
        quote = " | ".join(" | ".join(data_rows[name]) for name in ("product", "scrap", "total"))
        return [str(values[group + current_index]), str(values[group + previous_index])], quote
    return None


def values_from_single_product_business_table(
    definition: MetricDefinition, page: ParsedPage,
    current_period: str, previous_period: str,
) -> tuple[list[str], str] | None:
    """Use a sole product row as main business only when it fully equals the total."""
    if definition.code not in {"main_business_revenue", "main_business_cost"}:
        return None
    target_kind = "revenue" if definition.code.endswith("revenue") else "cost"
    previous_table_end = 0
    for table_match in re.finditer(
        r"<table[^>]*>.*?</table>", page.text, flags=re.IGNORECASE | re.DOTALL
    ):
        rows = html_table_rows(table_match.group(0))
        data_rows = [
            row for row in rows
            if len(row) == 3 and canonical_table_label(row[0])
            and canonical_table_label(row[0]) not in {"合计", "总计", "其中"}
            and all(len(table_cell_numbers(cell)) == 1 for cell in row[1:])
        ]
        total_row = next((row for row in rows if len(row) == 3 and canonical_table_label(row[0]) in {"合计", "总计"}), None)
        if len(data_rows) != 1 or total_row is None:
            continue
        # This rule applies to an explicitly titled income/cost note, not arbitrary tables.
        context = searchable_line(page.text[max(0, table_match.start() - 900):table_match.start()])
        if not any(title in context for title in ("营业收入及营业成本", "营业收入和营业成本", "营业收入、营业成本", "营业收入及成本")):
            continue
        local_context = searchable_line(page.text[previous_table_end:table_match.start()])
        previous_table_end = table_match.end()
        revenue_pos = max(local_context.rfind("营业收入"), local_context.rfind("主营业务收入"))
        cost_pos = max(local_context.rfind("营业成本"), local_context.rfind("主营业务成本"))
        nearest_kind = "revenue" if revenue_pos > cost_pos else "cost"
        if max(revenue_pos, cost_pos) < 0 or nearest_kind != target_kind:
            continue
        header_rows = rows[:rows.index(data_rows[0])]
        roles: list[str] = []
        for row in header_rows:
            for cell in row:
                role = period_column_role(cell, current_period, previous_period)
                if role is not None and (not roles or roles[-1] != role):
                    roles.append(role)
        if roles not in (["current", "previous"], ["previous", "current"]):
            continue
        parsed_data = [table_cell_numbers(cell) for cell in data_rows[0][1:]]
        parsed_total = [table_cell_numbers(cell) for cell in total_row[1:]]
        if any(len(values) != 1 for values in parsed_data + parsed_total):
            continue
        data_values = [values[0] for values in parsed_data]
        total_values = [values[0] for values in parsed_total]
        if roles == ["previous", "current"]:
            data_values.reverse()
            total_values.reverse()
        if any(normalize_number(value) != normalize_number(total) for value, total in zip(data_values, total_values, strict=True)):
            continue
        return data_values, " | ".join(data_rows[0])
    return None


def values_from_text_business_detail_table(
    definition: MetricDefinition, page: ParsedPage,
    current_period: str, previous_period: str,
) -> tuple[list[str], str] | None:
    offset = {
        "main_business_revenue": 0,
        "main_business_cost": 1,
        "other_business_revenue": 2,
        "other_business_cost": 3,
    }.get(definition.code)
    if offset is None or "<table" in page.text.lower():
        return None
    lines = [compact_line(line) for line in page.text.splitlines() if compact_line(line)]
    for index, line in enumerate(lines):
        business_type = "主营业务" if offset < 2 else "其他业务"
        if not re.fullmatch(rf"{business_type}(?:收入)?\s+(?:-?[\d,]+(?:\.\d{{1,2}})?\s+){{3}}-?[\d,]+(?:\.\d{{1,2}})?", line):
            continue
        headers = lines[max(0, index - 3):index]
        if not any(
            title in searchable_line(item)
            for item in lines[max(0, index - 10):index]
            for title in ("营业收入及成本", "营业收入及营业成本")
        ):
            continue
        if len(headers) < 2 or searchable_line(headers[-1]) != "收入成本收入成本":
            continue
        period_roles = [
            period_column_role(part, current_period, previous_period)
            for part in headers[-2].split()
        ]
        if period_roles not in (["current", "previous"], ["previous", "current"]):
            continue
        amounts = NUMBER_PATTERN.findall(line.split(maxsplit=1)[1])
        if len(amounts) != 4:
            continue
        group = period_roles.index("current")
        previous_group = period_roles.index("previous")
        column_offset = offset % 2
        return [amounts[group * 2 + column_offset], amounts[previous_group * 2 + column_offset]], " | ".join(headers[-2:] + [line])
    return None


def values_from_text_statement_row(
    definition: MetricDefinition, page: ParsedPage,
    current_period: str, previous_period: str,
) -> tuple[list[str], str] | None:
    if "<table" in page.text.lower():
        return None
    if definition.category not in ("资产负债表", "利润表", "现金流量表"):
        return None
    if definition.category not in searchable_line(page.text):
        return None
    lines = [compact_line(line) for line in page.text.splitlines() if compact_line(line)]
    header_index = None
    roles: list[str] = []
    for index, line in enumerate(lines[:12]):
        roles = [
            role for part in line.split()
            if (role := period_column_role(part, current_period, previous_period)) is not None
        ]
        if roles in (["current", "previous"], ["previous", "current"]):
            header_index = index
            break
    if header_index is None:
        return None
    aliases = {searchable_line(alias) for alias in definition.aliases}
    for line in lines[header_index + 1:]:
        match = re.match(
            r"^(.*?)\s+(-?[\d,，]+(?:\.\d+)?\s+-?[\d,，]+(?:\.\d+)?)\s*$", line
        )
        if match is None:
            continue
        label = match.group(1)
        label = re.sub(r"\s+(?:附注|注释)?[一二三四五六七八九十百]+[、.．]\d{1,3}$", "", label)
        label = re.sub(r"\s+(?:附注|注释)?[一二三四五六七八九十百]+[、.．]?$", "", label)
        canonical = canonical_table_label(label)
        if not any(canonical == alias or canonical.startswith(alias + "（")
                   or canonical.startswith(alias + "(") for alias in aliases):
            continue
        if definition.code == "fixed_assets" and "原价" in canonical:
            continue
        amounts = NUMBER_PATTERN.findall(match.group(2))
        if len(amounts) != 2:
            continue
        ordered = [amounts[roles.index("current")], amounts[roles.index("previous")]]
        return ordered, f"{lines[header_index]} | {line}"
    return None


def values_from_explicit_dash_statement_row(
    definition: MetricDefinition, page: ParsedPage,
    current_period: str, previous_period: str,
) -> tuple[list[str | None], str] | None:
    """Treat explicit dash cells in a financial statement as zero, never blanks."""
    if definition.category not in {"资产负债表", "利润表", "现金流量表"}:
        return None
    if definition.category not in searchable_line(page.text[:500]):
        return None
    aliases = {searchable_line(alias) for alias in definition.aliases}
    dash_values = {"-", "−", "–", "—", "－"}
    for table_html in re.findall(
        r"<table[^>]*>.*?</table>", page.text, flags=re.IGNORECASE | re.DOTALL
    ):
        rows = html_table_rows(table_html)
        for row_index, row in enumerate(rows):
            if not row:
                continue
            label_columns = [
                index for index, cell in enumerate(row)
                if (label := canonical_table_label(cell))
                and any(label == alias or label.startswith(alias + "（") or label.startswith(alias + "(") for alias in aliases)
            ]
            if not label_columns:
                continue
            header = next(
                (
                    header_row for header_row in reversed(rows[:row_index])
                    if sum(period_column_role(cell, current_period, previous_period) is not None for cell in header_row) >= 2
                ),
                None,
            )
            if header is None:
                continue
            positions: dict[str, int] = {}
            for index, cell in enumerate(header):
                role = period_column_role(cell, current_period, previous_period)
                if role is not None:
                    positions[role] = index
            if set(positions) != {"current", "previous"}:
                continue
            if max(positions.values()) >= len(row):
                continue
            raw_values = [row[positions["current"]].strip(), row[positions["previous"]].strip()]
            if not any(searchable_line(value) in dash_values for value in raw_values):
                continue
            normalized_values: list[str | None] = []
            for raw in raw_values:
                if searchable_line(raw) in dash_values:
                    normalized_values.append("0")
                    continue
                if not raw.strip():
                    normalized_values.append(None)
                    continue
                amounts = table_cell_numbers(raw)
                if len(amounts) != 1:
                    break
                normalized_values.append(amounts[0])
            if len(normalized_values) == 2:
                return normalized_values, " | ".join(row)
    return None


def values_from_period_aligned_statement_row(
    definition: MetricDefinition, page: ParsedPage,
    current_period: str, previous_period: str,
) -> tuple[list[str | None], str] | None:
    """Keep a lone statement amount in the period column where it was printed."""
    if definition.code not in CORE_FINANCIAL_METRIC_CODES:
        return None
    if "利润表" not in searchable_line(page.text[:500]):
        return None
    aliases = {searchable_line(alias) for alias in definition.aliases}
    for table_html in re.findall(
        r"<table[^>]*>.*?</table>", page.text, flags=re.IGNORECASE | re.DOTALL
    ):
        rows = html_table_rows(table_html)
        for row_index, row in enumerate(rows):
            if not row:
                continue
            label = canonical_table_label(row[0])
            if not any(label == alias or label.startswith(alias + "（") or label.startswith(alias + "(") for alias in aliases):
                continue
            header = next(
                (
                    header_row for header_row in reversed(rows[:row_index])
                    if sum(period_column_role(cell, current_period, previous_period) is not None for cell in header_row) >= 2
                ),
                None,
            )
            if header is None:
                continue
            positions: dict[str, int] = {}
            for index, cell in enumerate(header):
                role = period_column_role(cell, current_period, previous_period)
                if role is not None:
                    positions[role] = index
            if set(positions) != {"current", "previous"} or max(positions.values()) >= len(row):
                continue
            ordered: list[str | None] = []
            for role in ("current", "previous"):
                raw = row[positions[role]].strip()
                if not raw:
                    ordered.append(None)
                    continue
                if searchable_line(raw) in {"-", "−", "–", "—", "－"}:
                    ordered.append("0")
                    continue
                numbers = table_cell_numbers(raw)
                if len(numbers) != 1:
                    break
                ordered.append(numbers[0])
            if len(ordered) == 2 and any(value is not None for value in ordered):
                return ordered, " | ".join(row)
    return None


def values_from_opening_closing_balance_row(
    definition: MetricDefinition, page: ParsedPage,
    current_period: str, previous_period: str,
) -> tuple[list[str | None], str] | None:
    """Read explicit 年初/期末 columns in a side-by-side balance sheet."""
    if definition.category != "资产负债表" or "资产负债表" not in searchable_line(page.text[:500]):
        return None
    aliases = {searchable_line(alias) for alias in definition.aliases}
    for table_html in re.findall(
        r"<table[^>]*>.*?</table>", page.text, flags=re.IGNORECASE | re.DOTALL
    ):
        rows = html_table_rows(table_html)
        for row_index, row in enumerate(rows):
            label_columns = [
                index for index, cell in enumerate(row)
                if (label := canonical_table_label(cell))
                and any(label == alias or label.startswith(alias + "（") or label.startswith(alias + "(") for alias in aliases)
            ]
            if not label_columns:
                continue
            header = next(
                (candidate for candidate in reversed(rows[:row_index])
                 if any(searchable_line(cell) == "年初余额" for cell in candidate)
                 and any(searchable_line(cell) == "期末余额" for cell in candidate)),
                None,
            )
            if header is None:
                continue
            roles = [(index, period_column_role(cell, current_period, previous_period))
                     for index, cell in enumerate(header)]
            for label_column in label_columns:
                positions = {
                    role: next((index for index, candidate_role in roles
                                if index > label_column and candidate_role == role), None)
                    for role in ("current", "previous")
                }
                if None in positions.values() or max(positions.values()) >= len(row):
                    continue
                ordered: list[str | None] = []
                for role in ("current", "previous"):
                    raw = row[positions[role]].strip()
                    if not raw:
                        ordered.append(None)
                    elif searchable_line(raw) in {"-", "−", "–", "—", "－"}:
                        ordered.append("0")
                    else:
                        numbers = table_cell_numbers(raw)
                        if len(numbers) != 1:
                            break
                        ordered.append(numbers[0])
                if len(ordered) == 2 and any(value is not None for value in ordered):
                    return ordered, " | ".join(row)
    return None


def values_from_cash_breakdown_note(
    definition: MetricDefinition, page: ParsedPage,
    current_period: str, previous_period: str,
) -> list[ExtractedMetric] | None:
    """Prefer a complete cash-note total over a misaligned paired-statement row."""
    if definition.code != "cash" or "货币资金" not in searchable_line(page.text):
        return None
    for table_html in re.findall(
        r"<table[^>]*>.*?</table>", page.text, flags=re.IGNORECASE | re.DOTALL
    ):
        rows = html_table_rows(table_html)
        labels = [canonical_table_label(row[0]) for row in rows if row]
        if not {"库存现金", "银行存款", "合计"}.issubset(set(labels)):
            continue
        for row_index, row in enumerate(rows):
            if not row or canonical_table_label(row[0]) != "合计":
                continue
            header = next(
                (
                    candidate for candidate in reversed(rows[:row_index])
                    if any(period_column_role(cell, current_period, previous_period) == "current" for cell in candidate)
                    and any(period_column_role(cell, current_period, previous_period) == "previous" for cell in candidate)
                ),
                None,
            )
            if header is None:
                continue
            positions = {
                role: next(
                    (index for index, cell in enumerate(header)
                     if period_column_role(cell, current_period, previous_period) == role),
                    None,
                )
                for role in ("current", "previous")
            }
            if any(index is None or index >= len(row) for index in positions.values()):
                continue
            ordered: dict[str, str] = {}
            for role in ("current", "previous"):
                raw = row[positions[role]].strip()
                if searchable_line(raw) in {"-", "−", "–", "—", "－"}:
                    ordered[role] = "0"
                    continue
                numbers = table_cell_numbers(raw)
                if len(numbers) != 1:
                    break
                ordered[role] = numbers[0]
            if len(ordered) != 2:
                continue
            quote = " | ".join(header) + "；" + " | ".join(row)
            return [
                metric_for_period(
                    definition, ordered[role], detect_unit(page.text), period,
                    page.page_number, quote, Decimal("0.99"),
                )
                for role, period in (("current", current_period), ("previous", previous_period))
            ]
    return None


def values_from_blank_primary_operating_rows(
    definition: MetricDefinition, page: ParsedPage,
    current_period: str, previous_period: str,
) -> tuple[list[str], str] | None:
    """Use zero only when both statement totals are blank and net profit is reported."""
    if definition.code not in {"operating_revenue", "operating_cost"}:
        return None
    if "利润表" not in searchable_line(page.text[:500]):
        return None
    definitions = {metric.code: metric for metric in METRICS}
    aliases = {
        code: {searchable_line(alias) for alias in definitions[code].aliases}
        for code in ("operating_revenue", "operating_cost", "net_profit")
    }
    for table_html in re.findall(
        r"<table[^>]*>.*?</table>", page.text, flags=re.IGNORECASE | re.DOTALL
    ):
        rows = html_table_rows(table_html)
        target_rows: dict[str, list[str]] = {}
        for row in rows:
            if not row:
                continue
            label = canonical_table_label(row[0])
            for code, code_aliases in aliases.items():
                if any(label == alias or label.startswith(alias + "（") or label.startswith(alias + "(") for alias in code_aliases):
                    target_rows[code] = row
        if not all(code in target_rows for code in aliases):
            continue
        header = next(
            (
                header_row for header_row in reversed(rows[:rows.index(target_rows["net_profit"])])
                if sum(period_column_role(cell, current_period, previous_period) is not None for cell in header_row) >= 2
            ),
            None,
        )
        if header is None:
            continue
        positions: dict[str, int] = {}
        for index, cell in enumerate(header):
            role = period_column_role(cell, current_period, previous_period)
            if role is not None:
                positions[role] = index
        if set(positions) != {"current", "previous"}:
            continue
        if any(max(positions.values()) >= len(target_rows[code]) for code in aliases):
            continue
        blank_primary = all(
            not target_rows[code][positions[period]].strip()
            for code in ("operating_revenue", "operating_cost")
            for period in ("current", "previous")
        )
        reported_profit = all(
            len(table_cell_numbers(target_rows["net_profit"][positions[period]])) == 1
            for period in ("current", "previous")
        )
        if blank_primary and reported_profit:
            return ["0", "0"], " | ".join(target_rows[definition.code])
    return None


def derive_main_business_from_reconciled_other_business(
    metrics: list[ExtractedMetric], pages: list[ParsedPage],
) -> list[ExtractedMetric]:
    """Derive zero main-business amount only when the note's other-business total reconciles exactly."""
    definitions = {definition.code: definition for definition in METRICS}
    page_by_number = {page.page_number: page for page in pages}
    values = {(metric.definition.code, metric.period): metric for metric in metrics if metric.period}
    additions: list[ExtractedMetric] = []
    for kind, main_code, other_code, total_code, label in (
        ("revenue", "main_business_revenue", "other_business_revenue", "operating_revenue", "主营业务收入"),
        ("cost", "main_business_cost", "other_business_cost", "operating_cost", "主营业务成本"),
    ):
        periods = {period for code, period in values if code == other_code}
        for period in periods:
            if (main_code, period) in values:
                continue
            other = values[(other_code, period)]
            total = values.get((total_code, period))
            page = page_by_number.get(other.source_page)
            if total is None or page is None or total.normalized_value != other.normalized_value:
                continue
            source_text = searchable_line(page.text)
            if not all(term in source_text for term in ("其他业务", "合计")) or not any(
                term in source_text for term in ("营业收入及成本", "营业收入及营业成本", "营业收入和营业成本")
            ):
                continue
            quote = (
                f"附注PDF第{other.source_page}页其他业务{kind}与合计均为{other.value_text}元；"
                f"利润表PDF第{total.source_page}页营业{kind}总额为{total.value_text}元，完全相等，"
                f"据收入成本分类合计差额确认{label}为0元。"
            )
            additions.append(ExtractedMetric(
                definition=definitions[main_code], value_text="0", normalized_value=Decimal("0"),
                unit=other.unit, period=period, source_page=other.source_page,
                source_quote=quote, confidence=min(other.confidence, total.confidence, Decimal("0.90")),
            ))
    return metrics + additions


def values_from_split_business_table(
    definition: MetricDefinition, page: ParsedPage,
    current_period: str, previous_period: str,
) -> tuple[list[str], str] | None:
    other_component = {
        "other_business_revenue": ("其他业务收入", 0),
        "other_business_cost": ("其他业务成本", 2),
    }.get(definition.code)
    if other_component is not None:
        target_header, amount_offset = other_component
        companion_header = "其他业务成本" if amount_offset == 0 else "其他业务收入"
        # Some reports put revenue and cost in columns on the same row, while
        # naming the category row with the revenue measure only. A printed dash
        # is an explicit zero, but an empty cell remains undisclosed.
        target_codes = {
            "other_business_revenue": "revenue",
            "other_business_cost": "cost",
        }
        target_kind = target_codes.get(definition.code)
        target_measure = {"revenue": "\u6536\u5165", "cost": "\u6210\u672c"}.get(target_kind)
        for table_html in re.findall(
            r"<table[^>]*>.*?</table>", page.text, flags=re.IGNORECASE | re.DOTALL
        ):
            rows = html_table_rows(table_html)
            for row_index, row in enumerate(rows):
                if not row or canonical_table_label(row[0]) != "\u5176\u4ed6\u4e1a\u52a1\u6536\u5165":
                    continue
                header = next(
                    (
                        candidate for candidate in reversed(rows[:row_index])
                        if len(candidate) == 5
                        and all(period_column_role(candidate[index], current_period, previous_period)
                                is not None for index in range(1, 5))
                        and sum("收入" in searchable_line(candidate[index]) for index in range(1, 5)) == 2
                        and sum("成本" in searchable_line(candidate[index]) for index in range(1, 5)) == 2
                    ),
                    None,
                )
                if header is None or len(row) != 5 or target_kind is None:
                    continue
                measure_indices = [
                    index for index in range(1, 5)
                    if target_measure is not None and target_measure in searchable_line(header[index])
                ]
                if len(measure_indices) != 2:
                    continue
                period_indices = {
                    role: next(
                        (index for index in measure_indices
                         if period_column_role(header[index], current_period, previous_period) == role),
                        None,
                    )
                    for role in ("current", "previous")
                }
                if any(index is None for index in period_indices.values()):
                    continue
                normalized_amounts: list[str] = []
                for role in ("current", "previous"):
                    raw = row[period_indices[role]].strip()
                    if searchable_line(raw) in {"-", "−", "–", "—", "－"}:
                        normalized_amounts.append("0")
                        continue
                    if not raw:
                        break
                    amounts = table_cell_numbers(raw)
                    if len(amounts) != 1:
                        break
                    normalized_amounts.append(amounts[0])
                if len(normalized_amounts) == 2:
                    quote = " | ".join(header) + "；" + " | ".join(row)
                    return normalized_amounts, quote

            # Some reports list each business category as its own row with a
            # two-period header (本年发生数/上年发生数), and spell out zeros.
            for row_index, row in enumerate(rows):
                label_index = next(
                    (i for i, cell in enumerate(row) if searchable_line(cell) == searchable_line(target_header)),
                    None,
                )
                if label_index is None:
                    continue
                header = next(
                    (
                        candidate for candidate in reversed(rows[:row_index])
                        if any(period_column_role(cell, current_period, previous_period) == "current" for cell in candidate)
                        and any(period_column_role(cell, current_period, previous_period) == "previous" for cell in candidate)
                    ),
                    None,
                )
                if header is None:
                    continue
                current_columns = [
                    i for i, cell in enumerate(header)
                    if period_column_role(cell, current_period, previous_period) == "current"
                ]
                previous_columns = [
                    i for i, cell in enumerate(header)
                    if period_column_role(cell, current_period, previous_period) == "previous"
                ]
                if len(current_columns) != 1 or len(previous_columns) != 1:
                    continue
                indices = (current_columns[0], previous_columns[0])
                if max(indices) >= len(row):
                    continue
                dash_values = {"-", "−", "–", "—", "－"}
                normalized_amounts: list[str] = []
                for index in indices:
                    raw = row[index].strip()
                    if searchable_line(raw) in dash_values:
                        normalized_amounts.append("0")
                        continue
                    if not raw:
                        break
                    amounts = table_cell_numbers(raw)
                    if len(amounts) != 1:
                        break
                    normalized_amounts.append(amounts[0])
                if len(normalized_amounts) == 2:
                    return normalized_amounts, " | ".join(row)

            header_index = next(
                (i for i, row in enumerate(rows)
                 if target_header in "".join(searchable_line(cell) for cell in row)
                 and companion_header in "".join(searchable_line(cell) for cell in row)),
                None,
            )
            if header_index is None:
                continue
            period_row = next(
                (row for row in rows[header_index + 1:header_index + 4]
                 if len(row) >= 4 and sum(
                     period_column_role(cell, "9999", "0000") is not None for cell in row
                 ) >= 4),
                None,
            )
            if period_row is None:
                continue
            roles = [period_column_role(cell, "9999", "0000") for cell in period_row]
            roles = [role for role in roles if role is not None]
            if roles != ["current", "previous", "current", "previous"]:
                continue
            total = next(
                (row for row in rows[rows.index(period_row) + 1:]
                 if row and canonical_table_label(row[0]) == "合计"),
                None,
            )
            if total is None or len(total) < 5:
                continue
            amounts = [table_cell_numbers(cell) for cell in total[1:5]]
            selected = [amounts[amount_offset], amounts[amount_offset + 1]]
            # Blank cells stay absent. Do not infer zero for undisclosed costs.
            if all(len(values) == 1 for values in selected):
                return [values[0] for values in selected], " | ".join(total)
            return [], " | ".join(total)
        return None

    group_start = {
        "main_business_revenue": 0,
        "main_business_cost": 2,
    }.get(definition.code)
    if group_start is None:
        return None
    rows = html_table_rows(page.text)
    for row_index, cells in enumerate(rows):
        row_text = searchable_line(" ".join(cells))
        if "主营业务收入" not in row_text or "主营业务成本" not in row_text:
            continue
        nearby_rows = rows[row_index + 1 : row_index + 5]
        header_row = next(
            (
                row
                for row in nearby_rows
                if sum(
                    "本期" in searchable_line(cell)
                    or "本年" in searchable_line(cell)
                    or "上期" in searchable_line(cell)
                    or "上年" in searchable_line(cell)
                    for cell in row
                )
                >= 4
            ),
            None,
        )
        quote = " | ".join(cells)
        if header_row is None:
            return [], quote
        period_headers = [searchable_line(cell) for cell in header_row]
        if len(period_headers) > 4:
            period_headers = period_headers[-4:]
        selected_headers = period_headers[group_start : group_start + 2]
        current_positions = [
            index
            for index, header in enumerate(selected_headers)
            if "本期" in header or "本年" in header
        ]
        previous_positions = [
            index
            for index, header in enumerate(selected_headers)
            if "上期" in header or "上年" in header
        ]
        if len(current_positions) != 1 or len(previous_positions) != 1:
            return [], quote
        header_index = nearby_rows.index(header_row)
        for value_row in nearby_rows[header_index + 1 :]:
            value_cells = value_row[-4:]
            if len(value_cells) < 4:
                continue
            cell_values = [table_cell_numbers(cell) for cell in value_cells]
            if any(len(numbers) != 1 for numbers in cell_values):
                continue
            group_values = [numbers[0] for numbers in cell_values[group_start : group_start + 2]]
            quote = " | ".join(cells + header_row + value_row)
            return [
                group_values[current_positions[0]],
                group_values[previous_positions[0]],
            ], quote
        return [], quote
    return None


def values_from_section_table_row(
    definition: MetricDefinition, page: ParsedPage,
    current_period: str, previous_period: str,
) -> tuple[list[str], str] | None:
    rule = SECTION_RULES.get(definition.code)
    if rule is None:
        return None
    headings, target_row, number_index = rule
    lines = page.text.splitlines(keepends=True)
    heading_line_index = next(
        (
            index
            for index, line in enumerate(lines)
            if any(searchable_line(heading) in searchable_line(line) for heading in headings)
        ),
        None,
    )
    if heading_line_index is None:
        return None
    section_text = "".join(lines[heading_line_index:])
    target = searchable_line(target_row)
    for table_html in re.findall(
        r"<table[^>]*>.*?</table>", section_text, flags=re.IGNORECASE | re.DOTALL
    ):
        rows = html_table_rows(table_html)
        for row_index, cells in enumerate(rows):
            if len(cells) < 3 or searchable_line(cells[0]) != target:
                continue
            numbers = [number for cell in cells[1:] for number in table_cell_numbers(cell)]
            if len(numbers) < 4:
                continue
            roles: list[str] = []
            for header_row in rows[:row_index]:
                for cell in header_row:
                    role = period_column_role(cell, current_period, previous_period)
                    if role is not None and (not roles or roles[-1] != role):
                        roles.append(role)
            if roles not in (["current", "previous"], ["previous", "current"]):
                raise ValueError("附注收入成本表年度列头缺失或冲突，不能安全归属年度")
            return [
                numbers[roles.index("current") * 2 + number_index],
                numbers[roles.index("previous") * 2 + number_index],
            ], " | ".join(cells)
    return None


def is_fixed_asset_useful_life_table_page(definition: MetricDefinition, page: ParsedPage) -> bool:
    """Reject depreciation-policy tables as evidence for the fixed-asset balance."""
    if definition.code != "fixed_assets":
        return False
    text = searchable_line(page.text)
    has_useful_life_table = "预计使用年限" in text and "年折旧率" in text
    has_balance_row = "固定资产净值" in text or "固定资产账面价值" in text
    return has_useful_life_table and not has_balance_row


def is_fixed_asset_depreciation_note_page(definition: MetricDefinition, page: ParsedPage) -> bool:
    """Reject depreciation-note pages that mention fixed assets but no net balance."""
    if definition.code != "fixed_assets":
        return False
    text = searchable_line(page.text)
    has_depreciation_note = "固定资产累计折旧" in text or "固定资产累计折旧额" in text
    has_net_balance = "固定资产净值" in text or "固定资产账面价值" in text
    return has_depreciation_note and not has_net_balance


def find_metric_periods_in_page(
    definition: MetricDefinition, page: ParsedPage, current_period: str, previous_period: str
) -> list[ExtractedMetric]:
    cash_note_values = values_from_cash_breakdown_note(
        definition, page, current_period, previous_period
    )
    if cash_note_values is not None:
        return cash_note_values
    if is_fixed_asset_useful_life_table_page(definition, page) or is_fixed_asset_depreciation_note_page(definition, page):
        return []
    # A balance sheet may print gross fixed assets, accumulated depreciation,
    # and net book value as separate rows. In that layout the workbench's
    # fixed_assets metric must bind to the explicit net-value row.
    if (
        definition.code == "fixed_assets"
        and "固定资产净值" in page.text
        and "累计折旧" in page.text
    ):
        definition = replace(
            definition,
            label="固定资产净值",
            aliases=("固定资产净值", "固定资产账面价值"),
        )
    page_heading = searchable_line(page.text[:200])
    if re.match(r"^A\d{6}(?:\b|\s)", page.text.strip()) or is_table_of_contents_page(page) or any(
        title in page_heading for title in ("已更正错报汇总表", "已更正的错报和披露错报汇总表", "新准则调整分录")
    ):
        return []
    multi_year = values_from_multi_year_statement_row(definition, page)
    if multi_year is not None:
        return multi_year
    table_result = values_from_explicit_dash_statement_row(
        definition, page, current_period, previous_period
    )
    values_already_ordered = table_result is not None
    if table_result is None:
        table_result = values_from_opening_closing_balance_row(
            definition, page, current_period, previous_period
        )
        values_already_ordered = table_result is not None
    if table_result is None:
        table_result = values_from_period_aligned_statement_row(
            definition, page, current_period, previous_period
        )
        values_already_ordered = table_result is not None
    if table_result is None:
        table_result = values_from_blank_primary_operating_rows(
            definition, page, current_period, previous_period
        )
        values_already_ordered = table_result is not None
    if table_result is None:
        table_result = values_from_combined_company_table(
            definition, page, current_period, previous_period
        )
        values_already_ordered = table_result is not None
    if table_result is None:
        table_result = values_from_business_category_columns(
            definition, page, current_period, previous_period
        )
        values_already_ordered = table_result is not None
    if table_result is None:
        table_result = values_from_business_category_row_with_revenue_cost_columns(
            definition, page, current_period, previous_period
        )
        values_already_ordered = table_result is not None
    if table_result is None:
        if definition.code in {"main_business_revenue", "main_business_cost"}:
            table_result = values_from_business_detail_table(definition, page)
            values_already_ordered = table_result is not None
        if table_result is None:
            table_result = values_from_split_business_table(
                definition, page, current_period, previous_period
            )
            values_already_ordered = table_result is not None
    if table_result is None:
        table_result = values_from_business_detail_table(definition, page)
        values_already_ordered = table_result is not None
    if table_result is None:
        table_result = values_from_single_product_business_table(
            definition, page, current_period, previous_period
        )
        values_already_ordered = table_result is not None
    if table_result is None:
        table_result = values_from_product_scrap_business_table(
            definition, page, current_period, previous_period
        )
        values_already_ordered = table_result is not None
    if table_result is None:
        table_result = values_from_product_material_detail_table(
            definition, page, current_period, previous_period
        )
        values_already_ordered = table_result is not None
    if table_result is None:
        table_result = values_from_text_business_detail_table(
            definition, page, current_period, previous_period
        )
        values_already_ordered = table_result is not None
    if table_result is None:
        table_result = values_from_text_statement_row(
            definition, page, current_period, previous_period
        )
        values_already_ordered = table_result is not None
    if table_result is None:
        table_result = values_from_paired_balance_total_row(definition, page)
        values_already_ordered = table_result is not None
    if table_result is None:
        table_result = values_from_named_table_row(definition, page)
        # Keep the table's physical left-to-right order so its year headers can
        # assign prior/current periods instead of assuming newest-first.
        values_already_ordered = False
    confidence = Decimal("0.96")
    if table_result is None:
        if definition.code in {"operating_revenue", "operating_cost"} and any(
            title in searchable_line(page.text)
            for title in ("营业收入和营业成本", "营业收入及营业成本", "营业收入、营业成本")
        ) and "主营业务" in searchable_line(page.text) and "其他业务" in searchable_line(page.text):
            # Avoid treating a main-business-only subtotal as the operating total.
            return []
        table_result = values_from_section_table_row(
            definition, page, current_period, previous_period
        )
        values_already_ordered = table_result is not None
        confidence = Decimal("0.90")
    if table_result is not None:
        values, quote = table_result
        if not values_already_ordered:
            values = order_values_by_table_header(
                page.text, quote, values, current_period, previous_period, definition
            )
        candidates = [
            metric_for_period(
                definition, value, detect_unit(page.text), period,
                page.page_number, quote, confidence,
            )
            for value, period in zip(values[:2], (current_period, previous_period), strict=False)
            if value is not None
        ]
        return [candidate for candidate in candidates if candidate is not None]

    current = find_metric_in_page(definition, page)
    if current is None:
        return []
    return [replace(current, period=current_period)]


def values_from_multi_year_statement_row(
    definition: MetricDefinition, page: ParsedPage,
) -> list[ExtractedMetric] | None:
    """Read rows with three or more explicit year columns, preserving each year."""
    page_text = searchable_line(page.text[:3000])
    if definition.category == "资产负债表" and "资产负债表" not in page_text:
        return None
    if definition.category == "利润表" and not any(
        title in page_text
        for title in ("利润表", "营业收入及成本", "营业收入和营业成本", "营业收入、营业成本")
    ):
        return None
    year_pattern = re.compile(
        r"(?<!\d)(20\d{2})(?=\s*(?:年度?|[./-]\s*12(?:[./-]\s*31)?))"
    )
    for table_html in re.findall(
        r"<table[^>]*>(.*?)</table>", page.text, flags=re.IGNORECASE | re.DOTALL
    ):
        row_htmls = re.findall(
            r"<tr[^>]*>(.*?)</tr>", table_html, flags=re.IGNORECASE | re.DOTALL
        )
        for header_index, row_html in enumerate(row_htmls):
            header_cells = expanded_table_row(row_html)
            years = {
                column: match.group(1)
                for column, cell in enumerate(header_cells)
                if (match := year_pattern.search(cell)) is not None
                and plausible_report_year(match.group(1))
            }
            if len(years) < 3 or len(set(years.values())) < 3:
                continue
            for data_html in row_htmls[header_index + 1 :]:
                cells = expanded_table_row(data_html)
                label_cells = [
                    re.sub(r"^[一二三四五六七八九十]+[、.．：:]?", "", searchable_line(cell))
                    for cell in cells[: min(years)] if searchable_line(cell)
                ]
                aliases = [searchable_line(alias) for alias in definition.aliases]
                if not any(
                    label == alias or label.startswith(alias)
                    for label in label_cells for alias in aliases
                ):
                    continue
                label_text = " ".join(label_cells)
                if definition.code in {"operating_revenue", "operating_cost"} and any(
                    label in label_text for label in ("主营业务", "其他业务")
                ):
                    continue
                quote = " | ".join(header_cells + cells)
                metrics: list[ExtractedMetric] = []
                for column, year in years.items():
                    if column >= len(cells):
                        continue
                    raw = cells[column].strip()
                    if not raw:
                        continue
                    if raw in {"-", "—", "–", "－"}:
                        raw = "0"
                    values = table_cell_numbers(raw)
                    if len(values) != 1:
                        continue
                    metric = metric_for_period(
                        definition, values[0], detect_unit(page.text), year,
                        page.page_number, quote, Decimal("0.96"),
                    )
                    if metric is not None:
                        metrics.append(metric)
                if metrics:
                    return metrics
    return None


def find_metric_in_page(definition: MetricDefinition, page: ParsedPage) -> ExtractedMetric | None:
    if is_fixed_asset_useful_life_table_page(definition, page) or is_fixed_asset_depreciation_note_page(definition, page):
        return None
    if (
        definition.code == "fixed_assets"
        and "固定资产净值" in page.text
        and "累计折旧" in page.text
    ):
        definition = replace(
            definition,
            label="固定资产净值",
            aliases=("固定资产净值", "固定资产账面价值"),
        )
    page_unit = detect_unit(page.text)
    period = detect_period(page.text)
    lines = [compact_line(line) for line in page.text.splitlines() if compact_line(line)]
    page_has_note_column = "附注" in searchable_line(page.text[:1500])
    page_has_index_column = any(
        marker in searchable_line(page.text[:1500]) for marker in ("行次", "栏次")
    )
    for line in lines:
        if "<table" in line.lower():
            continue
        line_for_search = searchable_line(line)
        ordered_aliases = sorted(
            definition.aliases,
            key=lambda alias: (
                f"<td>{searchable_line(alias)}</td>" not in line_for_search,
                -len(searchable_line(alias)),
            ),
        )
        for alias in ordered_aliases:
            searchable_alias = searchable_line(alias)
            line_for_search = searchable_line(line)
            exact_table_cell = f"<td>{searchable_alias}</td>"
            alias_position = line_for_search.find(exact_table_cell)
            matched_length = len(exact_table_cell)
            if alias_position < 0:
                alias_position = line_for_search.find(searchable_alias)
                matched_length = len(searchable_alias)
            if alias_position < 0:
                continue
            label_prefix = canonical_table_label(
                line_for_search[: alias_position + matched_length].replace("<td>", "").replace("</td>", "")
            )
            if not (
                label_prefix == searchable_alias
                or label_prefix.startswith(searchable_alias + "（")
                or label_prefix.startswith(searchable_alias + "(")
            ):
                continue
            after_alias = line_for_search[alias_position + matched_length :]
            if definition.code == "fixed_assets" and re.match(r"(?:原价|清理|累计折旧|本期折旧|折旧额)", after_alias):
                continue
            after_alias = re.sub(r"^[（(][^）)]{1,30}[）)]", "", after_alias).lstrip()
            if is_explicit_note_reference(after_alias.strip()):
                continue
            after_alias = re.sub(
                r"^(?:(?:附注|注释)\d{1,3}(?:[.．]\d{1,3})?|"
                r"(?:附注)?(?:[一二三四五六七八九十百]+[、.．]\d{1,3}|"
                r"[一二三四五六七八九十百]+[、.．]?[（(][一二三四五六七八九十百0-9、.．]+[）)](?:[、.．]?\d{1,3})?|"
                r"[（(][一二三四五六七八九十百]+[）)]\d{1,3}))(?=\s)",
                "",
                after_alias,
            ).lstrip()
            if page_has_note_column or page_has_index_column:
                after_alias = re.sub(
                    r"^\d{1,3}(?:[.．]\d{1,3})?(?=\s)", "", after_alias
                ).lstrip()
            number_match = NUMBER_PATTERN.search(after_alias)
            if number_match is None:
                continue
            if ("……" in line or re.search(r"\.{3,}", line)) and re.search(
                r"\d{1,3}(?:[-—]\d{1,3})?$", line_for_search
            ):
                continue
            raw_value = number_match.group(0)
            try:
                normalized = normalize_number(raw_value)
            except ValueError:
                continue
            confidence = Decimal("0.96") if alias == definition.label else Decimal("0.88")
            return ExtractedMetric(
                definition=definition,
                value_text=raw_value,
                normalized_value=normalized,
                unit=page_unit,
                period=period,
                source_page=page.page_number,
                source_quote=line[:500],
                confidence=confidence,
            )
    return find_metric_in_section(definition, page, lines)


def extract_financial_metrics(
    pages: list[ParsedPage], report_period: str,
    warnings: list[str] | None = None,
) -> list[ExtractedMetric]:
    current_period, previous_period = report_periods(report_period)
    notes_start = general_note_start_index(pages)
    primary_region = pages if notes_start is None else pages[:notes_start]
    partial_previous_categories = {
        category for category, title in (("利润表", "利润表"), ("现金流量表", "现金流量表"))
        if any(
            title in searchable_line(page.text[:3000])
            and re.search(
                rf"<td[^>]*>{previous_period}年\d{{1,2}}[-—至]\d{{1,2}}月</td>",
                searchable_line(page.text[:3000]),
            )
            for page in pages
        )
    }
    results: list[ExtractedMetric] = []
    for definition in METRICS:
        candidate_pages = pages
        if definition.category == "现金流量表":
            # Prefer company-level face statements when a report contains both
            # consolidated and company statements. Cash-flow note tables often
            # repeat consolidated totals and can otherwise win by page order.
            statement_pages = [
                page for page in primary_region
                if (
                    "现金流量表" in searchable_line(page.text[:500])
                    or (
                        "<table" in page.text.lower()
                        and all(marker in searchable_line(page.text) for marker in (
                            "经营活动产生的现金流量", "筹资活动产生的现金流量", "现金及现金等价物"
                        ))
                    )
                )
                and "附注" not in searchable_line(page.text[:500])
                and "补充资料" not in searchable_line(page.text[:500])
            ]
            company_pages = [
                page for page in statement_pages
                if "公司现金流量表" in searchable_line(page.text[:500])
                and "合并" not in searchable_line(page.text[:500])
            ]
            if company_pages:
                candidate_pages = company_pages
            elif statement_pages:
                nonconsolidated_pages = [
                    page for page in statement_pages
                    if "合并" not in searchable_line(page.text[:500])
                ]
                candidate_pages = nonconsolidated_pages or statement_pages
        if definition.category == "资产负债表":
            # A tax form may mention average assets before the actual balance sheet.
            statement_pages = [
                page for page in pages
                if "资产负债表" in searchable_line(page.text[:400])
            ]
            if statement_pages:
                candidate_pages = statement_pages + [
                    page for page in pages if page not in statement_pages
                ]
            if definition.code in {"accounts_receivable", "accounts_payable"}:
                # These are face-statement totals. Notes commonly list only
                # selected counterparties, which must not become the entity's
                # total when OCR misses the balance-sheet row.
                candidate_pages = statement_pages
        if definition.code == "cash":
            # Cash may be cross-laid next to liabilities on a paired balance
            # sheet, confusing column recognition. Prefer an explicit
            # cash-note total reconciled from cash on hand and bank deposits.
            cash_note_pages = [
                page for page in pages
                if values_from_cash_breakdown_note(
                    definition, page, current_period, previous_period
                ) is not None
            ]
            if cash_note_pages:
                candidate_pages = cash_note_pages + [
                    page for page in candidate_pages if page not in cash_note_pages
                ]
        if definition.code == "contract_liabilities":
            # Prefer an explicit contract-liabilities row when present. The
            # legacy aliases below remain a fallback for reports that only
            # contain customer advances.
            explicit_definition = MetricDefinition(
                "contract_liabilities", "合同负债", ("合同负债", "Contract Liabilities"), "资产负债表"
            )
            explicit_pages = [
                page for page in candidate_pages
                if find_metric_periods_in_page(
                    explicit_definition, page, current_period, previous_period
                )
            ]
            if explicit_pages:
                candidate_pages = explicit_pages
                definition = explicit_definition
        if definition.code == "advance_receipts":
            # Keep legacy pre-receipts mapped to contract liabilities when
            # that is the only source row. Split them only if the same
            # balance-sheet page also has a separately extractable explicit
            # contract-liabilities row.
            statement_pages = [
                page for page in pages
                if "资产负债表" in searchable_line(page.text[:400])
            ]
            explicit_contract_definition = MetricDefinition(
                "contract_liabilities", "合同负债", ("合同负债", "Contract Liabilities"), "资产负债表"
            )
            candidate_pages = [
                page for page in statement_pages
                if find_metric_periods_in_page(
                    explicit_contract_definition, page, current_period, previous_period
                )
            ]
            if not candidate_pages:
                continue
        if definition.code == "prepayments":
            statement_pages = [
                page for page in pages
                if "<table" in page.text.lower()
                and "资产负债表" in searchable_line(page.text[:400])
                and any(label in searchable_line(page.text) for label in ("资产总计", "资产合计"))
            ]
            if statement_pages:
                # Prefer the primary balance sheet, but keep note pages as a
                # fallback when prepayments are only disclosed in the notes.
                candidate_pages = statement_pages + [
                    page for page in pages if page not in statement_pages
                ]
        if definition.code in {"income_tax_expense", "selling_expenses"}:
            statement_pages = [
                page for page in pages
                if "<table" in page.text.lower()
                and "营业收入" in searchable_line(page.text)
                and (
                    "净利润" in searchable_line(page.text)
                    if definition.code == "income_tax_expense"
                    else "营业成本" in searchable_line(page.text)
                )
                and definition.label in searchable_line(page.text)
            ]
            if statement_pages:
                candidate_pages = statement_pages
        if definition.code == "owners_equity":
            total_assets_pages = [
                metric.source_page
                for metric in results
                if metric.definition.code == "total_assets" and metric.source_page is not None
            ]
            if len(total_assets_pages) > 0:
                first_total_assets_page = min(total_assets_pages)
                candidate_pages = [
                    page for page in pages if page.page_number >= first_total_assets_page
                ]
        result: list[ExtractedMetric] = []
        for page in candidate_pages:
            try:
                candidates = find_metric_periods_in_page(
                    definition, page, current_period, previous_period
                )
            except ValueError as exc:
                if warnings is not None:
                    warnings.append(
                        f"第{page.page_number}页{definition.label}未取数：{exc}"
                    )
                continue
            if (
                candidates
                and definition.category in partial_previous_categories
                and definition.category != "资产负债表"
            ):
                partial_period = partial_comparative_period(page, previous_period)
                if partial_period:
                    candidates = [
                        replace(metric, period=partial_period)
                        if metric.period == previous_period else metric
                        for metric in candidates
                    ]
                else:
                    candidates = [
                        metric for metric in candidates
                        if metric.period != previous_period
                    ]
            if candidates:
                result = candidates
                break
        results.extend(result)
    results = extract_reconciled_single_period_business_rows(
        results, pages, report_period
    )
    results = recover_multiline_main_business_totals(
        results, pages, current_period, previous_period
    )
    results = derive_main_business_from_reconciled_other_business(results, pages)
    promoted_results = promote_legacy_business_totals(results, pages)
    if warnings is not None:
        current_codes = {
            metric.definition.code for metric in promoted_results
            if metric.period == report_period
        }
        represented_periods = {report_period}
        represented_periods.update(
            metric.period for metric in promoted_results
            if metric.period in {current_period, previous_period}
        )
        definitions_by_code = {definition.code: definition for definition in METRICS}
        current_missing_core = []
        for period in sorted(represented_periods, reverse=True):
            period_codes = {
                metric.definition.code for metric in promoted_results
                if metric.period == period
            }
            for code in REQUIRED_COMPLETENESS_METRIC_CODES - {"main_business_revenue", "main_business_cost"}:
                definition = definitions_by_code[code]
                if code in period_codes:
                    continue
                if any(
                    alias in searchable_line(page.text)
                    for page in pages
                    for alias in definition.aliases
                ):
                    current_missing_core.append(f"{period}年{definition.label}")
        if current_missing_core:
            warnings.append(
                "原件中出现以下财务报表项目名称，但未提取到对应金额，请核对原件并补录或标缺失："
                + "、".join(current_missing_core)
            )
        missing_main = {
            code for code in ("main_business_revenue", "main_business_cost")
            if code not in current_codes
        }
        if missing_main:
            missing_labels = "、".join(
                "主营业务收入" if code == "main_business_revenue" else "主营业务成本"
                for code in ("main_business_revenue", "main_business_cost")
                if code in missing_main
            )
            warnings.append(
                f"未识别到本报告期{missing_labels}；需检查审计报告全文附注，未确认前不得以营业收入/成本总额替代。"
            )
        # Revenue and cost notes are often split across adjacent pages. Search
        # the full report for these markers instead of requiring all three on
        # one page, or a missing other-business cost row can go unnoticed.
        page_texts = [searchable_line(page.text) for page in pages]
        has_business_classification = all(
            any(marker in text for text in page_texts)
            for marker in ("其他业务", "营业收入", "营业成本")
        )
        missing_other = {
            code for code in ("other_business_revenue", "other_business_cost")
            if code not in current_codes
        }
        if has_business_classification and missing_other:
            missing_labels = "、".join(
                "其他业务收入" if code == "other_business_revenue" else "其他业务成本"
                for code in ("other_business_revenue", "other_business_cost")
                if code in missing_other
            )
            warnings.append(f"附注明确出现其他业务分类但未识别{missing_labels}，请人工复核原表。")
        else:
            # A gap between a disclosed main-business amount and the operating
            # total is evidence that classification data is incomplete, even
            # when OCR failed to retain the note's "其他业务" label.
            values_by_period: dict[str, dict[str, Decimal]] = {}
            for metric in promoted_results:
                if metric.period == report_period:
                    values_by_period.setdefault(metric.period, {})[metric.definition.code] = metric.normalized_value
            current_values = values_by_period.get(report_period, {})
            for main_code, other_code, total_code, main_label, other_label, total_label in (
                ("main_business_revenue", "other_business_revenue", "operating_revenue", "主营业务收入", "其他业务收入", "营业收入"),
                ("main_business_cost", "other_business_cost", "operating_cost", "主营业务成本", "其他业务成本", "营业成本"),
            ):
                if all(code in current_values for code in (main_code, total_code)) and other_code not in current_values:
                    gap = current_values[total_code] - current_values[main_code]
                    if abs(gap) > Decimal("0.02"):
                        warnings.append(
                            f"{main_label}与{total_label}相差{gap:.2f}元且未识别{other_label}；分类可能不完整，请复核附注。"
                        )
    try:
        return reconcile_business_total_conflicts(
            promoted_results, pages, current_period, previous_period
        )
    except ValueError as exc:
        if warnings is not None:
            warnings.append(f"附注收入成本表未用于冲突修正：{exc}")
        return promoted_results


def extract_full_years_from_interim_report(
    pages: list[ParsedPage],
) -> tuple[str, list[ExtractedMetric]] | None:
    """Read only the two complete years when a later interim column leads the same statements."""
    income_page = next(
        (
            page for page in pages
            if "母公司利润表" in searchable_line(page.text)
            and "<table" in page.text.lower()
            and any(
                re.fullmatch(r"20\d{2}年\d{1,2}[-—至]\d{1,2}月", searchable_line(cell))
                for row in html_table_rows(page.text)[:2] for cell in row
            )
        ),
        None,
    )
    if income_page is None:
        return None
    income_header = html_table_rows(income_page.text)[0]
    partial_years = [
        int(match.group(1))
        for cell in income_header
        if (match := re.fullmatch(
            r"(20\d{2})年\d{1,2}[-—至]\d{1,2}月", searchable_line(cell)
        )) is not None
    ]
    annual_years = [
        int(match.group(1))
        for cell in income_header
        if (match := re.fullmatch(r"(20\d{2})年度", searchable_line(cell))) is not None
    ]
    if (
        len(partial_years) != 1 or len(annual_years) != 2
        or annual_years[0] != annual_years[1] + 1
        or partial_years[0] != annual_years[0] + 1
    ):
        return None
    current_year, previous_year = annual_years
    primary_pages = [
        page for page in pages
        if income_page.page_number - 2 <= page.page_number <= income_page.page_number + 1
    ]
    if not any("母公司现金流量表" in searchable_line(page.text) for page in primary_pages):
        return None
    year_columns: list[tuple[ParsedPage, list[list[str]], list[str], int, int]] = []
    for page in primary_pages:
        rows = html_table_rows(page.text)
        if not rows:
            continue
        header = [searchable_line(cell) for cell in rows[0]]
        current_index = next((index for index, cell in enumerate(header) if cell in (
            f"{current_year}年度", f"{current_year}年12月31日"
        )), None)
        previous_index = next((index for index, cell in enumerate(header) if cell in (
            f"{previous_year}年度", f"{previous_year}年12月31日"
        )), None)
        if current_index is not None and previous_index is not None:
            year_columns.append((page, rows[1:], rows[0], current_index, previous_index))
    if len(year_columns) < 3:
        return None
    metrics: list[ExtractedMetric] = []
    for definition in METRICS:
        aliases = {searchable_line(alias) for alias in definition.aliases}
        for page, rows, header_cells, current_index, previous_index in year_columns:
            matched_row = next(
                (
                    row for row in rows
                    if row and any(
                        (label := canonical_table_label(row[0])) == alias
                        or label.startswith(alias + "(")
                        or label.startswith(alias + "（")
                        for alias in aliases
                    )
                ),
                None,
            )
            if matched_row is None:
                continue
            quote = " | ".join(header_cells) + "；" + " | ".join(matched_row)
            for index, year in ((current_index, current_year), (previous_index, previous_year)):
                if index >= len(matched_row):
                    continue
                values = table_cell_numbers(matched_row[index])
                if len(values) != 1:
                    continue
                metric = metric_for_period(
                    definition, values[0], detect_unit(page.text), str(year),
                    page.page_number, quote, Decimal("0.95"),
                )
                if metric is not None:
                    metrics.append(metric)
            break
    return str(current_year), metrics


def extract_reconciled_single_period_business_rows(
    metrics: list[ExtractedMetric], pages: list[ParsedPage], report_period: str,
) -> list[ExtractedMetric]:
    """Read one-period main/other tables only when their total matches a statement total."""
    totals = {
        metric.definition.code: metric.normalized_value
        for metric in metrics
        if metric.period == report_period
        and metric.definition.code in {"operating_revenue", "operating_cost"}
    }
    if len(totals) < 2:
        return metrics

    candidates: dict[str, set[tuple[str, str, str, int, str]]] = {
        "revenue": set(), "cost": set(),
    }
    for page in pages:
        for table_html in re.findall(
            r"<table[^>]*>.*?</table>", page.text, flags=re.IGNORECASE | re.DOTALL
        ):
            rows = html_table_rows(table_html)
            if not any(
                any(token in searchable_line(cell) for token in ("本期", "本年", "当期"))
                for row in rows[:3] for cell in row
            ):
                continue
            if any(
                any(token in searchable_line(cell) for token in ("上期", "上年", "去年"))
                for row in rows[:3] for cell in row
            ):
                continue

            category_values: dict[str, str] = {}
            for row in rows:
                if len(row) != 2:
                    continue
                label = canonical_table_label(row[0])
                if label not in {"主营业务", "其他业务", "合计"}:
                    continue
                values = table_cell_numbers(row[1])
                if len(values) == 1:
                    category_values[label] = values[0]
            if set(category_values) != {"主营业务", "其他业务", "合计"}:
                continue

            total_value = normalize_number(category_values["合计"])
            matches = [
                kind for kind, code in (("revenue", "operating_revenue"), ("cost", "operating_cost"))
                if abs(total_value - totals[code]) <= Decimal("0.02")
            ]
            if len(matches) != 1:
                continue
            kind = matches[0]
            quote = " | ".join(
                f"{label} {category_values[label]}"
                for label in ("主营业务", "其他业务", "合计")
            )
            candidates[kind].add((
                category_values["主营业务"], category_values["其他业务"],
                category_values["合计"], page.page_number, quote, detect_unit(page.text),
            ))

    definitions = {definition.code: definition for definition in METRICS}
    recovered: dict[tuple[str, str], ExtractedMetric] = {}
    for kind, found in candidates.items():
        # Conflicting candidate tables with the same total are ambiguous; leave them for review.
        value_sets = {(main, other, total) for main, other, total, _, _, _ in found}
        if len(value_sets) != 1 or not found:
            continue
        main_value, other_value, _, source_page, quote, unit = next(iter(found))
        main_code, other_code = (
            ("main_business_revenue", "other_business_revenue")
            if kind == "revenue" else ("main_business_cost", "other_business_cost")
        )
        for code, value in ((main_code, main_value), (other_code, other_value)):
            metric = metric_for_period(
                definitions[code], value, unit, report_period, source_page, quote,
                Decimal("0.94"),
            )
            if metric is not None:
                recovered[(code, report_period)] = metric

    if not recovered:
        return metrics
    merged = {
        (metric.definition.code, metric.period): metric
        for metric in metrics
    }
    merged.update(recovered)
    return list(merged.values())


def recover_multiline_main_business_totals(
    metrics: list[ExtractedMetric], pages: list[ParsedPage],
    current_period: str, previous_period: str,
) -> list[ExtractedMetric]:
    """Recover main-business subtotals when their classified rows span pages."""
    metric_values = {
        (metric.definition.code, metric.period): metric.normalized_value
        for metric in metrics if metric.period is not None
    }
    required_totals = {
        (code, period): metric_values.get((code, period))
        for code in ("operating_revenue", "operating_cost")
        for period in (current_period, previous_period)
    }

    row_pattern = re.compile(
        r"^(?P<label>.+?)\s+(?P<a1>(?:\d[\d,，]*(?:\.\d+)?|[-—–－−]))\s+"
        r"(?P<a2>(?:\d[\d,，]*(?:\.\d+)?|[-—–－−]))\s+"
        r"(?P<a3>(?:\d[\d,，]*(?:\.\d+)?|[-—–－−]))\s+"
        r"(?P<a4>(?:\d[\d,，]*(?:\.\d+)?|[-—–－−]))$"
    )

    def amount(token: str) -> Decimal:
        if token in {"-", "—", "–", "－", "−"}:
            return Decimal("0")
        return normalize_number(token)

    definitions = {definition.code: definition for definition in METRICS}
    for page_index, page in enumerate(pages[:-1]):
        lines = [compact_line(line) for line in page.text.splitlines() if compact_line(line)]
        section_start = next((
            i for i, line in enumerate(lines)
            if any(title in searchable_line(line) for title in (
                "营业收入及营业成本", "营业收入和营业成本", "营业收入、营业成本"
            ))
        ), None)
        if section_start is None:
            continue

        section_lines = lines[section_start:]
        next_page_lines = [
            compact_line(line) for line in pages[page_index + 1].text.splitlines()
            if compact_line(line)
        ]
        section_lines.extend(next_page_lines)
        classified: list[tuple[str, list[Decimal], str]] = []
        total: list[Decimal] | None = None
        for line in section_lines:
            match = row_pattern.match(line)
            if not match:
                continue
            label = searchable_line(match.group("label"))
            amounts = [amount(match.group(f"a{i}")) for i in range(1, 5)]
            if label in {"合计", "总计", "小计"}:
                total = amounts
                break
            if label.startswith(searchable_line("主营业务")):
                classified.append(("main", amounts, line))
            elif label.startswith(searchable_line("其他业务")):
                classified.append(("other", amounts, line))
        main_rows = [row for row in classified if row[0] == "main"]
        other_rows = [row for row in classified if row[0] == "other"]
        if total is None or len(main_rows) < 2 or not other_rows:
            continue

        def sums(rows: list[tuple[str, list[Decimal], str]]) -> list[Decimal]:
            return [sum((row[1][i] for row in rows), Decimal("0")) for i in range(4)]

        main_amounts = sums(main_rows)
        other_amounts = sums(other_rows)
        # Determine which pair of column groups is the current year by requiring
        # both revenue and cost totals to agree with the audited statements.
        for current_first in (True, False):
            main = main_amounts if current_first else [main_amounts[2], main_amounts[3], main_amounts[0], main_amounts[1]]
            other = other_amounts if current_first else [other_amounts[2], other_amounts[3], other_amounts[0], other_amounts[1]]
            totals = total if current_first else [total[2], total[3], total[0], total[1]]
            if [main[i] + other[i] for i in range(4)] != totals:
                continue
            expected_statement_totals = [
                required_totals[("operating_revenue", current_period)],
                required_totals[("operating_cost", current_period)],
                required_totals[("operating_revenue", previous_period)],
                required_totals[("operating_cost", previous_period)],
            ]
            if any(value is not None for value in expected_statement_totals):
                if any(
                    expected is not None and totals[index] != expected
                    for index, expected in enumerate(expected_statement_totals)
                ):
                    continue
            quote = "；".join([row[2] for row in classified] + ["合计 " + " ".join(str(value) for value in totals)])
            recovered: dict[tuple[str, str], ExtractedMetric] = {}
            for code, col in (("main_business_revenue", 0), ("main_business_cost", 1)):
                for period, index in ((current_period, col), (previous_period, col + 2)):
                    metric = metric_for_period(
                        definitions[code], str(main[index]), detect_unit(page.text),
                        period, page.page_number, quote, Decimal("0.95"),
                    )
                    if metric is not None:
                        recovered[(code, period)] = metric
            if not recovered:
                continue
            merged = {
                (metric.definition.code, metric.period): metric for metric in metrics
            }
            merged.update(recovered)
            return list(merged.values())
    return metrics


def promote_legacy_business_totals(
    metrics: list[ExtractedMetric], pages: list[ParsedPage] | None = None,
) -> list[ExtractedMetric]:
    definitions = {definition.code: definition for definition in METRICS}
    existing = {
        (metric.definition.code, metric.period)
        for metric in metrics
        if metric.period is not None
    }
    net_profit_pages = {
        (metric.period, metric.source_page)
        for metric in metrics
        if metric.definition.code == "net_profit" and metric.period is not None
    }
    page_by_number = {page.page_number: page for page in pages or []}
    promoted: list[ExtractedMetric] = []
    relationships = (
        ("main_business_revenue", "operating_revenue"),
        ("main_business_cost", "operating_cost"),
    )
    for part_code, total_code in relationships:
        for metric in metrics:
            if (
                metric.definition.code != part_code
                or metric.period is None
                or (total_code, metric.period) in existing
                or (metric.period, metric.source_page) not in net_profit_pages
            ):
                continue
            source_page = page_by_number.get(metric.source_page)
            if source_page is not None:
                source_text = searchable_line(source_page.text)
                if "其他业务" in source_text or "利润表有关项目附注" in source_text:
                    continue
            promoted.append(
                replace(
                    metric,
                    definition=definitions[total_code],
                    confidence=min(metric.confidence, Decimal("0.92")),
                )
            )
    return metrics + promoted


def reconcile_business_total_conflicts(
    metrics: list[ExtractedMetric],
    pages: list[ParsedPage],
    current_period: str,
    previous_period: str,
) -> list[ExtractedMetric]:
    relationships = (
        ("main_business_revenue", "operating_revenue"),
        ("main_business_cost", "operating_cost"),
    )
    definitions = {definition.code: definition for definition in METRICS}
    replacements: dict[tuple[str, str], ExtractedMetric] = {}
    metric_values = {
        (metric.definition.code, metric.period): metric.normalized_value
        for metric in metrics
        if metric.period is not None
    }
    for part_code, total_code in relationships:
        definition = definitions[total_code]
        for period in (current_period, previous_period):
            part_value = metric_values.get((part_code, period))
            total_value = metric_values.get((total_code, period))
            if part_value is None or total_value is None:
                continue
            tolerance = max(abs(total_value) * Decimal("0.001"), Decimal("1"))
            if part_value - total_value <= tolerance:
                continue
            for page in pages:
                result = values_from_section_table_row(
                    definition, page, current_period, previous_period
                )
                if result is None:
                    continue
                values, quote = result
                alternatives = [
                    metric_for_period(
                        definition,
                        value,
                        detect_unit(page.text),
                        candidate_period,
                        page.page_number,
                        quote,
                        Decimal("0.92"),
                    )
                    for value, candidate_period in zip(
                        values[:2], (current_period, previous_period), strict=False
                    )
                ]
                alternative = next(
                    (
                        candidate
                        for candidate in alternatives
                        if candidate is not None and candidate.period == period
                    ),
                    None,
                )
                if alternative is not None and alternative.normalized_value >= part_value:
                    replacements[(total_code, period)] = alternative
                    break
    return [
        replacements.get((metric.definition.code, metric.period), metric)
        if metric.period is not None
        else metric
        for metric in metrics
    ]


def apply_filename_period(
    metrics: list[ExtractedMetric], filename: str
) -> list[ExtractedMetric]:
    period = filename_period(filename)
    if period is None:
        return metrics
    return [replace(metric, period=metric.period or period) for metric in metrics]


def validate_balance(metrics: list[ExtractedMetric]) -> list[str]:
    errors: list[str] = []
    periods = sorted({metric.period for metric in metrics if metric.period is not None})
    for period in periods:
        values = {
            metric.definition.code: metric.normalized_value
            for metric in metrics
            if metric.period == period
        }
        required = ("total_assets", "total_liabilities", "owners_equity")
        if not all(code in values for code in required):
            continue
        difference = values["total_assets"] - values["total_liabilities"] - values["owners_equity"]
        tolerance = max(abs(values["total_assets"]) * Decimal("0.001"), Decimal("1"))
        if abs(difference) > tolerance:
            errors.append(f"{period}年资产负债表不平衡，资产与负债加权益相差 {difference}")
    return errors


def validate_statement_reconciliations(
    metrics: list[ExtractedMetric], pages: list[ParsedPage]
) -> list[str]:
    errors: list[str] = []
    page_by_number = {page.page_number: page for page in pages}
    periods = sorted({metric.period for metric in metrics if metric.period is not None})
    if not periods:
        return errors
    report_period = periods[-1]
    previous_period = str(int(report_period) - 1)
    exchange_definition = MetricDefinition(
        "exchange_effect", "汇率变动对现金及现金等价物的影响",
        ("汇率变动对现金及现金等价物的影响", "汇率变动对现金的影响"), "现金流量表",
    )
    required = (
        "operating_cash_flow", "investing_cash_flow", "financing_cash_flow", "cash_increase"
    )
    for period in periods:
        by_code = {
            metric.definition.code: metric
            for metric in metrics if metric.period == period
        }
        if not all(code in by_code for code in required):
            continue
        cash_metrics = [by_code[code] for code in required]
        if len({metric.source_page for metric in cash_metrics}) != 1:
            continue
        page = page_by_number.get(cash_metrics[0].source_page)
        if page is None:
            continue
        exchange = Decimal(0)
        if "汇率变动" in page.text:
            try:
                exchange_metrics = find_metric_periods_in_page(
                    exchange_definition, page, report_period, previous_period
                )
            except ValueError:
                errors.append(f"{period}年现金流量表汇率变动金额的年度列无法确认")
                continue
            exchange_by_period = {
                metric.period: metric.normalized_value for metric in exchange_metrics
            }
            if period not in exchange_by_period:
                exchange_rows = [
                    row for table in re.findall(
                        r"<table[^>]*>.*?</table>", page.text,
                        flags=re.IGNORECASE | re.DOTALL,
                    ) for row in html_table_rows(table)
                    if any("汇率变动对现金" in cell for cell in row)
                ]
                if not exchange_rows or not any(
                    all(cell.strip() in ("", "-", "—", "－") for cell in row[index + 1:])
                    for row in exchange_rows
                    for index, cell in enumerate(row) if "汇率变动对现金" in cell
                ):
                    errors.append(f"{period}年现金流量表汇率变动金额无法确认")
                    continue
            else:
                exchange = exchange_by_period[period]
        difference = (
            sum((by_code[code].normalized_value for code in required[:3]), Decimal(0))
            + exchange - by_code["cash_increase"].normalized_value
        )
        if abs(difference) > Decimal("1"):
            errors.append(f"{period}年现金流量表不平衡，活动净额及汇率影响与现金净增加额相差 {difference} 元")
    return errors


def validate_metric_relationships(
    metrics: list[ExtractedMetric],
    approved_excesses: dict[tuple[str, str], tuple[Decimal, Decimal]] | None = None,
) -> list[str]:
    errors: list[str] = []
    relationships = (
        ("main_business_revenue", "operating_revenue", "主营业务收入", "营业收入"),
        ("main_business_cost", "operating_cost", "主营业务成本", "营业成本"),
    )
    periods = sorted({metric.period for metric in metrics if metric.period is not None})
    for period in periods:
        values = {
            metric.definition.code: metric.normalized_value
            for metric in metrics
            if metric.period == period
        }
        if (
            "cash" in values
            and "total_assets" in values
            and values["cash"] > values["total_assets"] + Decimal("1")
        ):
            errors.append(f"{period}年货币资金大于资产总额")
        for part_code, total_code, part_label, total_label in relationships:
            if part_code not in values or total_code not in values:
                continue
            tolerance = max(abs(values[total_code]) * Decimal("0.001"), Decimal("1"))
            if values[part_code] - values[total_code] > tolerance:
                approved_pair = (approved_excesses or {}).get((period, part_code))
                if approved_pair != (values[part_code], values[total_code]):
                    errors.append(f"{period}年{part_label}大于{total_label}")
        for main_code, other_code, total_code, total_label in (
            ("main_business_revenue", "other_business_revenue", "operating_revenue", "营业收入"),
            ("main_business_cost", "other_business_cost", "operating_cost", "营业成本"),
        ):
            if not all(code in values for code in (main_code, other_code, total_code)):
                continue
            difference = values[main_code] + values[other_code] - values[total_code]
            # Amounts in the source are reported to cents. Do not let a one-cent
            # discrepancy pass as a valid split; only sub-cent rounding noise is
            # tolerated here.
            if abs(difference) > Decimal("0.005"):
                errors.append(f"{period}年主营及其他业务分类合计与{total_label}相差 {difference} 元")
        source_pages = {
            metric.definition.code: metric.source_page
            for metric in metrics
            if metric.period == period and metric.source_page is not None
        }
        if (
            "total_assets" in source_pages
            and "owners_equity" in source_pages
            and source_pages["owners_equity"] < source_pages["total_assets"]
        ):
            errors.append(f"{period}年所有者权益来源页早于资产总额来源页")
        if all(code in values for code in ("total_profit", "income_tax_expense", "net_profit")):
            expected_net_profit = values["total_profit"] - values["income_tax_expense"]
            difference = values["net_profit"] - expected_net_profit
            tolerance = max(abs(expected_net_profit) * Decimal("0.001"), Decimal("1"))
            if abs(difference) > tolerance:
                errors.append(f"{period}年净利润与利润总额减所得税费用不一致")
    return errors
