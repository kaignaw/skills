#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Search the bundled Jiangsu BOQ / quota / mapping data.

Examples:
  python3 scripts/lookup.py quota 保温
  python3 scripts/lookup.py quota --chapter 第十章 --unit m3
  python3 scripts/lookup.py index 保温
  python3 scripts/lookup.py index 干挂 --chapter 第十三章
  python3 scripts/lookup.py boq 屋面
  python3 scripts/lookup.py boqindex 屋面
  python3 scripts/lookup.py boqindex 011101001 --json
  python3 scripts/lookup.py mapping 干挂

The script prints a compact Markdown table, which keeps the result readable in
a terminal and directly usable in notes.  Use --json for machine-readable data.
A full quota code such as 12-18 is matched exactly; a 9-digit bill code is
also matched exactly.  Other queries search all fields, so "12-18" does not
return 12-180/12-181.
"""

from __future__ import annotations

import argparse
import csv
import json
import re
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent / "data"


def read_csv(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    raw = path.read_bytes()
    for enc in ("utf-8-sig", "utf-8", "gb18030"):
        try:
            text = raw.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    else:
        raise SystemExit(f"无法解码：{path}")
    rows = list(csv.DictReader(text.splitlines()))
    return (list(rows[0].keys()) if rows else []), rows


def normalize_unit(value: str) -> str:
    return (
        value.replace("m3", "m³")
        .replace("m2", "m²")
        .replace("M3", "m³")
        .replace("M2", "m²")
        .replace(" ", "")
    )


def match(value: str, query: str) -> bool:
    return query.lower() in (value or "").lower()


def print_table(headers: list[str], rows: list[dict[str, str]], limit: int) -> None:
    print("| " + " | ".join(headers) + " |")
    print("|" + "|".join(["---"] * len(headers)) + "|")
    for row in rows[:limit]:
        cells = []
        for h in headers:
            value = str(row.get(h, "")).replace("\n", " ").replace("|", "／")
            if len(value) > 80:
                value = value[:77] + "…"
            cells.append(value)
        print("| " + " | ".join(cells) + " |")
    if len(rows) > limit:
        print(f"\n共 {len(rows)} 条，仅显示前 {limit} 条。")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument(
        "kind",
        choices=["boq", "boqindex", "quota", "index", "mapping"],
        help="查询哪张表：boq=26条已核对清单种子库，boqindex=477条全量清单索引，quota=59条已核对定额种子库，index=3115条定额全量索引",
    )
    parser.add_argument("query", nargs="?", default="", help="关键词（不区分大小写，匹配所有字段）")
    parser.add_argument("--chapter", default="", help="按章节过滤，如 第十章 / 13.4 / 附录K / K.1")
    parser.add_argument("--unit", default="", help="按计量单位过滤，如 m3 / 10m²")
    parser.add_argument("--quality", default="", help="index/boqindex 通用：按名称质量精确过滤，如 已核对 / 自动提取 / 国标提取 / 江苏增补（已核对）")
    parser.add_argument("--limit", type=int, default=30)
    parser.add_argument("--json", action="store_true", help="输出 JSON")
    args = parser.parse_args()

    if args.kind == "boq":
        path = BASE / "boq_2024_jiangsu.csv"
        headers = ["清单编码", "清单名称", "计量单位"]
    elif args.kind == "boqindex":
        path = BASE / "boq_2024_jiangsu_index.csv"
        headers = ["清单编码", "清单名称", "计量单位", "附录", "节", "名称质量", "江苏差异"]
    elif args.kind == "quota":
        path = BASE / "quota_2026_jiangsu_seed.csv"
        headers = ["定额编号", "定额子目名称", "计量单位", "章", "节"]
    elif args.kind == "index":
        path = BASE / "quota_2026_jiangsu_index.csv"
        headers = ["定额编号", "定额子目名称", "计量单位", "章", "节", "页码"]
    else:
        path = BASE / "mapping_examples.csv"
        headers = ["序号", "做法编号", "做法层序", "图纸做法条文", "清单编码", "定额编号", "套用说明 / 备注"]

    _, rows = read_csv(path)
    query = args.query.strip()
    exact_quota = bool(re.fullmatch(r"\d{1,2}-\d{1,4}", query))
    exact_boq = bool(re.fullmatch(r"\d{9}", query))
    result = []
    for row in rows:
        if query:
            if exact_quota and args.kind in ("quota", "index", "mapping"):
                if row.get("定额编号", "").strip() != query:
                    continue
            elif exact_boq and args.kind in ("boq", "boqindex", "mapping"):
                if row.get("清单编码", "").strip() != query:
                    continue
            elif not any(match(str(v), query) for v in row.values()):
                continue
        if args.chapter and not match(
            row.get("章", "") + row.get("节", "") + row.get("附录", "") + row.get("定额所属章节", ""),
            args.chapter,
        ):
            continue
        if args.unit and normalize_unit(args.unit) not in normalize_unit(
            row.get("计量单位", "") + row.get("定额计量单位", "")
        ):
            continue
        if args.quality and row.get("名称质量", "").strip() != args.quality:
            continue
        result.append(row)

    if args.json:
        print(json.dumps(result[: args.limit], ensure_ascii=False, indent=2))
    else:
        print_table(headers, result, args.limit)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
