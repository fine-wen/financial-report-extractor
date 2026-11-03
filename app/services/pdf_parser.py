from dataclasses import dataclass
from pathlib import Path

from pypdf import PdfReader, PdfWriter
from pypdf.errors import PdfReadError


class PdfParsingError(RuntimeError):
    pass


class ScannedPdfDetectedError(PdfParsingError):
    pass


@dataclass(frozen=True)
class ParsedPage:
    page_number: int
    text: str


def extract_pdf_pages(path: Path) -> list[ParsedPage]:
    try:
        reader = PdfReader(path)
    except (PdfReadError, OSError) as exc:
        raise PdfParsingError(f"无法读取 PDF：{path.name}；原因：{exc}") from exc
    pages = [
        ParsedPage(page_number=index + 1, text=(page.extract_text() or "").strip())
        for index, page in enumerate(reader.pages)
    ]
    total_text = sum(len(page.text) for page in pages)
    if total_text < 30:
        raise ScannedPdfDetectedError(
            f"PDF 没有足够的可提取文字：{path.name}。该文件已判定为扫描件。"
        )
    return pages


def has_predominantly_landscape_pages(path: Path) -> bool:
    try:
        reader = PdfReader(path)
    except (PdfReadError, OSError) as exc:
        raise PdfParsingError(f"无法检查 PDF 页面方向：{path.name}；原因：{exc}") from exc
    if len(reader.pages) == 0:
        return False
    landscape_page_count = sum(
        float(page.mediabox.width) > float(page.mediabox.height) for page in reader.pages
    )
    return landscape_page_count >= 2 and landscape_page_count / len(reader.pages) >= 0.8


def write_clockwise_rotated_pdf(source_path: Path, output_path: Path) -> None:
    try:
        reader = PdfReader(source_path)
        writer = PdfWriter()
        for page in reader.pages:
            rotated_page = (
                page.rotate(90)
                if float(page.mediabox.width) > float(page.mediabox.height)
                else page
            )
            writer.add_page(rotated_page)
        with output_path.open("wb") as output:
            writer.write(output)
    except (PdfReadError, OSError) as exc:
        raise PdfParsingError(
            f"无法生成方向校正后的 PDF：{source_path.name}；原因：{exc}"
        ) from exc
