from app.services.financial_extractor import METRICS
from app.services.financial_indicators import DERIVED_DEFINITIONS


# Historical reviews added fields beyond the extractor definitions. Their
# display names are fixed by field code, independent of source wording.
ADDITIONAL_FINANCE_LABELS: dict[str, str] = {
    "accounts_receivable_financing": "应收款项融资",
    "acquisitions_cash_paid": "取得子公司及其他营业单位支付的现金净额",
    "advances_from_customers": "预收账款",
    "advertising_expenses": "广告费",
    "asset_disposal_gain": "资产处置收益",
    "bank_fees": "手续费",
    "biological_assets": "生物资产",
    "borrowings_cash_received": "取得借款收到的现金",
    "borrowings_received": "取得借款收到的现金",
    "business_entertainment_expenses": "业务招待费",
    "capital_expenditure_cash": "购建长期资产支付的现金",
    "cash_disposal_long_term_assets": "处置长期资产收回的现金净额",
    "cash_disposal_subsidiaries": "处置子公司及其他营业单位收到的现金净额",
    "cash_dividends_receivable": "应收股利",
    "cash_increase_note": "现金等价物变动（现金流附注）",
    "cash_investment_recovery": "收回投资收到的现金",
    "cash_paid_for_goods": "购买商品、接受劳务支付的现金",
    "cash_paid_for_subsidiaries": "取得子公司及其他营业单位支付的现金净额",
    "cash_paid_to_employees": "支付给职工以及为职工支付的现金",
    "cash_received_from_customers": "销售商品、提供劳务收到的现金",
    "current_maturities_of_noncurrent_liabilities": "一年内到期的非流动负债",
    "debt_investment": "债权投资",
    "deferred_expenses": "待摊费用",
    "derivative_financial_assets": "衍生金融资产",
    "development_expenditure": "开发支出",
    "dividends_interest_cash_paid": "分配股利、利润或偿付利息支付的现金",
    "dividends_payable": "应付股利",
    "dividends_receivable": "应收股利",
    "engineering_materials": "工程物资",
    "estimated_liabilities": "预计负债",
    "exchange_gain_loss": "汇兑损益",
    "fixed_asset_disposal": "固定资产清理",
    "government_grant_asset_related": "与资产相关的政府补助",
    "government_grant_income_related": "与收益相关的政府补助",
    "government_grants": "政府补助",
    "indirect_operating_cash_flow": "间接法经营活动现金流量净额（补充资料）",
    "interest_payable": "应付利息",
    "interest_receivable": "应收利息",
    "investment_cash_paid": "投资支付的现金",
    "investment_income_dividends": "应收子公司股息、红利",
    "investment_income_equity_method": "收回投资确认的投资收益",
    "investment_income_received": "取得投资收益收到的现金",
    "investment_income_wealth_products": "理财产品赎回收益",
    "investment_recovery_cash": "收回投资收到的现金",
    "investment_return_cash_received": "取得投资收益收到的现金",
    "investor_cash_received": "吸收投资收到的现金",
    "long_term_accounts_payable": "长期应付款",
    "long_term_bond_investments": "长期债券投资",
    "long_term_debt_investments": "长期债权投资",
    "long_term_equity_investment": "长期股权投资",
    "long_term_prepaid_expenses": "长期待摊费用",
    "long_term_receivables": "长期应收款",
    "non_operating_expenses": "营业外支出",
    "non_operating_government_grants": "营业外收入中的政府补助",
    "non_operating_income": "营业外收入",
    "noncurrent_liabilities": "非流动负债合计",
    "other_comprehensive_income": "其他综合收益",
    "other_equity_investments": "其他权益工具投资",
    "other_financial_expenses": "其他财务费用",
    "other_financing_cash_paid": "支付其他与筹资活动有关的现金",
    "other_financing_cash_received": "收到其他与筹资活动有关的现金",
    "other_investing_cash_paid": "支付其他与投资活动有关的现金",
    "other_investing_cash_received": "收到其他与投资活动有关的现金",
    "other_noncurrent_liabilities": "其他非流动负债",
    "other_operating_cash_paid": "支付其他与经营活动有关的现金",
    "other_operating_cash_received": "收到其他与经营活动有关的现金",
    "productive_biological_assets": "生产性生物资产",
    "profit_payable": "应付利润或股利",
    "project_materials": "工程物资",
    "rd_to_main_business_revenue": "研发费用占主营业务收入比例",
    "receivables": "应收款项",
    "repayment_borrowings_cash": "偿还借款或债务支付的现金",
    "tax_refund_cash_received": "收到的税费返还",
    "tax_refund_received": "收到的税费返还",
    "treasury_stock": "库存股（权益抵减项）",
}

FINANCE_LABELS: dict[str, str] = {
    **{definition.code: definition.label for definition in METRICS},
    **{code: definition.label for code, definition in DERIVED_DEFINITIONS.items()},
    **ADDITIONAL_FINANCE_LABELS,
}


def finance_display_label(field_code: str, source_label: str) -> str:
    return FINANCE_LABELS.get(field_code, source_label)


FINANCE_WIDE_FIELD_ORDER: tuple[str, ...] = (
    "operating_revenue",
    "main_business_revenue",
    "operating_cost",
    "main_business_cost",
    "other_business_revenue",
    "other_business_cost",
    "total_profit",
    "net_profit",
    "rd_expenses",
    "selling_expenses",
    "administrative_expenses",
    "total_assets",
    "notes_receivable",
    "receivables_financing",
    "total_liabilities",
    "current_liabilities",
    "long_term_liabilities",
    "notes_payable",
    "other_payables",
    "dividend_payable",
    "owners_equity",
    "operating_revenue_yoy",
    "main_business_revenue_yoy",
    "net_profit_yoy",
    "operating_revenue_cagr",
    "main_business_revenue_cagr",
    "rd_to_revenue",
    "rd_to_main_revenue",
    "asset_liability_ratio",
    "net_margin",
)

FINANCE_WIDE_FIELD_INDEX: dict[str, int] = {
    code: index for index, code in enumerate(FINANCE_WIDE_FIELD_ORDER)
}

TAX_FIELD_INDEX: dict[str, int] = {
    "vat_payable_cumulative": 0,
    "corporate_income_tax_payable": 1,
    "corporate_income_tax_prepayment_due": 2,
    "tax_payment_net_total": 3,
}


def finance_wide_field_order(field_code: str) -> tuple[int, int | str]:
    index = FINANCE_WIDE_FIELD_INDEX.get(field_code)
    if index is not None:
        return 0, index
    tax_index = TAX_FIELD_INDEX.get(field_code)
    if tax_index is not None:
        return 1, tax_index
    return 2, field_code
