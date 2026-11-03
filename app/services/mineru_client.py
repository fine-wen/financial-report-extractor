import json
import logging
from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path
from time import sleep
from zipfile import BadZipFile, ZipFile

import httpx

from app.services.pdf_parser import ParsedPage, PdfParsingError


logger = logging.getLogger(__name__)
CACHE_DIRECTORY_NAME = "_mineru_cache"


class MinerUError(PdfParsingError):
    pass


class MinerUUnavailableError(MinerUError):
    pass


class MinerUTaskNotFoundError(MinerUError):
    pass


@dataclass(frozen=True)
class MinerUTaskState:
    task_id: str
    status: str
    created_at: datetime
    started_at: datetime | None
    completed_at: datetime | None
    error: str | None
    queued_ahead: int | None


TaskUpdateCallback = Callable[[MinerUTaskState], None]


def is_mineru_transport_failure(error: BaseException) -> bool:
    current: BaseException | None = error
    visited: set[int] = set()
    while current is not None and id(current) not in visited:
        if isinstance(current, (MinerUUnavailableError, httpx.TransportError)):
            return True
        visited.add(id(current))
        current = current.__cause__ or current.__context__
    return False


def unavailable_error(message: str, error: BaseException) -> MinerUUnavailableError | None:
    if not is_mineru_transport_failure(error):
        return None
    return MinerUUnavailableError(f"{message}；最后一次错误：{error}")


def mineru_task_elapsed_seconds(task_state: MinerUTaskState, current_time: datetime) -> float:
    elapsed_from = task_state.started_at or task_state.created_at
    return max((current_time - elapsed_from).total_seconds(), 0.0)


def parse_optional_datetime(value: object, field_name: str, task_id: str) -> datetime | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise MinerUError(f"MinerU 任务字段格式无效：{field_name}；任务编号：{task_id}")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise MinerUError(
            f"MinerU 任务时间无法读取：{field_name}={value}；任务编号：{task_id}"
        ) from exc
    return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=timezone.utc)


def parse_task_state(payload: object) -> MinerUTaskState:
    if not isinstance(payload, dict):
        raise MinerUError("MinerU 任务状态格式无效")
    task_id = payload.get("task_id")
    task_status = payload.get("status")
    if not isinstance(task_id, str) or task_id.strip() == "":
        raise MinerUError("MinerU 任务状态缺少任务编号")
    if task_status not in ("pending", "processing", "completed", "failed"):
        raise MinerUError(f"MinerU 返回了未知任务状态：{task_status}；任务编号：{task_id}")
    created_at = parse_optional_datetime(payload.get("created_at"), "created_at", task_id)
    if created_at is None:
        raise MinerUError(f"MinerU 任务状态缺少提交时间；任务编号：{task_id}")
    error = payload.get("error")
    queued_ahead = payload.get("queued_ahead")
    if error is not None and not isinstance(error, str):
        raise MinerUError(f"MinerU 任务错误字段格式无效；任务编号：{task_id}")
    if queued_ahead is not None and not isinstance(queued_ahead, int):
        raise MinerUError(f"MinerU 排队信息格式无效；任务编号：{task_id}")
    return MinerUTaskState(
        task_id=task_id,
        status=task_status,
        created_at=created_at,
        started_at=parse_optional_datetime(payload.get("started_at"), "started_at", task_id),
        completed_at=parse_optional_datetime(payload.get("completed_at"), "completed_at", task_id),
        error=error,
        queued_ahead=queued_ahead,
    )


def extract_block_text(block: dict[str, object]) -> str:
    text_fields = ("text", "table_body", "equation")
    list_fields = ("img_caption", "image_caption", "table_caption")
    parts: list[str] = []
    for field in text_fields:
        value = block.get(field)
        if isinstance(value, str) and value.strip() != "":
            parts.append(value.strip())
    for field in list_fields:
        value = block.get(field)
        if isinstance(value, list):
            parts.extend(str(item).strip() for item in value if str(item).strip() != "")
    return "\n".join(parts)


def parse_mineru_zip(content: bytes, filename: str) -> list[ParsedPage]:
    try:
        with ZipFile(BytesIO(content)) as archive:
            content_files = sorted(
                name for name in archive.namelist() if name.lower().endswith("content_list.json")
            )
            if len(content_files) == 0:
                raise MinerUError(f"MinerU 返回结果中缺少逐页文字清单：{filename}")
            raw_content = archive.read(content_files[0])
    except BadZipFile as exc:
        raise MinerUError(f"MinerU 返回的结果不是有效压缩包：{filename}") from exc

    try:
        blocks = json.loads(raw_content.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise MinerUError(f"MinerU 返回的逐页文字清单无法读取：{filename}") from exc
    if not isinstance(blocks, list):
        raise MinerUError(f"MinerU 返回的逐页文字清单格式无效：{filename}")

    page_parts: defaultdict[int, list[str]] = defaultdict(list)
    for block in blocks:
        if not isinstance(block, dict):
            raise MinerUError(f"MinerU 返回的文字区块格式无效：{filename}")
        page_index = block.get("page_idx")
        if not isinstance(page_index, int) or page_index < 0:
            raise MinerUError(f"MinerU 返回的文字区块缺少有效页码：{filename}")
        block_text = extract_block_text(block)
        if block_text != "":
            page_parts[page_index].append(block_text)

    pages = [
        ParsedPage(page_number=page_index + 1, text="\n".join(page_parts[page_index]).strip())
        for page_index in sorted(page_parts)
    ]
    if sum(len(page.text) for page in pages) < 30:
        raise MinerUError(f"MinerU 已处理扫描件，但没有识别到足够文字：{filename}")
    return pages


def parse_mineru_content_list(content_list_path: Path, filename: str) -> list[ParsedPage]:
    try:
        blocks = json.loads(content_list_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise MinerUError(f"MinerU 缓存无法读取：{content_list_path}") from exc
    if not isinstance(blocks, list):
        raise MinerUError(f"MinerU 缓存格式无效：{content_list_path}")
    page_parts: defaultdict[int, list[str]] = defaultdict(list)
    for block in blocks:
        if not isinstance(block, dict):
            raise MinerUError(f"MinerU 缓存区块格式无效：{content_list_path}")
        page_index = block.get("page_idx")
        if not isinstance(page_index, int) or page_index < 0:
            raise MinerUError(f"MinerU 缓存缺少有效页码：{content_list_path}")
        block_text = extract_block_text(block)
        if block_text != "":
            page_parts[page_index].append(block_text)
    pages = [
        ParsedPage(page_number=index + 1, text="\n".join(page_parts[index]).strip())
        for index in sorted(page_parts)
    ]
    if sum(len(page.text) for page in pages) < 30:
        raise MinerUError(f"MinerU 缓存没有足够文字：{filename}")
    return pages


def mineru_cache_path(storage_dir: Path, sha256: str) -> Path:
    return storage_dir / CACHE_DIRECTORY_NAME / f"{sha256}.json"


def mineru_stage_cache_path(storage_dir: Path, sha256: str, stage: str) -> Path:
    if stage not in ("discovery", "detail", "hybrid"):
        raise MinerUError(f"未知的 MinerU 缓存阶段：{stage}")
    return storage_dir / CACHE_DIRECTORY_NAME / f"{sha256}.{stage}.json"


def read_mineru_cache(storage_dir: Path, sha256: str, filename: str) -> list[ParsedPage] | None:
    cache_path = mineru_cache_path(storage_dir, sha256)
    if not cache_path.exists():
        return None
    return parse_mineru_content_list(cache_path, filename)


def save_mineru_cache(storage_dir: Path, sha256: str, content: bytes, filename: str) -> list[ParsedPage]:
    pages = parse_mineru_zip(content, filename)
    try:
        with ZipFile(BytesIO(content)) as archive:
            content_files = sorted(
                name for name in archive.namelist() if name.lower().endswith("content_list.json")
            )
            raw_content = archive.read(content_files[0])
        cache_path = mineru_cache_path(storage_dir, sha256)
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        cache_path.write_bytes(raw_content)
    except (OSError, BadZipFile, IndexError) as exc:
        raise MinerUError(f"MinerU 结果缓存保存失败：{filename}") from exc
    return pages


def read_best_mineru_cache(
    storage_dir: Path, sha256: str, filename: str
) -> list[ParsedPage] | None:
    return read_mineru_cache(storage_dir, sha256, filename)


def clear_mineru_stage_caches(storage_dir: Path, sha256: str) -> None:
    for stage in ("discovery", "detail", "hybrid"):
        cache_path = mineru_stage_cache_path(storage_dir, sha256, stage)
        if cache_path.exists():
            cache_path.unlink()


def mineru_form_data() -> dict[str, str]:
    return {
        "lang_list": "ch",
        "parse_method": "auto",
        "formula_enable": "false",
        "table_enable": "true",
        "return_md": "false",
        "return_content_list": "true",
        "return_images": "false",
        "response_format_zip": "true",
        "return_original_file": "false",
    }


def mineru_upload_name(path: Path) -> str:
    # Windows strips trailing spaces and dots from directory components created by MinerU.
    return f"{path.stem.rstrip(' .')}{path.suffix}"


def submit_mineru_task(path: Path, api_url: str, timeout_seconds: int) -> MinerUTaskState:
    endpoint = f"{api_url.rstrip('/')}/tasks"
    with path.open("rb") as source:
        with httpx.Client(trust_env=False, follow_redirects=True) as client:
            response = client.post(
                endpoint,
                data=mineru_form_data(),
                files={"files": (mineru_upload_name(path), source, "application/pdf")},
                timeout=httpx.Timeout(timeout_seconds),
            )
    if response.status_code in (502, 503, 504):
        raise MinerUUnavailableError(
            f"MinerU 服务暂时不可用；请求地址：{endpoint}；状态码：{response.status_code}；"
            f"返回内容：{response.text[:1000]}"
        )
    if response.status_code != 202:
        raise MinerUError(
            f"MinerU 任务提交失败；请求地址：{endpoint}；状态码：{response.status_code}；"
            f"返回内容：{response.text[:1000]}"
        )
    return parse_task_state(response.json())


def get_mineru_task(api_url: str, task_id: str, timeout_seconds: int) -> MinerUTaskState:
    endpoint = f"{api_url.rstrip('/')}/tasks/{task_id}"
    with httpx.Client(trust_env=False, follow_redirects=True) as client:
        response = client.get(endpoint, timeout=httpx.Timeout(timeout_seconds))
    if response.status_code == 404:
        raise MinerUTaskNotFoundError(f"MinerU 中已找不到任务：{task_id}")
    if response.status_code in (502, 503, 504):
        raise MinerUUnavailableError(
            f"MinerU 服务暂时不可用；请求地址：{endpoint}；状态码：{response.status_code}；"
            f"返回内容：{response.text[:1000]}"
        )
    if response.status_code != 200:
        raise MinerUError(
            f"MinerU 任务状态读取失败；请求地址：{endpoint}；状态码：{response.status_code}；"
            f"返回内容：{response.text[:1000]}"
        )
    return parse_task_state(response.json())


def download_mineru_result(api_url: str, task_id: str, timeout_seconds: int) -> bytes:
    endpoint = f"{api_url.rstrip('/')}/tasks/{task_id}/result"
    with httpx.Client(trust_env=False, follow_redirects=True) as client:
        response = client.get(endpoint, timeout=httpx.Timeout(timeout_seconds))
    if response.status_code == 404:
        raise MinerUTaskNotFoundError(f"MinerU 中已找不到任务结果：{task_id}")
    if response.status_code in (502, 503, 504):
        raise MinerUUnavailableError(
            f"MinerU 服务暂时不可用；请求地址：{endpoint}；状态码：{response.status_code}；"
            f"返回内容：{response.text[:1000]}"
        )
    if response.status_code != 200:
        raise MinerUError(
            f"MinerU 任务结果下载失败；请求地址：{endpoint}；状态码：{response.status_code}；"
            f"返回内容：{response.text[:1000]}"
        )
    if not response.content.startswith(b"PK"):
        raise MinerUError(
            f"MinerU 任务结果不是有效压缩包；请求地址：{endpoint}；返回内容：{response.text[:1000]}"
        )
    return response.content


def get_mineru_task_with_retries(
    api_url: str,
    task_id: str,
    timeout_seconds: int,
    retry_count: int,
    document_filename: str,
) -> MinerUTaskState:
    last_error: MinerUError | httpx.HTTPError | None = None
    for attempt in range(1, retry_count + 2):
        try:
            return get_mineru_task(api_url, task_id, timeout_seconds)
        except MinerUTaskNotFoundError:
            raise
        except (MinerUError, httpx.HTTPError) as exc:
            last_error = exc
            logger.warning(
                "MinerU task status request failed",
                extra={
                    "document_filename": document_filename,
                    "task_id": task_id,
                    "api_url": api_url,
                    "attempt": attempt,
                    "max_attempts": retry_count + 1,
                    "error": str(exc),
                },
            )
            if attempt <= retry_count:
                sleep(min(attempt * 2, 5))
    if last_error is None:
        raise MinerUError(f"MinerU 未读取任务状态：{task_id}")
    unavailable = unavailable_error(
        f"MinerU 服务连接中断：{document_filename}；任务编号：{task_id}",
        last_error,
    )
    if unavailable is not None:
        raise unavailable from last_error
    raise MinerUError(
        f"MinerU 任务状态连续读取失败：{document_filename}；任务编号：{task_id}；"
        f"最后一次错误：{last_error}"
    ) from last_error


def download_mineru_result_with_retries(
    api_url: str,
    task_id: str,
    timeout_seconds: int,
    retry_count: int,
    document_filename: str,
) -> bytes:
    last_error: MinerUError | httpx.HTTPError | None = None
    for attempt in range(1, retry_count + 2):
        try:
            return download_mineru_result(api_url, task_id, timeout_seconds)
        except MinerUTaskNotFoundError:
            raise
        except (MinerUError, httpx.HTTPError) as exc:
            last_error = exc
            logger.warning(
                "MinerU task result download failed",
                extra={
                    "document_filename": document_filename,
                    "task_id": task_id,
                    "api_url": api_url,
                    "attempt": attempt,
                    "max_attempts": retry_count + 1,
                    "error": str(exc),
                },
            )
            if attempt <= retry_count:
                sleep(min(attempt * 2, 5))
    if last_error is None:
        raise MinerUError(f"MinerU 未下载任务结果：{task_id}")
    unavailable = unavailable_error(
        f"MinerU 服务连接中断：{document_filename}；任务编号：{task_id}",
        last_error,
    )
    if unavailable is not None:
        raise unavailable from last_error
    raise MinerUError(
        f"MinerU 任务结果连续下载失败：{document_filename}；任务编号：{task_id}；"
        f"最后一次错误：{last_error}"
    ) from last_error


def request_mineru(path: Path, api_url: str, timeout_seconds: int) -> bytes:
    endpoint = f"{api_url.rstrip('/')}/file_parse"
    with path.open("rb") as source:
        with httpx.Client(trust_env=False, follow_redirects=True) as client:
            response = client.post(
                endpoint,
                data=mineru_form_data(),
                files={"files": (path.name, source, "application/pdf")},
                timeout=httpx.Timeout(timeout_seconds),
            )
    if response.status_code != 200:
        raise MinerUError(
            f"MinerU 处理失败；请求地址：{endpoint}；状态码：{response.status_code}；返回内容：{response.text[:1000]}"
        )
    if not response.content.startswith(b"PK"):
        raise MinerUError(
            f"MinerU 返回格式不符合预期；请求地址：{endpoint}；返回内容：{response.text[:1000]}"
        )
    return response.content


def extract_scan_page(
    path: Path, api_url: str, timeout_seconds: int, page_number: int, backend: str
) -> ParsedPage:
    """Re-read one original PDF page without changing the whole-document OCR cache."""
    if page_number < 1 or backend not in ("pipeline", "vlm-engine"):
        raise MinerUError("疑点页识别参数无效")
    endpoint = f"{api_url.rstrip('/')}/file_parse"
    form = mineru_form_data() | {
        "backend": backend,
        "parse_method": "ocr",
        "start_page_id": str(page_number - 1),
        "end_page_id": str(page_number - 1),
    }
    try:
        with path.open("rb") as source:
            with httpx.Client(trust_env=False, follow_redirects=True) as client:
                response = client.post(
                    endpoint,
                    data=form,
                    files={"files": (mineru_upload_name(path), source, "application/pdf")},
                    timeout=httpx.Timeout(timeout_seconds),
                )
    except httpx.TransportError as exc:
        raise MinerUUnavailableError(f"MinerU 疑点页识别连接失败：第{page_number}页") from exc
    if response.status_code != 200 or not response.content.startswith(b"PK"):
        raise MinerUError(
            f"MinerU 疑点页识别失败：第{page_number}页；状态码：{response.status_code}"
        )
    pages = parse_mineru_zip(response.content, path.name)
    if len(pages) != 1 or pages[0].text.strip() == "":
        raise MinerUError(f"MinerU 疑点页没有返回有效文字：第{page_number}页")
    return ParsedPage(page_number=page_number, text=pages[0].text)


def extract_scan_pages(
    path: Path,
    api_url: str,
    timeout_seconds: int,
    retry_count: int,
    storage_dir: Path,
    sha256: str,
    existing_task_id: str | None,
    poll_seconds: int,
    max_task_seconds: int,
    on_task_update: TaskUpdateCallback,
) -> list[ParsedPage]:
    if api_url.strip() == "":
        raise MinerUError("MinerU 服务地址不能为空")
    task_state: MinerUTaskState | None = None
    task_id = existing_task_id
    last_error: MinerUError | httpx.HTTPError | None = None
    attempt = 1
    resubmitted_missing_task = False
    while attempt <= retry_count + 1:
        try:
            if task_id is None:
                task_state = submit_mineru_task(path, api_url, timeout_seconds)
                task_id = task_state.task_id
                on_task_update(task_state)
            else:
                task_state = get_mineru_task_with_retries(
                    api_url, task_id, timeout_seconds, retry_count, path.name
                )
                on_task_update(task_state)
            break
        except MinerUTaskNotFoundError as exc:
            last_error = exc
            if task_id == existing_task_id and not resubmitted_missing_task:
                logger.warning(
                    "MinerU task disappeared; resubmitting source file",
                    extra={"document_filename": path.name, "task_id": task_id, "api_url": api_url},
                )
                task_id = None
                resubmitted_missing_task = True
                continue
            raise
        except (MinerUError, httpx.HTTPError) as exc:
            last_error = exc
            logger.warning(
                "MinerU request failed",
                extra={
                    "document_filename": path.name,
                    "api_url": api_url,
                    "attempt": attempt,
                    "max_attempts": retry_count + 1,
                    "error": str(exc),
                },
            )
            if attempt <= retry_count:
                sleep(min(attempt * 2, 5))
            attempt += 1
    if task_state is None or task_id is None:
        if last_error is None:
            raise MinerUError(f"MinerU 未提交识别任务：{path.name}")
        unavailable = unavailable_error(
            f"MinerU 服务连接中断，扫描任务尚未提交：{path.name}", last_error
        )
        if unavailable is not None:
            raise unavailable from last_error
        raise MinerUError(f"扫描识别任务提交失败：{path.name}；最后一次错误：{last_error}") from last_error

    while True:
        on_task_update(task_state)
        elapsed_seconds = mineru_task_elapsed_seconds(task_state, datetime.now(timezone.utc))
        if elapsed_seconds > max_task_seconds and task_state.status not in ("completed", "failed"):
            raise MinerUError(
                f"MinerU 任务超过 {max_task_seconds // 60} 分钟仍未完成：{path.name}；"
                f"任务编号：{task_id}；当前状态：{task_state.status}"
            )
        if task_state.status == "failed":
            raise MinerUError(
                f"MinerU 任务执行失败：{path.name}；任务编号：{task_id}；"
                f"错误：{task_state.error or '未提供详细错误'}"
            )
        if task_state.status == "completed":
            content = download_mineru_result_with_retries(
                api_url, task_id, timeout_seconds, retry_count, path.name
            )
            return save_mineru_cache(storage_dir, sha256, content, path.name)
        sleep(poll_seconds)
        task_state = get_mineru_task_with_retries(
            api_url, task_id, timeout_seconds, retry_count, path.name
        )
