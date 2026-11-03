import hashlib
from pathlib import Path


class InvalidUploadError(ValueError):
    pass


def validate_pdf(filename: str | None, content: bytes, max_upload_mb: int) -> str:
    if filename is None or filename.strip() == "":
        raise InvalidUploadError("上传文件缺少文件名")
    if Path(filename).suffix.lower() != ".pdf":
        raise InvalidUploadError(f"第一版只支持 PDF 文件，收到的文件是：{filename}")
    if len(content) == 0:
        raise InvalidUploadError(f"文件内容为空：{filename}")
    limit_bytes = max_upload_mb * 1024 * 1024
    if len(content) > limit_bytes:
        raise InvalidUploadError(
            f"文件超过 {max_upload_mb}MB 限制：{filename}，实际 {len(content) / 1024 / 1024:.1f}MB"
        )
    if not content.startswith(b"%PDF"):
        raise InvalidUploadError(f"文件扩展名是 PDF，但内容不是有效 PDF：{filename}")
    return filename


def sha256_bytes(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def store_document(storage_dir: Path, company_id: int, digest: str, filename: str, content: bytes) -> Path:
    company_dir = storage_dir / str(company_id)
    company_dir.mkdir(parents=True, exist_ok=True)
    safe_name = Path(filename).name
    target = company_dir / f"{digest[:16]}_{safe_name}"
    target.write_bytes(content)
    return target
