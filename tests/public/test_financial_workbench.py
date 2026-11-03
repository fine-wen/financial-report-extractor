"""Public regressions use constructed data, without customer report excerpts."""

from decimal import Decimal

import pytest

from app.services.financial_extractor import (
    ParentCompanyPagesUnavailableError,
    extract_financial_metrics,
    select_parent_company_pages,
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
