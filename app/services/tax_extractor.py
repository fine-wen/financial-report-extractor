import re
from calendar import monthrange
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from hashlib import sha256

from app.services.financial_extractor import (
    ExtractedMetric, MetricDefinition, has_core_statement_text, html_table_rows,
    normalize_number, searchable_line,
)
from app.services.pdf_parser import ParsedPage

VAT_RETURN = "vat_return"
CORPORATE_INCOME_TAX_RETURN = "corporate_income_tax_return"
CORPORATE_INCOME_TAX_PREPAYMENT = "corporate_income_tax_prepayment"
TAX_PAYMENT_CERTIFICATE = "tax_payment_certificate"
TAX_DOCUMENT_TYPES = frozenset({
    VAT_RETURN, CORPORATE_INCOME_TAX_RETURN,
    CORPORATE_INCOME_TAX_PREPAYMENT, TAX_PAYMENT_CERTIFICATE,
})

VAT_PAYABLE_CUMULATIVE = MetricDefinition(
    "vat_payable_cumulative", "增值税应纳税额合计（截至申报期）",
    ("应纳税额合计",), "增值税申报表",
)
CORPORATE_INCOME_TAX_PAYABLE = MetricDefinition(
    "corporate_income_tax_payable", "企业所得税年度实际应纳所得税额",
    ("实际应纳所得税额",), "企业所得税年度申报表",
)
CORPORATE_INCOME_TAX_PREPAYMENT_DUE = MetricDefinition(
    "corporate_income_tax_prepayment_due", "企业所得税本期实际应补（退）所得税额",
    ("实际应补（退）所得税额",), "企业所得税预缴申报表",
)
DECIMAL_AMOUNT_PATTERN = re.compile(r"[-－−（(]?[\d,，]+\.\d{2}[）)]?")
DATE_PATTERN = re.compile(r"(20\d{2})\s*(?:年|[-./])\s*(\d{1,2})\s*(?:月|[-./])\s*(\d{1,2})")
CERTIFICATE_ROW_PATTERN = re.compile(
    r"(?P<start>20\d{2}-\d{2}-\d{2})\s*至\s*"
    r"(?P<end>20\d{2}-\d{2}-\d{2})\s+"
    r"(?P<paid>20\d{2}-\d{2}-\d{2})\s+¥\s*(?P<amount>-?[\d,]+\.\d{2})"
)
CERTIFICATE_PERIOD_PATTERN = re.compile(
    r"20\d{2}-\d{2}-\d{2}\s*至\s*20\d{2}-\d{2}-\d{2}"
)


@dataclass(frozen=True)
class CertificateRow:
    tax_name: str
    start: str
    end: str
    paid_date: str
    raw_amount: str
    page: ParsedPage
    source_quote: str


def taxpayer_matches_company(pages: list[ParsedPage], company_name: str) -> bool:
    normalized_name = re.sub(r"\s+", "", company_name)
    taxpayer_pattern = re.compile(
        r"纳税人名称[:：]?(?:（公章）)?" + re.escape(normalized_name)
        + r"(?=纳税人识别号|金额单位|法定代表人|$)"
    )
    return any(
        taxpayer_pattern.search(re.sub(r"\s+", "", line)) is not None
        for page in pages[:3] for line in page.text.splitlines()
        if "纳税人名称" in line
    )


def is_tax_return_page(page: ParsedPage) -> bool:
    text = searchable_line(page.text)
    return any(title in text for title in (
        "增值税及附加税费申报表", "企业所得税年度纳税申报表",
        "企业所得税月（季）度预缴纳税申报表", "税收完税证明",
    ))


def detect_tax_document_type(pages: list[ParsedPage]) -> str | None:
    if not pages or has_core_statement_text(pages):
        return None
    first = searchable_line(pages[0].text)
    leading = "\n".join(searchable_line(page.text) for page in pages[:3])
    if "审计报告" in first or "审计意见" in first:
        return None
    if "税收完税证明" in first:
        return TAX_PAYMENT_CERTIFICATE
    if "企业所得税月（季）度预缴纳税申报表" in first:
        return CORPORATE_INCOME_TAX_PREPAYMENT
    if "企业所得税年度纳税申报表" in first:
        return CORPORATE_INCOME_TAX_RETURN
    if "增值税及附加税费申报表" in first:
        return VAT_RETURN
    if "a100000企业所得税年度纳税申报主表" in leading:
        return CORPORATE_INCOME_TAX_RETURN
    if all(token in leading for token in (
        "实际应纳所得税额", "应纳税所得额", "本年累计预缴所得税额",
    )):
        return CORPORATE_INCOME_TAX_RETURN
    return None


def tax_period_range(pages: list[ParsedPage]) -> tuple[str, str]:
    for page in pages[:3]:
        for line in page.text.splitlines():
            if "税款所属" not in searchable_line(line):
                continue
            dates = DATE_PATTERN.findall(line)
            if len(dates) >= 2:
                normalized = [
                    date(int(year), int(month), int(day)).isoformat()
                    for year, month, day in dates[:2]
                ]
                return normalized[0], normalized[1]
    raise ValueError("无法从税款所属期间判断申报期")


def certificate_rows(pages: list[ParsedPage]) -> list[CertificateRow]:
    rows: list[CertificateRow] = []
    for page in pages:
        lines = page.text.splitlines()
        for index, line in enumerate(lines):
            if "金额合计" in line:
                continue
            matches = list(CERTIFICATE_ROW_PATTERN.finditer(line))
            if not matches:
                continue
            if len(matches) != 1:
                raise ValueError("完税证明明细行无法逐行对应，已停止取数")
            match = matches[0]
            tax_name = line[:match.start()].strip()
            quote = line.strip()
            if index > 0:
                preceding = lines[index - 1].strip()
                if preceding.count("(") + preceding.count("（") > (
                    preceding.count(")") + preceding.count("）")
                ):
                    tax_name = preceding + tax_name
                    quote = preceding + "\n" + quote
            if not tax_name or "税种" in tax_name:
                raise ValueError("完税证明明细税种无法确认，已停止取数")
            rows.append(CertificateRow(
                tax_name, match.group("start"), match.group("end"),
                match.group("paid"), match.group("amount"), page, quote,
            ))
    if not rows:
        raise ValueError("完税证明未找到带所属期、入库日期和实缴金额的明细")
    for row in rows:
        if date.fromisoformat(row.start) > date.fromisoformat(row.end):
            raise ValueError("完税证明税款所属时期起止日期颠倒")
        date.fromisoformat(row.paid_date)
    detail_amount_count = sum(
        line.count("¥")
        for page in pages for line in page.text.splitlines()
        if "金额合计" not in line
    )
    period_count = sum(
        len(CERTIFICATE_PERIOD_PATTERN.findall(page.text)) for page in pages
    )
    if detail_amount_count != len(rows) or period_count != len(rows):
        raise ValueError("完税证明有金额明细无法对应所属期，已停止取数")
    return rows


def detect_tax_period(document_type: str, pages: list[ParsedPage], filename: str) -> str:
    try:
        start, end = tax_period_range(pages)
    except ValueError as exc:
        raise ValueError(f"无法判断税务申报所属期间：{filename}") from exc
    if start > end or start[:4] != end[:4]:
        raise ValueError(f"税务申报所属期间不完整或跨年度：{filename}")
    if document_type == CORPORATE_INCOME_TAX_RETURN:
        if start[5:] != "01-01" or end[5:] != "12-31":
            raise ValueError(f"企业所得税年报不是完整年度：{filename}")
        return start[:4]
    if document_type == CORPORATE_INCOME_TAX_PREPAYMENT:
        if start[:7] == end[:7]:
            return end[:7]
        quarter = (int(end[5:7]) - 1) // 3 + 1
        quarter_start = f"{end[:4]}-{3 * quarter - 2:02d}-01"
        last_month = 3 * quarter
        quarter_end = f"{end[:4]}-{last_month:02d}-{monthrange(int(end[:4]), last_month)[1]}"
        if start == quarter_start and end == quarter_end:
            return f"{end[:4]}-Q{quarter}"
        return f"{start}至{end}"
    return end[:7] if start[:7] == end[:7] else f"{start}至{end}"


def single_cell_amount(cell: str) -> str | None:
    values = DECIMAL_AMOUNT_PATTERN.findall(cell)
    return values[0] if len(values) == 1 else None


def metric_from_value(
    definition: MetricDefinition, raw_value: str, period: str,
    page: ParsedPage, quote: str, confidence: Decimal,
) -> ExtractedMetric:
    return ExtractedMetric(
        definition=definition, value_text=raw_value,
        normalized_value=normalize_number(raw_value), unit="元",
        period=period, source_page=page.page_number,
        source_quote=quote[:500], confidence=confidence,
    )


def extract_vat_payable(pages: list[ParsedPage], period: str) -> ExtractedMetric | None:
    target = searchable_line("应纳税额合计")
    for page in pages:
        page_text = searchable_line(page.text)
        title_line = next((line.strip() for line in page.text.splitlines() if line.strip()), "")
        if (
            not searchable_line(title_line).startswith("增值税及附加税费申报表")
            or "附列资料" in title_line
            or target not in page_text
            or not all(label in page_text for label in (
                "一般项目", "本月数", "本年累计", "即征即退项目",
            ))
        ):
            continue
        for cells in html_table_rows(page.text):
            label_index = next(
                (index for index, cell in enumerate(cells) if target in searchable_line(cell)), None
            )
            if label_index is None or len(cells) - label_index < 6:
                continue
            if not any(re.search(r"\b24\b", cell) for cell in cells[label_index + 1:-4]):
                continue
            raw_value = single_cell_amount(cells[-4:][1])
            if raw_value is not None:
                return metric_from_value(
                    VAT_PAYABLE_CUMULATIVE, raw_value, period, page,
                    " | ".join(cells), Decimal("0.96"),
                )
        for line in page.text.splitlines():
            if target not in searchable_line(line):
                continue
            values = DECIMAL_AMOUNT_PATTERN.findall(line)
            if len(values) == 4 and "24=" in line:
                return metric_from_value(
                    VAT_PAYABLE_CUMULATIVE, values[1], period, page,
                    line, Decimal("0.90"),
                )
    return None


def extract_corporate_income_tax_payable(
    pages: list[ParsedPage], period: str,
) -> ExtractedMetric | None:
    target = searchable_line("实际应纳所得税额")
    for page in pages:
        if "A100000" not in page.text or target not in searchable_line(page.text):
            continue
        for cells in html_table_rows(page.text):
            if not any(target in searchable_line(cell) for cell in cells):
                continue
            if not re.search(r"\b36\b", cells[0]):
                continue
            raw_value = single_cell_amount(cells[-1])
            if raw_value is not None:
                return metric_from_value(
                    CORPORATE_INCOME_TAX_PAYABLE, raw_value, period, page,
                    " | ".join(cells), Decimal("0.96"),
                )
        for line in page.text.splitlines():
            if target not in searchable_line(line) or not re.match(r"\s*36\s", line):
                continue
            values = DECIMAL_AMOUNT_PATTERN.findall(line)
            if len(values) == 1:
                return metric_from_value(
                    CORPORATE_INCOME_TAX_PAYABLE, values[0], period, page,
                    line, Decimal("0.90"),
                )
    return None


def extract_corporate_income_tax_prepayment(
    pages: list[ParsedPage], period: str,
) -> ExtractedMetric | None:
    for page in pages:
        if "实际缴纳企业所得税计算" not in page.text:
            continue
        for line in page.text.splitlines():
            if not re.match(r"\s*40\s+.*实际应补[（(]退[）)]所得税额", line):
                continue
            values = DECIMAL_AMOUNT_PATTERN.findall(line)
            if len(values) == 1:
                return metric_from_value(
                    CORPORATE_INCOME_TAX_PREPAYMENT_DUE, values[0], period,
                    page, line, Decimal("0.90"),
                )
    return None


def extract_tax_payment_rows(pages: list[ParsedPage]) -> list[ExtractedMetric]:
    rows = certificate_rows(pages)
    totals: list[Decimal] = []
    for page in pages:
        for line in page.text.splitlines():
            if "金额合计" not in line:
                continue
            match = re.search(r"¥\s*(-?[\d,]+\.\d{2})", line)
            if match is not None:
                totals.append(Decimal(match.group(1).replace(",", "")))
    if len(totals) != 1:
        raise ValueError("完税证明金额合计无法唯一确认，已停止取数")
    if sum((normalize_number(row.raw_amount) for row in rows), Decimal("0")) != totals[0]:
        raise ValueError("完税证明明细金额与合计不一致，已停止取数")
    metrics: list[ExtractedMetric] = []
    for index, row in enumerate(rows, start=1):
        identity = "|".join((
            row.tax_name, row.start, row.end, row.paid_date, row.raw_amount,
        ))
        suffix = sha256(identity.encode("utf-8")).hexdigest()[:10]
        definition = MetricDefinition(
            f"tax_payment_line_{index:03d}_{suffix}",
            row.tax_name, (row.tax_name,), "税收完税证明",
        )
        metrics.append(metric_from_value(
            definition, row.raw_amount, f"{row.start}至{row.end}",
            row.page, row.source_quote, Decimal("0.96"),
        ))
    return metrics


def extract_tax_metrics(
    document_type: str, pages: list[ParsedPage], filename: str,
) -> list[ExtractedMetric]:
    if document_type == TAX_PAYMENT_CERTIFICATE:
        return extract_tax_payment_rows(pages)
    period = detect_tax_period(document_type, pages, filename)
    if not any(
        re.search(r"金额单位[:：]?(?:人民币)?元", searchable_line(page.text))
        for page in pages[:3]
    ):
        raise ValueError(f"无法确认税务申报表金额单位为元：{filename}")
    if document_type == VAT_RETURN:
        metric = extract_vat_payable(pages, period)
        label = VAT_PAYABLE_CUMULATIVE.label
    elif document_type == CORPORATE_INCOME_TAX_RETURN:
        metric = extract_corporate_income_tax_payable(pages, period)
        label = CORPORATE_INCOME_TAX_PAYABLE.label
    elif document_type == CORPORATE_INCOME_TAX_PREPAYMENT:
        metric = extract_corporate_income_tax_prepayment(pages, period)
        label = CORPORATE_INCOME_TAX_PREPAYMENT_DUE.label
    else:
        raise ValueError(f"不支持的税务报表类型：{document_type}")
    if metric is None:
        raise ValueError(f"已识别税务资料，但无法安全取到：{label}")
    return [metric]
