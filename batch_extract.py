import os
import sys
import json
import csv
import re
import time
import threading
import logging
import subprocess
import argparse
from pathlib import Path
from datetime import datetime

import openai
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler

BASE_DIR = Path(__file__).parent
WATCH_DIR = BASE_DIR / "input_pdfs"
OUTPUT_DIR = BASE_DIR / "output"
SUCCESS_DIR = BASE_DIR / "success"


INDICATORS = [
    "营业收入",
    "主营业务收入",
    "营业成本",
    "主营业务成本",
    "利润总额",
    "净利润",
    "研发费用",
    "销售费用",
    "管理费用",
    "资产总额",
    "负债总额",
    "所有者权益",
]
CSV_HEADERS = ["客户名称"] + INDICATORS + ["处理时间"]

DS_API_KEY = os.environ.get("DEEPSEEK_API_KEY", "")
DS_BASE_URL = "https://api.deepseek.com"
DS_MODEL = "deepseek-chat"

MINERU_MODEL_SOURCE = os.environ.get("MINERU_MODEL_SOURCE", "modelscope")
os.environ["MINERU_MODEL_SOURCE"] = MINERU_MODEL_SOURCE

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger(__name__)


def get_processed_keys() -> set:
    keys = set()
    for csv_file in BASE_DIR.glob("financial_data_*.csv"):
        try:
            with open(csv_file, "r", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    name = row.get("客户名称", "").strip()
                    if name:
                        keys.add(name)
        except Exception:
            continue
    return keys


def get_csv_path_for_year(year: str) -> Path:
    year_str = str(year) if year and str(year) != "未知年度" else "其他"
    return BASE_DIR / f"financial_data_{year_str}.csv"


def append_to_csv(row: dict, year: str):
    csv_path = get_csv_path_for_year(year)
    file_exists = csv_path.exists()
    with open(csv_path, "a", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_HEADERS)
        if not file_exists:
            writer.writeheader()
        writer.writerow(row)
    log.info(
        f"已写入 {csv_path.name}: {row.get('客户名称', '?')}"
    )


def parse_pdf_with_mineru(pdf_path: Path) -> str | None:
    pdf_name = pdf_path.stem
    out_subdir = OUTPUT_DIR / pdf_name
    auto_dir = out_subdir / "auto"

    # mineru 输出文件名有多种可能
    possible_md = [
        auto_dir / "input.md",
        auto_dir / f"{pdf_name}.md",
    ]
    for md_path in possible_md:
        if md_path.exists():
            log.info(f"  MinerU 已有缓存: {md_path}")
            return str(md_path)

    # 放宽匹配: 搜索所有输出目录，找文件名包含 pdf_name 的
    for d in OUTPUT_DIR.iterdir():
        if d.is_dir() and pdf_name in d.name:
            for m in (d / "auto").glob("*.md"):
                log.info(f"  MinerU 模糊匹配缓存: {m}")
                return str(m)

    log.info(f"  正在调用 mineru 解析: {pdf_path.name}")
    result = subprocess.run(
        [
            "mineru",
            "-p",
            str(pdf_path),
            "-o",
            str(OUTPUT_DIR),
            "-b",
            "pipeline",
            "-f",
            "False",
        ],
        capture_output=True,
        text=True,
        timeout=3600,
        env={**os.environ, "MINERU_MODEL_SOURCE": MINERU_MODEL_SOURCE},
    )

    if result.returncode != 0:
        log.error(
            f"  mineru 解析失败 (code={result.returncode}): {result.stderr[:500]}"
        )
        return None

    # 再次尝试查找 md 文件
    for md_path in possible_md:
        if md_path.exists():
            log.info(f"  MinerU 解析完成: {md_path}")
            return str(md_path)

    fallback = OUTPUT_DIR / "input" / "auto" / "input.md"
    if fallback.exists():
        log.info(f"  MinerU 解析完成(回退路径): {fallback}")
        return str(fallback)

    # 再试试 auto 目录下的任何 .md 文件
    if auto_dir.exists():
        for f in auto_dir.glob("*.md"):
            log.info(f"  MinerU 解析完成(自动发现): {f}")
            return str(f)

    log.error(f"  MinerU 解析后未找到 md 文件 (可检查 {OUTPUT_DIR})")
    return None


MAX_DS_CHARS = 120000


def extract_relevant_sections(md_content: str) -> str:
    lines = md_content.split("\n")

    # 跳过审计意见正文（第一个 <table> 之前的内容）
    table_start = None
    for i, line in enumerate(lines):
        if "<table>" in line:
            table_start = i
            break

    if table_start is None:
        return md_content

    # 找到附注数据区入口
    note_start = None
    for i in range(table_start, len(lines)):
        if "合并财务报表项目注释" in lines[i]:
            note_start = i
            break

    # 主表部分: 从第一个 table 到附注开始前
    part_a_lines = lines[table_start:note_start] if note_start else lines[table_start:]
    part_a = "\n".join(part_a_lines)

    log.info(f"  跳过审计意见({table_start}行)")

    if note_start is None:
        # 只有主表，没有附注
        return part_a

    # 附注部分: 从合并财务报表项目注释到结尾
    part_b = "\n".join(lines[note_start:])
    log.info(f"  主表({len(part_a)}字符) + 附注({len(part_b)}字符)")

    # 组合: 尽量保留两部分
    if len(part_a) + len(part_b) <= MAX_DS_CHARS:
        return part_a + "\n\n" + part_b

    # 超出限制: 附注优先（含营业收入等明细数据）
    b_budget = min(len(part_b), 70000)
    a_budget = MAX_DS_CHARS - b_budget
    part_b = part_b[:b_budget]
    part_a = part_a[:a_budget]
    log.info(
        f"  压缩后: 主表({a_budget}字符) + 附注({b_budget}字符) = {a_budget + b_budget}字符"
    )
    return part_a + "\n\n" + part_b


def read_md_content(md_path: str) -> str:
    with open(md_path, "r", encoding="utf-8") as f:
        content = f.read()
    content = extract_relevant_sections(content)
    if len(content) > MAX_DS_CHARS:
        log.warning(f"  超出限制，截取前 {MAX_DS_CHARS} 字符")
        content = content[:MAX_DS_CHARS]
    log.info(f"  发送给 DeepSeek: {len(content)} 字符")
    return content


def determine_report_type(md_full: str) -> str:
    has_bs = '资产负债表' in md_full
    has_is = '利润表' in md_full
    has_cf = '现金流量表' in md_full
    has_notes = '合并财务报表项目注释' in md_full
    table_count = md_full.count('<table>')

    log.info(
        f"  判定报表类型: 主表(资产={has_bs},利润={has_is},现金流={has_cf}), "
        f"附注={has_notes}, 表格数={table_count}"
    )

    if has_bs and has_is and has_notes:
        return "审计报告"
    return "财务报表"


def extract_indicators_via_ds(md_content: str) -> dict:
    indicators_str = "、".join(INDICATORS)

    system_prompt = f"""你是一个专业的财务报表数据提取助手。你的任务是从财务报表的 Markdown 内容中提取指定的财务指标。

要求：
1. 提取以下 12 个指标【仅限合并报表数据，如果找不到合并报表则用母公司报表】：{indicators_str}
2. 同时从正文中识别出【客户/公司全称】
3. 识别报告的【年度】（如 2024、2025）
4. 优先使用最新年度的数据（报告通常包含两年对比，取最新一年）
5. 金额以"元"为单位，返回纯数字（去掉逗号分隔符）
6. 如果某个指标在报告中完全没有披露，返回 "未披露"
7. 只返回 JSON，不要任何解释或额外文字

JSON 格式示例：
{{
    "客户名称": "公司全称",
    "年度": 2024,
    "营业收入": 123456789.00,
    "主营业务收入": 123456789.00,
    ...
}}"""

    user_prompt = f"请从以下审计报告内容中提取财务数据：\n\n{md_content}"

    try:
        client = openai.OpenAI(api_key=DS_API_KEY, base_url=DS_BASE_URL)
        resp = client.chat.completions.create(
            model=DS_MODEL,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.01,
            response_format={"type": "json_object"},
        )

        content = resp.choices[0].message.content or ""
        text = content.strip()
        return json.loads(text) if text else {}

    except Exception as e:
        log.error(f"  DeepSeek API 调用失败: {e}")
        return {}


def clean_ds_result(result: dict) -> dict:
    row = {"客户名称": result.get("客户名称", "未知")}
    for ind in INDICATORS:
        val = result.get(ind, "未披露")
        if val is None or val == "" or val == "null":
            val = "未披露"
        if val != "未披露":
            try:
                val = float(str(val).replace(",", "").replace(" ", ""))
            except (ValueError, TypeError):
                val = "未披露"
        row[ind] = val
    row["处理时间"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    return row


def move_to_success(pdf_path: Path, company: str, year: str, report_type: str):

    SUCCESS_DIR.mkdir(parents=True, exist_ok=True)
    new_name = f"{company}_{year}_{report_type}.pdf"
    dest = SUCCESS_DIR / new_name

    counter = 1
    while dest.exists():
        new_name = f"{company}_{year}_{report_type}({counter}).pdf"
        dest = SUCCESS_DIR / new_name
        counter += 1

    try:
        pdf_path.rename(dest)
        log.info(f"  已归档: {pdf_path.name} → {dest.name}")
    except Exception as e:
        log.error(f"  归档失败: {e}")


def process_pdf(pdf_path: Path, index: int = 1, total: int = 1):
    log.info(f"[{index}/{total}] 开始处理: {pdf_path.name}")

    md_path = parse_pdf_with_mineru(pdf_path)
    if not md_path:
        log.error(f"  {pdf_path.name} 解析失败，跳过")
        return

    # 读取完整内容用于判定报表类型
    with open(md_path, "r", encoding="utf-8") as f:
        md_full = f.read()
    report_type = determine_report_type(md_full)

    md_content = read_md_content(md_path)
    log.info(f"  已读取 Markdown ({len(md_content)} 字符)")

    raw_result = extract_indicators_via_ds(md_content)
    if not raw_result:
        log.error(f"  {pdf_path.name} DeepSeek 提取失败，跳过")
        return

    row = clean_ds_result(raw_result)
    log.info(
        f"  提取结果: {row.get('客户名称')} | "
        f"营业收入={row.get('营业收入')} | "
        f"净利润={row.get('净利润')}"
    )

    year = raw_result.get("年度", "其他")
    append_to_csv(row, year)
    company = raw_result.get("客户名称", pdf_path.stem)
    move_to_success(pdf_path, company, str(year), report_type)
    log.info(f"  ✓ [{index}/{total}] {pdf_path.name} 处理完成")


class PdfHandler(FileSystemEventHandler):
    def __init__(self):
        self.processed = get_processed_keys()
        self.pending_timers = {}
        log.info(f"已处理过的公司数: {len(self.processed)}")

    def on_created(self, event):
        if event.is_directory:
            return
        src = (
            event.src_path
            if isinstance(event.src_path, str)
            else event.src_path.decode()
        )
        if not src.lower().endswith(".pdf"):
            return
        self.schedule_process(Path(src))

    def on_moved(self, event):
        dest = (
            event.dest_path
            if isinstance(event.dest_path, str)
            else event.dest_path.decode()
        )
        if not dest.lower().endswith(".pdf"):
            return
        self.schedule_process(Path(dest))

    def schedule_process(self, pdf_path: Path):
        path_str = str(pdf_path)
        if path_str in self.pending_timers:
            self.pending_timers[path_str].cancel()
        self.pending_timers[path_str] = threading.Timer(
            3.0, self.do_process, args=[pdf_path]
        )
        self.pending_timers[path_str].start()

    def do_process(self, pdf_path: Path):
        path_str = str(pdf_path)
        self.pending_timers.pop(path_str, None)

        if not pdf_path.exists():
            return

        try:
            size1 = pdf_path.stat().st_size
            time.sleep(1)
            size2 = pdf_path.stat().st_size
            if size1 != size2:
                log.info(f"  文件仍在写入中，等待...")
                time.sleep(2)
        except OSError:
            log.warning(f"  文件不可访问: {pdf_path.name}")
            return

        process_pdf(pdf_path)

    def process_existing_files(self):
        pdfs = sorted(WATCH_DIR.glob("*.pdf"))
        total = len(pdfs)
        if total == 0:
            log.info("  input_pdfs/ 中没有待处理的 PDF")
            return
        log.info(f"发现 {total} 个待处理 PDF")
        for i, p in enumerate(pdfs, 1):
            process_pdf(p, index=i, total=total)


def main():
    parser = argparse.ArgumentParser(description="财务报表自动提取工具")
    group = parser.add_mutually_exclusive_group()
    group.add_argument(
        "--watch",
        action="store_true",
        help="持续监控 input_pdfs/ 文件夹（处理现有文件后不退出）",
    )
    group.add_argument(
        "--run-once",
        action="store_true",
        default=True,
        help="处理完现有 PDF 后退出（默认模式）",
    )
    args = parser.parse_args()

    if not DS_API_KEY:
        log.error("环境变量 DEEPSEEK_API_KEY 未设置！")
        log.error("请在运行前执行: set DEEPSEEK_API_KEY=sk-你的key")
        sys.exit(1)

    WATCH_DIR.mkdir(parents=True, exist_ok=True)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    log.info("=" * 50)
    log.info("财务报表自动提取工具 启动")
    log.info(f"监控文件夹: {WATCH_DIR}")
    log.info(f"成功归档:   {SUCCESS_DIR}")
    log.info(f"CSV 输出:   {BASE_DIR}/financial_data_年度.csv")
    log.info(f"DeepSeek 模型: {DS_MODEL}")
    log.info(f"运行模式: {'持续监控' if args.watch else '一次性处理'}")
    log.info("=" * 50)
    log.info("将 PDF 放入 input_pdfs/ 文件夹即可自动处理")
    log.info("处理完成后自动退出\n")

    handler = PdfHandler()
    handler.process_existing_files()

    if not args.watch:
        log.info("全部处理完成，程序退出。")
        return

    observer = Observer()
    observer.schedule(handler, str(WATCH_DIR), recursive=False)
    observer.start()
    log.info("文件监控已启动，等待新文件...")

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        observer.stop()
        log.info("\n工具已停止")
    observer.join()


if __name__ == "__main__":
    main()
