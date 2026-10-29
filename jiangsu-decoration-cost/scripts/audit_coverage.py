#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""检查清单/定额主表的核对覆盖率，并校验“已核对”行的证据。

用法：
  python3 scripts/audit_coverage.py
  python3 scripts/audit_coverage.py --json
  python3 scripts/audit_coverage.py --strict   # 未全部核对时返回非零

输出包括：
  * 每条主表的已核对/待核对/有争议数量；
  * “已核对”但没有证据ID、或证据表里找不到的行；
  * 重复编码、空名称/空单位；
  * 清单缺少原文页码、定额单位为“见表”等风险提示。
"""

from __future__ import annotations

import argparse
import csv
import json
import re
from collections import Counter, defaultdict
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
DATA = BASE / "data"
EVIDENCE = DATA / "verification_evidence.csv"

DATASETS = {
    "清单": {
        "path": DATA / "boq_2024_jiangsu.csv",
        "code": "清单编码",
        "name": "清单名称",
        "unit": "计量单位",
        "chapter": "附录",
    },
    "定额": {
        "path": DATA / "quota_2026_jiangsu.csv",
        "code": "定额编号",
        "name": "定额子目名称",
        "unit": "计量单位",
        "chapter": "章",
    },
}


def read_csv(path: Path) -> list[dict[str, str]]:
    raw = path.read_bytes()
    for encoding in ("utf-8-sig", "utf-8", "gb18030"):
        try:
            return list(csv.DictReader(raw.decode(encoding).splitlines()))
        except UnicodeDecodeError:
            continue
    raise SystemExit(f"无法解码：{path}")


def audit_dataset(label: str, config: dict[str, Path | str], evidence_ids: set[str]) -> dict[str, object]:
    rows = read_csv(config["path"])
    code_key = str(config["code"])
    name_key = str(config["name"])
    unit_key = str(config["unit"])
    chapter_key = str(config["chapter"])

    status = Counter((row.get("核对状态") or "空").strip() for row in rows)
    codes = [row.get(code_key, "").strip() for row in rows]
    duplicates = sorted(code for code, count in Counter(codes).items() if code and count > 1)
    blank_name = [row.get(code_key, "") for row in rows if not row.get(name_key, "").strip()]
    blank_unit = [row.get(code_key, "") for row in rows if not row.get(unit_key, "").strip()]

    verified = [row for row in rows if (row.get("核对状态") or "").strip() == "已核对"]
    missing_evidence = [row.get(code_key, "") for row in verified if not row.get("证据ID", "").strip()]
    unknown_evidence = [
        row.get(code_key, "")
        for row in verified
        if row.get("证据ID", "").strip() and row["证据ID"].strip() not in evidence_ids
    ]
    no_page = []
    if label == "清单":
        no_page = [
            row.get(code_key, "")
            for row in rows
            if not row.get("原文页码", "").strip()
            and not row.get("清单编码", "").startswith(("010103003", "011601016", "011601017", "011601018", "011601019"))
        ]

    chapter_rows: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in rows:
        chapter_rows[(row.get(chapter_key) or "未分类").strip()].append(row)
    chapter_coverage = []
    for chapter, items in chapter_rows.items():
        done = sum(1 for row in items if (row.get("核对状态") or "").strip() == "已核对")
        chapter_coverage.append(
            {
                "章节": chapter,
                "总数": len(items),
                "已核对": done,
                "覆盖率": round(done / len(items) * 100, 1) if items else 0.0,
            }
        )
    chapter_coverage.sort(key=lambda item: (item["覆盖率"], item["章节"]))

    total = len(rows)
    done = status.get("已核对", 0)
    return {
        "数据类别": label,
        "文件": str(config["path"].relative_to(BASE)),
        "总数": total,
        "状态": dict(status),
        "已核对": done,
        "覆盖率": round(done / total * 100, 1) if total else 0.0,
        "重复编码": duplicates,
        "空名称": blank_name,
        "空单位": blank_unit,
        "已核对但无证据ID": missing_evidence,
        "证据ID不存在": unknown_evidence,
        "清单缺原文页码": no_page,
        "章节覆盖率": chapter_coverage,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--json", action="store_true", help="输出 JSON")
    parser.add_argument("--strict", action="store_true", help="未全部核对或存在证据/字段问题时返回非零")
    args = parser.parse_args()

    evidence_rows = read_csv(EVIDENCE) if EVIDENCE.exists() else []
    evidence_ids = {row.get("证据ID", "").strip() for row in evidence_rows if row.get("证据ID", "").strip()}
    results = [audit_dataset(label, config, evidence_ids) for label, config in DATASETS.items()]

    if args.json:
        print(json.dumps(results, ensure_ascii=False, indent=2))
    else:
        for result in results:
            print(f"【{result['数据类别']}】{result['文件']}")
            print(f"  总数：{result['总数']}；已核对：{result['已核对']}（{result['覆盖率']}%）")
            print("  状态：" + "，".join(f"{k} {v}" for k, v in result["状态"].items()))
            for key in ("重复编码", "空名称", "空单位", "已核对但无证据ID", "证据ID不存在", "清单缺原文页码"):
                value = result[key]
                if value:
                    print(f"  {key}：{len(value)} 条，示例 {value[:5]}")
            print("  低覆盖章节：")
            for item in result["章节覆盖率"][:5]:
                print(f"    {item['章节']}：{item['已核对']}/{item['总数']}（{item['覆盖率']}%）")
            print()

    problems = 0
    for result in results:
        problems += len(result["重复编码"]) + len(result["空名称"]) + len(result["空单位"])
        problems += len(result["已核对但无证据ID"]) + len(result["证据ID不存在"])
        if result["清单缺原文页码"]:
            problems += len(result["清单缺原文页码"])
    incomplete = any(result["已核对"] != result["总数"] for result in results)
    if args.strict and (incomplete or problems):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
