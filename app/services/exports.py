from io import BytesIO

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.worksheet.worksheet import Worksheet

from app.models import Company, ExtractedField
from app.services.metric_catalog import finance_display_label


STATUS_LABELS: dict[str, str] = {
    "pending": "待复核",
    "confirmed": "已确认",
    "corrected": "已修改确认",
    "missing": "已标记缺失",
}


def style_header(sheet: Worksheet) -> None:
    header_fill = PatternFill("solid", fgColor="1E3A5F")
    header_font = Font(color="FFFFFF", bold=True)
    for cell in sheet[1]:
        cell.fill = header_fill
        cell.font = header_font
        cell.alignment = Alignment(horizontal="center")


def build_financial_workbook(
    company: Company, fields: list[ExtractedField], sheet_title: str = "财务数据",
) -> bytes:
    workbook = Workbook()
    sheet = workbook.active
    if sheet is None:
        raise RuntimeError("创建 Excel 工作表失败")
    sheet.title = sheet_title
    headers = ["指标", "数值", "单位", "期间", "状态", "来源文件", "来源页码", "原文证据", "复核人"]
    sheet.append(headers)
    style_header(sheet)
    for field in fields:
        sheet.append(
            [
                finance_display_label(field.field_code, field.label),
                field.value_text,
                field.unit,
                field.period,
                field.status,
                field.document.filename,
                field.source_page,
                field.source_quote,
                field.reviewed_by,
            ]
        )
    widths = [22, 18, 10, 10, 12, 36, 10, 70, 14]
    if sheet_title == "税务数据":
        widths[3] = 26
    for index, width in enumerate(widths, start=1):
        sheet.column_dimensions[chr(64 + index)].width = width
    sheet.freeze_panes = "A2"
    sheet.auto_filter.ref = sheet.dimensions

    info = workbook.create_sheet("企业信息")
    info.append(["企业名称", company.name])
    info.append(["统一社会信用代码", company.unified_code])
    info.append(["所属行业", company.industry])
    info.append(["联系人", company.contact_name])
    info.column_dimensions["A"].width = 24
    info.column_dimensions["B"].width = 48

    output = BytesIO()
    workbook.save(output)
    return output.getvalue()


def build_metric_workbook(fields: list[ExtractedField]) -> bytes:
    workbook = Workbook()
    sheet = workbook.active
    if sheet is None:
        raise RuntimeError("创建 Excel 工作表失败")
    sheet.title = "指标汇总"
    sheet.append(
        [
            "企业名称",
            "统一社会信用代码",
            "指标",
            "数值",
            "单位",
            "年度",
            "复核状态",
            "来源文件",
            "来源页码",
            "原文证据",
            "复核人",
        ]
    )
    style_header(sheet)
    for field in fields:
        sheet.append(
            [
                field.company.name,
                field.company.unified_code,
                finance_display_label(field.field_code, field.label),
                field.normalized_value,
                field.unit,
                field.period,
                STATUS_LABELS.get(field.status, field.status),
                field.document.filename,
                field.source_page,
                field.source_quote,
                field.reviewed_by,
            ]
        )
    for cell in sheet["D"][1:]:
        cell.number_format = "#,##0.0000"
    widths = [30, 24, 24, 18, 10, 10, 14, 38, 10, 70, 14]
    for index, width in enumerate(widths, start=1):
        sheet.column_dimensions[chr(64 + index)].width = width
    sheet.freeze_panes = "A2"
    sheet.auto_filter.ref = sheet.dimensions
    output = BytesIO()
    workbook.save(output)
    return output.getvalue()
