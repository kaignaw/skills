#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""生成人工核对队列，按“使用频率 + 抽取风险”排序。

用法：
  python3 scripts/build_review_queue.py
  python3 scripts/build_review_queue.py --kind quota --out work/quota_review.csv

优先处理：
  1. 高频章节（混凝土、楼地面、墙柱面、天棚、油漆、门窗、防水、保温、其他零星）；
  2. 单位为“见表”、工作内容为空、名称为空/过短；
  3. 名称中含单位碎片、独立数字、截断词等明显抽取风险。

输出只包含“待核对/有争议”行，已核对行不会进入队列。
"""

from __future__ import annotations

import argparse
import csv
import re
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
DATA = BASE / "data"

HIGH_PRIORITY_CHAPTERS = {
    "第五章", "第九章", "第十章", "第十二章", "第十三章", "第十四章",
    "第十五章", "第十六章", "第八章", "附录E", "附录H", "附录J", "附录K",
    "附录L", "附录M", "附录N", "附录P",
}

SUSPICIOUS_PATTERNS = [
    (re.compile(r"·\d+·"), "名称含独立数字"),
    (re.compile(r"(?:10m2|10m²|100m2|100m²|m2|m²|m3|m³|10m|100m)(?:·|$)", re.I), "名称含单位碎片"),
    (re.compile(r"(?:安装在|搁放在|型|U|T)$"), "名称疑似截断"),
    (re.compile(r"·见表(?:·|$)"), "名称含见表"),
]

# 这些词后面的“数字+单位”是规格描述（斗容量0.6m³、单体构件0.5m³），不是单位碎片。
DIMENSION_KEYWORDS = re.compile(r"(?:容量|构件|厚度|高度|宽度|长度|直径|管径|面积|体积|重量|层数)\S{0,4}$")


def is_false_unit_fragment(name: str, match: re.Match[str]) -> bool:
    prefix = name[: match.start()]
    if prefix.endswith("kg/"):
        return True
    return bool(DIMENSION_KEYWORDS.search(prefix))


def read_csv(path: Path) -> list[dict[str, str]]:
    raw = path.read_bytes()
    for encoding in ("utf-8-sig", "utf-8", "gb18030"):
        try:
            return list(csv.DictReader(raw.decode(encoding).splitlines()))
        except UnicodeDecodeError:
            continue
    raise SystemExit(f"无法解码：{path}")


def flags(row: dict[str, str], kind: str) -> list[str]:
    issues: list[str] = []
    name = row.get("清单名称" if kind == "boq" else "定额子目名称", "").strip()
    unit = row.get("计量单位", "").strip()
    work = row.get("工作内容", "").strip()
    if not name:
        issues.append("名称为空")
    elif len(name) < 4:
        issues.append("名称过短")
    if not unit:
        issues.append("单位为空")
    elif unit == "见表":
        issues.append("单位见表")
    if kind == "quota" and not work and not row.get("定额编号", "").startswith("20-"):
        issues.append("工作内容为空")
    for pattern, label in SUSPICIOUS_PATTERNS:
        match = pattern.search(name)
        if not match:
            continue
        if label == "名称含单位碎片" and is_false_unit_fragment(name, match):
            continue
        issues.append(label)
        break
    return issues


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--kind", choices=["boq", "quota", "all"], default="all")
    parser.add_argument("--out", type=Path, default=BASE.parent / "work" / "review_queue.csv")
    parser.add_argument("--limit", type=int, default=0, help="只输出前 N 条；0 表示全部")
    args = parser.parse_args()

    rows: list[dict[str, str]] = []
    sources = []
    if args.kind in ("boq", "all"):
        sources.append(
            (
                "boq",
                DATA / "boq_2024_jiangsu.csv",
                "清单编码",
                "清单名称",
                "附录",
                "节",
                "原文页码",
            )
        )
    if args.kind in ("quota", "all"):
        sources.append(
            (
                "quota",
                DATA / "quota_2026_jiangsu.csv",
                "定额编号",
                "定额子目名称",
                "章",
                "节",
                "页码",
            )
        )

    for kind, path, code_key, name_key, chapter_key, section_key, page_key in sources:
        for row in read_csv(path):
            if (row.get("核对状态") or "").strip() == "已核对":
                continue
            chapter = row.get(chapter_key, "").strip()
            section = row.get(section_key, "").strip()
            high_priority = chapter in HIGH_PRIORITY_CHAPTERS or any(
                chapter.startswith(prefix) for prefix in HIGH_PRIORITY_CHAPTERS
            )
            priority = "P1" if high_priority else "P2"
            issues = flags(row, kind)
            if issues:
                priority = "P0"
            rows.append(
                {
                    "优先级": priority,
                    "数据类别": "清单" if kind == "boq" else "定额",
                    "编码": row.get(code_key, ""),
                    "名称": row.get(name_key, ""),
                    "单位": row.get("计量单位", ""),
                    "章节": chapter,
                    "节": section,
                    "页码": row.get(page_key, ""),
                    "预检问题": "；".join(issues),
                }
            )

    rows.sort(key=lambda item: (item["优先级"], item["数据类别"], item["章节"], item["编码"]))
    if args.limit:
        rows = rows[: args.limit]

    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=["优先级", "数据类别", "编码", "名称", "单位", "章节", "节", "页码", "预检问题"],
        )
        writer.writeheader()
        writer.writerows(rows)

    from collections import Counter

    print(f"待核对 {len(rows)} 条；输出 {args.out}")
    print("优先级：" + "，".join(f"{k} {v}" for k, v in Counter(row["优先级"] for row in rows).items()))
    print("预检问题：" + "，".join(f"{k} {v}" for k, v in Counter(
        issue for row in rows for issue in (row["预检问题"].split("；") if row["预检问题"] else [])
    ).items()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
