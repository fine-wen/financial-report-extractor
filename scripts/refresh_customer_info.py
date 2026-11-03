"""Validate QCC exports and prepare a traceable customer-information refresh.

This script reads source files only. Spreadsheet creation is handled by the
companion Artifact Tool builder.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import sys
from collections import Counter, defaultdict
from datetime import date
from pathlib import Path

from openpyxl import load_workbook


KINDS = {
    "专利": ("企业名称", "发明名称", "专利类型", "法律状态", "申请号", "申请日", "公开(公告)号", "公开(公告)日期", "发明人", "申请(专利权)人"),
    "软件著作权": ("企业名称", "软件全称", "软件简称", "版本号", "登记号", "完成日期", "首次发布日期", "登记日期", "权利取得方式"),
    "资质证书": ("企业名称", "资质名称", "资质类别及等级/产品名称/认证项目", "证书编号", "发证机构", "发证日期", "有效期至", "证书状态"),
    "荣誉": ("企业名称", "名称", "编号", "荣誉类型", "级别", "发布单位", "认证年份", "发布日期", "有效期自", "有效期至", "来源"),
    "标准信息": ("企业名称", "标准号", "标准级别", "标准属性", "标准名称", "起草单位", "起草人", "发布日期", "状态"),
    "商标": ("企业名称", "商标名称", "国际分类", "商标状态", "申请/注册号", "申请日期", "注册公告日期"),
}


def clean(value: object) -> str:
    text = "" if value is None else str(value).strip()
    if text.startswith('="') and text.endswith('"'):
        text = text[2:-1].replace('""', '"')
    return "" if text == "-" else text


def source_files(folder: Path) -> dict[str, Path]:
    found: dict[str, Path] = {}
    for kind in ["工商信息", *KINDS]:
        suffix = ".xlsx" if kind == "工商信息" else ".csv"
        candidates = [p for p in folder.rglob(f"*{suffix}") if "批量查询" in p.name and ("企业基础工商信息" if kind == "工商信息" else kind) in p.name]
        if len(candidates) != 1:
            raise ValueError(f"{kind}需要恰好一份导出文件，实际发现{len(candidates)}份；请替换旧文件后再刷新。")
        found[kind] = candidates[0]
    return found


def read_basic(path: Path) -> list[dict]:
    wb = load_workbook(path, read_only=True, data_only=True)
    if len(wb.worksheets) != 1:
        raise ValueError("工商信息导出应只有一个工作表")
    ws = wb.active
    ws.reset_dimensions()  # QCC exports an incorrect A1 used-range marker.
    rows = ws.iter_rows(values_only=True)
    next(rows, None)  # Disclaimer.
    header = [clean(x) for x in next(rows)]
    expected = ["原文件导入名称", "企业名称", "登记状态", "统一社会信用代码"]
    if any(name not in header for name in expected):
        raise ValueError(f"工商信息缺少必要字段：{[x for x in expected if x not in header]}")
    records = []
    for rowno, row in enumerate(rows, 3):
        if not any(row):
            continue
        item = dict(zip(header, [clean(x) for x in row]))
        if not item.get("企业名称"):
            raise ValueError(f"工商信息第{rowno}行无企业名称")
        records.append(item)
    wb.close()
    return records


def read_csv(path: Path, expected: tuple[str, ...]) -> list[dict]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        rows = csv.reader(handle)
        next(rows, None)  # Disclaimer.
        next(rows, None)  # Blank row.
        next(rows, None)  # Category title.
        header = [clean(x) for x in next(rows)]
        if tuple(header[: len(expected)]) != expected:
            raise ValueError(f"{path.name}字段结构已变化，已停止刷新，避免错列：{header}")
        records = []
        for rowno, row in enumerate(rows, 1):
            if not row or not any(clean(x) for x in row):
                continue
            if len(row) < len(expected):
                raise ValueError(f"{path.name}第{rowno}条记录列数不足")
            item = dict(zip(expected, [clean(x) for x in row]))
            item["_row"] = rowno
            if not item["企业名称"]:
                raise ValueError(f"{path.name}第{rowno}条记录无企业名称")
            records.append(item)
        return records


def year(value: str) -> int | None:
    match = re.match(r"^(19|20)\d{2}", value)
    return int(match.group()) if match else None


def record_key(kind: str, row: dict) -> str:
    fields = {
        "专利": ("申请号", "公开(公告)号"),
        "软件著作权": ("登记号",),
        "资质证书": ("证书编号", "资质名称", "发证日期"),
        "荣誉": ("编号", "名称", "认证年份", "来源"),
        "标准信息": ("标准号", "标准名称", "发布日期"),
        "商标": ("申请/注册号", "国际分类"),
    }[kind]
    parts = [row.get(field, "") for field in fields]
    if not any(parts):
        parts = [json.dumps({k: v for k, v in row.items() if k != "_row"}, ensure_ascii=False, sort_keys=True)]
    return json.dumps([kind, row["企业名称"], *parts], ensure_ascii=False)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--previous", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    files = source_files(args.source)
    basic = read_basic(files["工商信息"])
    by_name = {x["企业名称"]: x for x in basic}
    if len(by_name) != len(basic):
        raise ValueError("工商信息存在重复企业名称，不能安全汇总")
    codes = [x["统一社会信用代码"] for x in basic if x["统一社会信用代码"]]
    if len(codes) != len(set(codes)):
        raise ValueError("工商信息存在重复统一社会信用代码，不能安全汇总")
    aliases = defaultdict(set)
    for item in basic:
        aliases[item["企业名称"]].add(item["企业名称"])
        aliases[item["原文件导入名称"]].add(item["企业名称"])

    previous = json.loads(args.previous.read_text(encoding="utf-8")) if args.previous.exists() else {}
    prior_records = previous.get("records", {})
    current_records: dict[str, dict] = {}
    stats = defaultdict(Counter)
    annual = defaultdict(Counter)
    honors = defaultdict(lambda: defaultdict(list))
    problems = []
    changes = []
    qualification_details = []
    duplicate_count = Counter()
    this_year = date.today().year

    for kind, schema in KINDS.items():
        for item in read_csv(files[kind], schema):
            source_name = item["企业名称"]
            matches = aliases.get(source_name, set())
            if len(matches) != 1:
                problems.append([kind, source_name, "未匹配工商信息" if not matches else "企业名称匹配冲突", item["_row"]])
                company = source_name
            else:
                company = next(iter(matches))
            item["企业名称"] = company
            key = record_key(kind, item)
            digest = hashlib.sha256(json.dumps({k: v for k, v in item.items() if k != "_row"}, ensure_ascii=False, sort_keys=True).encode()).hexdigest()
            if key in current_records:
                duplicate_count[kind] += 1
                if current_records[key]["digest"] == digest:
                    continue
                problems.append([kind, company, "同一记录编号对应不同内容，已分别保留", item["_row"]])
                key = f"{key}#{digest}"
                if key in current_records:
                    continue
            current_records[key] = {"digest": digest, "kind": kind, "company": company, "label": item.get({"专利": "发明名称", "软件著作权": "软件全称", "资质证书": "资质名称", "荣誉": "名称", "标准信息": "标准名称", "商标": "商标名称"}[kind], ""), "state": item.get({"专利": "法律状态", "软件著作权": "权利取得方式", "资质证书": "证书状态", "荣誉": "级别", "标准信息": "状态", "商标": "商标状态"}[kind], ""), "source_row": item["_row"]}
            stats[company][kind] += 1
            if kind in ("资质证书", "荣誉"):
                qualification_details.append([
                    by_name.get(company, {}).get("统一社会信用代码", ""), company, kind,
                    item.get("资质名称", item.get("名称", "")),
                    item.get("证书编号", item.get("编号", "")),
                    item.get("证书状态", item.get("级别", "")),
                    item.get("发证日期", item.get("发布日期", "")),
                    item.get("有效期至", ""), item["_row"],
                ])
            if kind == "专利":
                typ = item["专利类型"]
                grant_year = year(item["公开(公告)日期"])
                if typ in ("发明授权", "实用新型") and grant_year and this_year - 2 <= grant_year <= this_year:
                    annual[company][f"{grant_year}_{typ}"] += 1
                if typ in ("发明授权", "实用新型"):
                    stats[company]["授权专利历史记录"] += 1
            elif kind == "软件著作权":
                registered = year(item["登记日期"])
                if registered and this_year - 2 <= registered <= this_year:
                    annual[company][f"{registered}_软著"] += 1
            elif kind == "资质证书":
                if item["证书状态"] == "有效" and (not item["有效期至"] or item["有效期至"] >= date.today().isoformat()):
                    stats[company]["有效证书"] += 1
            elif kind == "荣誉":
                honors[company][item["名称"]].append(year(item["认证年份"]) or year(item["发布日期"]))
            elif kind == "标准信息" and item["状态"] in ("现行", "现行有效"):
                stats[company]["现行标准"] += 1
            elif kind == "商标" and "注册" in item["商标状态"] and "无效" not in item["商标状态"]:
                stats[company]["注册商标"] += 1
            before = prior_records.get(key)
            if prior_records and before is None:
                changes.append([company, kind, "新增", current_records[key]["label"], current_records[key]["state"], item["_row"]])
            elif before and before["digest"] != digest:
                changes.append([company, kind, "信息变化", current_records[key]["label"], f'{before.get("state", "")} → {current_records[key]["state"]}', item["_row"]])

    if prior_records:
        for key, old in prior_records.items():
            if key not in current_records:
                changes.append([old["company"], old["kind"], "本次未出现，待核查", old.get("label", ""), old.get("state", ""), ""])

    all_names = sorted(set(by_name) | {x[1] for x in problems if x[2] == "未匹配工商信息"})
    change_counts = defaultdict(Counter)
    for item in changes:
        change_counts[item[0]][item[2]] += 1
    summary = []
    for company in all_names:
        b = by_name.get(company, {})
        row = [b.get("统一社会信用代码", ""), company, b.get("登记状态", "缺工商信息"), b.get("所属区县", "")]
        for y in range(this_year - 2, this_year + 1):
            row.extend([annual[company][f"{y}_发明授权"], annual[company][f"{y}_实用新型"], annual[company][f"{y}_软著"]])
        for title in ("高新技术企业", "专精特新中小企业", "专精特新“小巨人”企业"):
            years = [x for x in honors[company][title] if x]
            row.append(max(years) if years else "")
        row.extend([stats[company]["有效证书"], stats[company]["荣誉"], stats[company]["现行标准"], stats[company]["注册商标"], change_counts[company]["新增"], change_counts[company]["信息变化"], change_counts[company]["本次未出现，待核查"]])
        summary.append(row)

    source_log = []
    for kind, path in files.items():
        source_log.append([kind, str(path.relative_to(args.source.parent)), path.stat().st_size, hashlib.sha256(path.read_bytes()).hexdigest(), len(basic) if kind == "工商信息" else sum(v["kind"] == kind for v in current_records.values()), duplicate_count[kind]])
    payload = {
        "as_of": date.today().isoformat(), "years": list(range(this_year - 2, this_year + 1)),
        "first_run": not bool(prior_records), "previous_as_of": previous.get("as_of", ""),
        "summary": summary, "qualification_details": qualification_details, "changes": changes,
        "problems": problems, "sources": source_log,
        "snapshot": {"as_of": date.today().isoformat(), "records": current_records},
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    print(f"已核对{len(summary)}家企业、{len(current_records)}条去重记录；问题{len(problems)}条，变更{len(changes)}条。")


if __name__ == "__main__":
    try:
        main()
    except (ValueError, OSError, KeyError, StopIteration) as exc:
        print(f"刷新失败：{exc}", file=sys.stderr)
        sys.exit(1)
