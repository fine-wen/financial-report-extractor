"""Public regressions use constructed data, without customer report excerpts."""

from decimal import Decimal

import pytest

from app.services.financial_extractor import (
    ParentCompanyPagesUnavailableError,
    extract_financial_metrics,
    select_parent_company_pages,
    validate_metric_completeness,
)
from app.services.metric_catalog import finance_display_label
from app.services.pdf_parser import ParsedPage


def income_table(title: str, revenue: str) -> str:
    return (
        f"{title} 2025年度 <table>"
        "<tr><td>项目</td><td>本期金额</td><td>上期金额</td></tr>"
        f"<tr><td>营业收入</td><td>{revenue}</td><td>900.00</td></tr>"
        "<tr><td>营业成本</td><td>600.00</td><td>500.00</td></tr>"
        "<tr><td>利润总额</td><td>300.00</td><td>250.00</td></tr>"
        "<tr><td>净利润</td><td>240.00</td><td>200.00</td></tr></table>"
    )


def test_parent_statement_without_parent_prefix_excludes_consolidated_values():
    pages = [
        ParsedPage(6, income_table("合并利润表", "5000.00")),
        ParsedPage(7, income_table("利润表", "1000.00")),
    ]
    selected = select_parent_company_pages(pages)
    assert [page.page_number for page in selected] == [7]
    values = {
        (metric.definition.code, metric.period): metric
        for metric in extract_financial_metrics(selected, "2025")
    }
    revenue = values[("operating_revenue", "2025")]
    assert revenue.normalized_value == Decimal("1000.00")
    assert revenue.source_page == 7
    assert "1000.00" in revenue.source_quote


def test_consolidated_only_report_does_not_fall_back_to_consolidated_values():
    with pytest.raises(ParentCompanyPagesUnavailableError):
        select_parent_company_pages([ParsedPage(6, income_table("合并利润表", "5000.00"))])


def test_independent_statement_keeps_original_page():
    pages = [ParsedPage(3, income_table("利润表", "1000.00"))]
    assert select_parent_company_pages(pages) == pages


@pytest.mark.parametrize("code,old_label,expected", [
    ("operating_revenue", "operating_revenue", "营业收入"),
    ("net_profit", "net_profit", "净利润"),
    ("main_business_revenue_yoy", "主營業務收入同比增長率", "主营业务收入同比增长率"),
    ("noncurrent_assets", "非流動資產合計", "非流动资产合计"),
])
def test_metric_names_use_simplified_chinese(code, old_label, expected):
    assert finance_display_label(code, old_label) == expected


def test_parent_notes_are_retained_from_their_substantive_start():
    notes = (
        "母公司财务报表附注 营业收入和营业成本 <table>"
        '<tr><td rowspan="2">项目</td><td colspan="2">本期发生额</td>'
        '<td colspan="2">上期发生额</td></tr>'
        '<tr><td>营业收入</td><td>营业成本</td><td>营业收入</td><td>营业成本</td></tr>'
        '<tr><td>主营业务</td><td>800.00</td><td>500.00</td><td>700.00</td><td>400.00</td></tr>'
        '</table>'
    )
    pages = [
        ParsedPage(2, income_table("合并利润表", "5000.00")),
        ParsedPage(3, income_table("母公司利润表", "1000.00")),
        ParsedPage(5, "财务报表附注 公司基本情况 合并报表附注"),
        ParsedPage(8, "母公司财务报表附注 公司基本情况"),
        ParsedPage(43, notes),
    ]
    selected = select_parent_company_pages(pages)
    assert [page.page_number for page in selected] == [3, 8, 43]
    values = {
        (metric.definition.code, metric.period): (metric.normalized_value, metric.source_page)
        for metric in extract_financial_metrics(selected, "2025")
    }
    assert values[("main_business_revenue", "2025")] == (Decimal("800"), 43)
    assert values[("main_business_cost", "2025")] == (Decimal("500"), 43)
    assert values[("main_business_revenue", "2024")] == (Decimal("700"), 43)
    assert values[("main_business_cost", "2024")] == (Decimal("400"), 43)


def test_duplicated_equity_word_is_normalized_without_changing_source_quote():
    page = ParsedPage(7, '资产负债表（续） 2025年12月31日 <table>'
        '<tr><td>项目</td><td>附注</td><td>期末余额</td><td>上年年末余额</td></tr>'
        '<tr><td>负债合计</td><td></td><td>40.00</td><td>30.00</td></tr>'
        '<tr><td>所有者权益权益合计</td><td></td><td>60.00</td><td>50.00</td></tr>'
        '<tr><td>负债和所有者权益总计</td><td></td><td>100.00</td><td>80.00</td></tr></table>')
    metrics = extract_financial_metrics([page], "2025")
    equity = next(metric for metric in metrics
                  if metric.definition.code == "owners_equity" and metric.period == "2025")
    assert equity.normalized_value == Decimal("60")
    assert equity.source_page == 7
    assert "所有者权益权益合计" in equity.source_quote
    assert "缺少所有者权益" not in validate_metric_completeness(metrics)


def test_adding_notes_does_not_hide_a_cash_statement_with_missing_ocr_title():
    cash_page = ParsedPage(5, '2025年度 单位：元 <table>'
        '<tr><td>项目</td><td>本期金额</td><td>上期金额</td></tr>'
        '<tr><td>经营活动产生的现金流量净额</td><td>100.00</td><td>90.00</td></tr>'
        '<tr><td>筹资活动产生的现金流量净额</td><td>20.00</td><td>10.00</td></tr>'
        '<tr><td>期末现金及现金等价物余额</td><td>350.00</td><td>250.00</td></tr></table>')
    notes = [ParsedPage(8, '母公司财务报表附注 公司基本情况'),
             ParsedPage(43, '现金流量表补充资料 <table><tr><td>无关说明</td><td>1.00</td></tr></table>')]

    def cash_values(pages):
        return {(m.definition.code, m.period): (m.normalized_value, m.source_page)
                for m in extract_financial_metrics(pages, '2025')
                if m.definition.category == '现金流量表'}

    original = cash_values([cash_page])
    assert original[("operating_cash_flow", "2025")] == (Decimal("100"), 5)
    assert cash_values([cash_page, *notes]) == original
