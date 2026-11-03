import re
from io import BytesIO

from pypdf import PdfReader
from pypdf.errors import PdfReadError

from app.services.pdf_parser import PdfParsingError


def company_name_for_matching(name: str) -> str:
    return re.sub(r"^[A-Za-z]?\d+(?:\.\d+)*[\s、._-]*", "", name).strip()


def match_company_from_pdf(content: bytes, companies: list[tuple[int, str]]) -> int:
    try:
        reader = PdfReader(BytesIO(content))
        cover_text = "".join((page.extract_text() or "") for page in reader.pages[:3])
    except (PdfReadError, OSError, ValueError) as exc:
        raise PdfParsingError(f"无法读取PDF首页以确认企业归属：{exc}") from exc
    cover_text = re.sub(r"\s+", "", cover_text)
    matches = [
        company_id
        for company_id, name in companies
        if (normalized := company_name_for_matching(name))
        and normalized.endswith(("有限公司", "股份有限公司"))
        and normalized in cover_text
    ]
    if len(matches) != 1:
        reason = "未识别到已建档企业" if not matches else "识别到多个可能的企业"
        raise PdfParsingError(
            f"{reason}，无法安全自动归属。请按企业上传或使用企业文件夹批量导入；"
            "扫描件首页若没有可读文字，也需先明确企业归属。"
        )
    return matches[0]
