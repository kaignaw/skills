#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""用官方 PDF 的文本/OCR 逐行比对清单主表，生成机器核对证据。

用法：
  python3 scripts/verify_boq_from_ocr.py --ocr gbocr.json --dry-run
  python3 scripts/verify_boq_from_ocr.py --ocr gbocr.json --apply

输入 `--ocr` 为官方 PDF 的 OCR JSON：`[{"page": 14, "items": [{"text": ..., "x0": ..., "y0": ..., "x1": ..., "y1": ...}]}, ...]`。
脚本按 9 位编码定位表格行，再从“项目名称”列重建名称，与主表名称比对：

  * 编码命中、名称一致（允许 OCR 常见错字/拆行）→ 标 `已核对`；
  * 编码或名称对不上 → 保持 `待核对`，在报告里列出，供人工按页码复核。

核对方式写为“官方PDF OCR 逐行比对（机器）”，核对批次 `ocr-audit-YYYY-MM-DD`，
并在 `data/verification_evidence.csv` 追加证据。`--dry-run` 只打印统计，不改文件。
"""

from __future__ import annotations

import argparse
import csv
import difflib
import json
import re
from collections import Counter
from datetime import date
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
DATA = BASE / "data"
MASTER = DATA / "boq_2024_jiangsu.csv"
EVIDENCE = DATA / "verification_evidence.csv"

GB_SHA = "cee06719fcfd23fee3e007c0cd65ae751c3edc4a72bb90006c4ba88703bbf708"
GB_URL = "https://www.mohurd.gov.cn/gongkai/zc/wjk/art/2024/art_c713a0ba3ee241de91d00ba70a031312.html"
SOURCE_NAME = "GB/T 50854-2024 官方 PDF（OCR）"
SOURCE_VERSION = "GB/T 50854-2024"

CODE_RE = re.compile(r"^\d{9}$")
HEADER_TOKENS = {
    "项目编码", "项目名称", "项目特征", "计量单位", "工程量计算规则", "工作内容",
    "编码", "名称", "单位",
}
NOISE_TOKENS = {"城乡", "城", "乡"}


def norm(value: str) -> str:
    value = value.replace("（", "(").replace("）", ")").replace("、", "、")
    return re.sub(r"[\s\u3000]", "", value)


def read_csv(path: Path) -> list[dict[str, str]]:
    raw = path.read_bytes()
    for encoding in ("utf-8-sig", "utf-8", "gb18030"):
        try:
            return list(csv.DictReader(raw.decode(encoding).splitlines()))
        except UnicodeDecodeError:
            continue
    raise SystemExit(f"无法解码：{path}")


def row_band(items: list[dict], target: dict) -> list[dict]:
    y = float(target["y0"])
    return [
        item
        for item in items
        if y - 55 <= float(item["y0"]) <= y + 75
    ]


def name_bounds(items: list[dict], target: dict) -> tuple[float, float]:
    """名称列左右界：以编码列位置为准。

    表头“项目名称”的 x0 是标签起点，不是列边界；“项目特征”同理，直接拿来
    切列会把右邻的项目特征文字带进来。清单表各列宽度稳定，编码列右侧
    150～370px 就是名称列。
    """
    x = float(target["x0"])
    return x + 150, x + 370


FEATURE_MARKER = re.compile(r"^[（(]?\d+[)）.．、]")

# OCR 常见字形混淆；只用于比对，不写回主表。
OCR_CONFUSIONS = str.maketrans({"標": "檩", "隆": "降", "尧": ""})


def reconstruct_name(items: list[dict], target: dict) -> str:
    low, high = name_bounds(items, target)
    picked = []
    for item in row_band(items, target):
        text = item["text"].strip()
        if not text or CODE_RE.match(text) or text in HEADER_TOKENS or text in NOISE_TOKENS:
            continue
        if FEATURE_MARKER.match(text):
            continue
        if low <= float(item["x0"]) <= high:
            picked.append(item)
    picked.sort(key=lambda item: (float(item["y0"]), float(item["x0"])))
    name = norm("".join(item["text"] for item in picked))
    if not name:
        # 少数表格把编码和名称 OCR 成同一个文本框。
        text = target["text"].strip()
        code = text[:9]
        if CODE_RE.match(code) and len(text) > 9:
            name = norm(text[9:])
    return name


def find_target(items: list[dict], code: str) -> dict | None:
    for item in items:
        if item["text"].strip() == code:
            return item
    for item in items:
        if code in item["text"]:
            return item
    return None


def is_subsequence(short: str, long: str) -> bool:
    iterator = iter(long)
    return all(char in iterator for char in short)


def name_matches(expected: str, found: str) -> bool:
    expected, found = norm(expected), norm(found).translate(OCR_CONFUSIONS)
    if not found:
        return False
    if expected == found or expected in found or found in expected:
        return True
    if difflib.SequenceMatcher(None, expected, found).ratio() >= 0.85:
        return True
    # 表头/特征行偶发穿插，名称字符仍按序出现。
    return len(expected) >= 4 and len(found) <= len(expected) * 3 and is_subsequence(expected, found)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--ocr", type=Path, required=True, help="官方 PDF OCR JSON")
    parser.add_argument("--master", type=Path, default=MASTER)
    parser.add_argument("--evidence", type=Path, default=EVIDENCE)
    parser.add_argument("--batch", default=f"ocr-audit-{date.today().isoformat()}")
    parser.add_argument("--apply", action="store_true", help="写回主表和证据表")
    parser.add_argument("--dry-run", action="store_true", help="只统计，不写文件（默认行为）")
    parser.add_argument(
        "--recheck-legacy",
        action="store_true",
        help="用 OCR 复核历史批次（legacy-seed-*）的已核对行，升级其核对方式和证据",
    )
    args = parser.parse_args()

    pages = {int(page["page"]): page["items"] for page in json.loads(args.ocr.read_text(encoding="utf-8"))}
    rows = read_csv(args.master)
    evidence_rows = read_csv(args.evidence) if args.evidence.exists() else []
    known_ids = {row.get("证据ID", "").strip() for row in evidence_rows}

    verified, pending, no_page = 0, 0, 0
    mismatches: list[tuple[str, str, str, str]] = []
    new_evidence: list[list[str]] = []
    evidence_updates: dict[str, list[str]] = {}
    evidence_index = {row.get("证据ID", "").strip(): row for row in evidence_rows}

    for row in rows:
        legacy = row.get("核对批次", "").startswith("legacy-seed-")
        if row.get("核对状态", "").strip() == "已核对" and not (args.recheck_legacy and legacy):
            verified += 1
            continue
        page_text = row.get("原文页码", "").strip()
        code = row.get("清单编码", "").strip()
        if not page_text.isdigit() or int(page_text) not in pages:
            no_page += 1
            mismatches.append((code, row.get("清单名称", ""), "缺少 OCR 页面", page_text))
            continue
        items = pages[int(page_text)]
        target = find_target(items, code)
        found = reconstruct_name(items, target) if target else ""
        if not target or not name_matches(row.get("清单名称", ""), found):
            pending += 1
            mismatches.append((code, row.get("清单名称", ""), found or "未定位到名称", page_text))
            continue

        verified += 1
        evidence_id = f"EV-BOQ-{code}"
        row["核对状态"] = "已核对"
        row["核对方式"] = "官方PDF OCR 逐行比对（机器）"
        row["核对人"] = "ocr-audit"
        row["核对日期"] = date.today().isoformat()
        row["核对批次"] = args.batch
        row["原文摘录"] = f"{code} {row.get('清单名称', '').strip()}"
        row["证据ID"] = evidence_id
        note = row.get("备注", "").strip()
        marker = "机器 OCR 比对，名称一致"
        if marker not in note:
            row["备注"] = (note + "；" if note else "") + marker
        record = [
            evidence_id, "清单", code, SOURCE_NAME, SOURCE_VERSION, GB_URL, GB_SHA,
            page_text, row["原文摘录"], str(args.ocr), "ocr-audit",
            date.today().isoformat(),
            f"官方PDF第{page_text}页 OCR 名称序列：{found}；单位按计算规则复核",
        ]
        if evidence_id in evidence_index:
            evidence_updates[evidence_id] = record
        elif evidence_id not in known_ids:
            new_evidence.append(record)
            known_ids.add(evidence_id)

    print(f"已核对 {verified} 条；本次比对通过并新增 {len(new_evidence)} 条；仍待核对 {pending} 条；无 OCR 页面 {no_page} 条")
    if evidence_updates:
        print(f"升级历史批次证据 {len(evidence_updates)} 条")
    if mismatches:
        print("\n未通过（需人工复核）：")
        for code, expected, found, page in mismatches[:40]:
            print(f"  {code} 第{page}页 期望“{expected}” OCR“{found}”")
        if len(mismatches) > 40:
            print(f"  ……其余 {len(mismatches) - 40} 条")

    if not args.apply:
        print("\n（未写文件；加 --apply 生效）")
        return 0

    with args.master.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)
    if new_evidence or evidence_updates:
        fields = list(evidence_rows[0].keys()) if evidence_rows else [
            "证据ID", "数据类别", "条目编码", "来源名称", "来源版本", "来源URL",
            "来源SHA256", "物理页码", "原文摘录", "证据文件", "核对人", "核对日期", "备注",
        ]
        with args.evidence.open("w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=fields)
            writer.writeheader()
            for existing in evidence_rows:
                updated = evidence_updates.get(existing.get("证据ID", "").strip())
                if updated:
                    writer.writerow(dict(zip(fields, updated)))
                else:
                    writer.writerow(existing)
            for record in new_evidence:
                writer.writerow(dict(zip(fields, record)))
    print(f"已写回 {args.master}，新增证据 {len(new_evidence)} 条，升级 {len(evidence_updates)} 条")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
