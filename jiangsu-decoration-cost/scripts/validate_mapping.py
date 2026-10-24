#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Validate a 清单定额套用 CSV before building the workbook.

Checks that are always errors:
  * malformed bill/quota codes
  * a continuation row whose group has no bill code
  * inconsistent bill fields inside one group

Checks that are warnings (unless --strict):
  * a bill code that is not in the 26-row verified seed library
  * a bill code that is not even in the 477-row full BOQ index
  * a quota code that is not in the 59-row verified seed library
  * a quota code that is not even in the 3115-row full index
  * a missing quota unit
  * a row with no quota at all

Usage:
  python3 scripts/validate_mapping.py work/清单定额套用.csv
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from pathlib import Path

HEADERS = [
    "序号", "部位/分部", "做法编号", "做法名称", "GTJ构件/做法建议", "做法层序",
    "图纸做法条文", "清单子项", "清单编码", "清单名称", "项目特征描述", "计量单位",
    "工程量计算规则", "清单工作内容", "定额编号", "定额子目名称", "定额所属章节",
    "定额计量单位", "定额工作内容", "套用说明 / 备注",
]
EMPTY_MARKERS = {"", "—", "-", "/", "无", "（无对应子目）", "(无对应子目)", "待定"}
BILL_CODE_RE = re.compile(r"^\d{9}$")
QUOTA_CODE_RE = re.compile(r"^\d+-\d+$")


def read_rows(path: Path) -> tuple[list[str], list[list[str]]]:
    if path.suffix.lower() == ".json":
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            data = data.get("rows", [])
        if data and isinstance(data[0], dict):
            headers = list(data[0].keys())
            return headers, [[str(row.get(h, "")) for h in headers] for row in data]
        return [str(i + 1) for i in range(len(data[0]))], data
    raw = path.read_bytes()
    for enc in ("utf-8-sig", "utf-8", "gb18030"):
        try:
            text = raw.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    else:
        raise SystemExit(f"无法解码：{path}")
    rows = list(csv.reader(text.splitlines()))
    return rows[0], rows[1:]


def load_codes(path: Path, col: str) -> set[str]:
    headers, rows = read_rows(path)
    if not rows:
        return set()
    idx = headers.index(col) if col in headers else 0
    return {str(row[idx]).strip() for row in rows if len(row) > idx and str(row[idx]).strip()}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    base = Path(__file__).resolve().parent.parent
    parser.add_argument("mapping", type=Path, help="清单定额套用 CSV/JSON")
    parser.add_argument("--boq", type=Path, default=base / "data/boq_2024_jiangsu.csv")
    parser.add_argument("--boq-index", type=Path, default=base / "data/boq_2024_jiangsu_index.csv")
    parser.add_argument("--quota", type=Path, default=base / "data/quota_2026_jiangsu_seed.csv")
    parser.add_argument("--index", type=Path, default=base / "data/quota_2026_jiangsu_index.csv")
    parser.add_argument("--strict", action="store_true", help="把警告也视为失败")
    args = parser.parse_args()

    headers, rows = read_rows(args.mapping)
    boq_codes = load_codes(args.boq, "清单编码")
    boq_index_codes = load_codes(args.boq_index, "清单编码") if args.boq_index.exists() else set()
    quota_codes = load_codes(args.quota, "定额编号")
    index_codes = load_codes(args.index, "定额编号") if args.index.exists() else set()

    errors: list[str] = []
    warnings: list[str] = []
    if headers[: len(HEADERS)] != HEADERS:
        errors.append("表头不是标准 20 列。")
    if not rows:
        errors.append("没有数据行。")

    group_no = None
    group_bill: dict[str, str] | None = None
    for i, row in enumerate(rows, 2):
        row = list(row) + [""] * (20 - len(row))
        no = row[0].strip()
        code = row[8].strip()
        name = row[9].strip()
        unit = row[11].strip()
        quota = row[14].strip()
        quota_unit = row[17].strip()
        note = row[19].strip()

        if no != group_no:
            group_no = no
            group_bill = None

        if not no:
            errors.append(f"第 {i} 行：序号为空。")
        if not row[6].strip():
            warnings.append(f"第 {i} 行：图纸做法条文为空。")
        if not row[5].strip():
            warnings.append(f"第 {i} 行：做法层序为空。")

        if code:
            if code not in EMPTY_MARKERS and not BILL_CODE_RE.match(code):
                errors.append(f"第 {i} 行：清单编码格式异常“{code}”。")
            if code not in EMPTY_MARKERS and code not in boq_codes:
                if code in boq_index_codes:
                    warnings.append(
                        f"第 {i} 行：清单编码 {code} 在 477 条全量清单索引中，"
                        "但不在 26 条已核对种子库，需核对项目特征和计算规则。"
                    )
                else:
                    warnings.append(
                        f"第 {i} 行：清单编码 {code} 不在 477 条全量清单索引中，需核对标准原文。"
                    )
            if not unit:
                warnings.append(f"第 {i} 行：有清单编码但计量单位为空。")
            group_bill = {"code": code, "name": name, "unit": unit}
        else:
            if group_bill is None:
                errors.append(f"第 {i} 行：清单编码为空，但上方没有可沿用的清单项。")
            elif group_bill["code"] not in EMPTY_MARKERS:
                if name and name != group_bill["name"]:
                    errors.append(f"第 {i} 行：同一清单组内清单名称不一致。")
                if unit and unit != group_bill["unit"]:
                    errors.append(f"第 {i} 行：同一清单组内计量单位不一致。")

        if quota and quota not in EMPTY_MARKERS:
            if not QUOTA_CODE_RE.match(quota):
                errors.append(f"第 {i} 行：定额编号格式异常“{quota}”。")
            elif quota not in quota_codes:
                if quota in index_codes:
                    warnings.append(
                        f"第 {i} 行：定额编号 {quota} 在 3115 条全量索引中，"
                        "但不在 59 条已核对种子库，需按索引页码复核名称和单位。"
                    )
                else:
                    warnings.append(
                        f"第 {i} 行：定额编号 {quota} 不在 3115 条索引中，需核对消耗量原文。"
                    )
            if not quota_unit:
                warnings.append(f"第 {i} 行：定额编号 {quota} 缺少定额计量单位。")
        elif not note:
            warnings.append(f"第 {i} 行：既没有定额编号，也没有说明（应写明“含在……内”或“待确认”）。")

    for text in errors:
        print("ERROR  " + text)
    for text in warnings:
        print("WARN   " + text)
    print(f"\n检查完成：{len(rows)} 行，错误 {len(errors)}，警告 {len(warnings)}。")
    if errors or (args.strict and warnings):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
