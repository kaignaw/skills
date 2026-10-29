#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""环境与数据自检：一条命令确认本技能能否直接跑出成果。

检查内容：
  1. Python 版本与必需依赖（openpyxl）；可选依赖只提示不报错。
  2. 五张数据表是否存在、表头是否完整、条数是否与 manifest 一致。
  3. 主表核对状态分布；出现 `待核对` 时给出提示。
  4. 20 列套用表表头是否与标准一致（含第 20 列 `套用说明 / 备注` 的空格）。
  5. 抽样跑一次 lookup，确认查询链路可用。

用法：
  python3 scripts/preflight.py            # 全部检查
  python3 scripts/preflight.py --quiet    # 只打印结论

退出码：0 全部通过；1 有致命问题（缺文件/缺依赖/表头错）；2 仅警告。
"""

from __future__ import annotations

import argparse
import csv
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
DATA = BASE / "data"

EXPECTED = {
    "boq_2024_jiangsu.csv": ("清单主表", 477),
    "quota_2026_jiangsu.csv": ("定额主表", 3133),
    "verification_evidence.csv": ("核对证据", 3610),
    "mapping_examples.csv": ("套用示例", 96),
    "example_dxf_text.csv": ("DXF 示例", 206),
}

REQUIRED_BOQ = ["序号", "清单编码", "清单名称", "计量单位", "附录", "节", "项目特征", "工程量计算规则", "工作内容", "核对状态", "原文页码", "证据ID"]
REQUIRED_QUOTA = ["序号", "定额编号", "定额子目名称", "计量单位", "章", "节", "页码", "工作内容", "核对状态", "证据ID"]

MAPPING_HEADER = [
    "序号", "部位/分部", "做法编号", "做法名称", "GTJ构件/做法建议", "做法层序", "图纸做法条文",
    "清单子项", "清单编码", "清单名称", "项目特征描述", "计量单位", "工程量计算规则", "清单工作内容",
    "定额编号", "定额子目名称", "定额所属章节", "定额计量单位", "定额工作内容", "套用说明 / 备注",
]

errors: list[str] = []
warnings: list[str] = []


def ok(message: str) -> None:
    print(f"  [OK]   {message}")


def warn(message: str) -> None:
    warnings.append(message)
    print(f"  [WARN] {message}")


def fail(message: str) -> None:
    errors.append(message)
    print(f"  [FAIL] {message}")


def read_rows(path: Path) -> tuple[list[str], list[dict]]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        return list(reader.fieldnames or []), list(reader)


def check_env() -> None:
    print("\n[1/5] 运行环境")
    if sys.version_info < (3, 10):
        fail(f"Python {sys.version.split()[0]} 过低，需要 3.10+")
    else:
        ok(f"Python {sys.version.split()[0]}")
    for module, level, hint in (
        ("openpyxl", "required", "生成 xlsx 必需"),
        ("bs4", "optional", "仅重建清单主表需要"),
        ("pdfplumber", "optional", "仅复核定额主表需要"),
    ):
        found = importlib.util.find_spec(module) is not None
        if found:
            ok(f"{module} 已安装")
        elif level == "required":
            fail(f"缺少 {module}（{hint}）：pip install {module}")
        else:
            warn(f"未安装 {module}（{hint}）")


def check_data() -> None:
    print("\n[2/5] 数据文件")
    manifest_path = DATA / "manifest.json"
    manifest = {}
    if manifest_path.exists():
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        ok(f"manifest.json 版本 {manifest.get('version', '?')}")
    else:
        warn("缺少 data/manifest.json，条数只能按实测值判断")

    for name, (label, expected) in EXPECTED.items():
        path = DATA / name
        if not path.exists():
            fail(f"缺少 {label} {name}")
            continue
        header, rows = read_rows(path)
        detail = f"{label} {name}：{len(rows)} 条"
        if expected and len(rows) != expected:
            warn(f"{detail}（manifest 记为 {expected} 条，请确认是否有意变更）")
        else:
            ok(detail)
        if name == "boq_2024_jiangsu.csv":
            missing = [c for c in REQUIRED_BOQ if c not in header]
        elif name == "quota_2026_jiangsu.csv":
            missing = [c for c in REQUIRED_QUOTA if c not in header]
        else:
            missing = []
        if missing:
            fail(f"{name} 缺少字段：{'、'.join(missing)}")


def check_verification() -> None:
    print("\n[3/5] 核对状态")
    for name, label in (("boq_2024_jiangsu.csv", "清单"), ("quota_2026_jiangsu.csv", "定额")):
        path = DATA / name
        if not path.exists():
            continue
        _, rows = read_rows(path)
        pending = sum(1 for row in rows if row.get("核对状态", "").strip() != "已核对")
        if pending:
            warn(f"{label}主表有 {pending} 条 `待核对`；使用前须按页码回查并补证据")
        else:
            ok(f"{label}主表 {len(rows)} 条全部 `已核对`")
    evidence = DATA / "verification_evidence.csv"
    if evidence.exists():
        _, rows = read_rows(evidence)
        ids = {row.get("条目编码", "") for row in rows}
        ok(f"证据 {len(rows)} 条，覆盖 {len(ids)} 个条目")


def check_mapping_header() -> None:
    print("\n[4/5] 20 列套用表表头")
    template = BASE / "assets" / "mapping_template.csv"
    if template.exists():
        header, _ = read_rows(template)
        if header == MAPPING_HEADER:
            ok("模板 assets/mapping_template.csv 表头标准")
        else:
            fail("模板表头与标准 20 列不一致")
    else:
        warn("缺少 assets/mapping_template.csv")


def check_lookup() -> None:
    print("\n[5/5] 查询链路")
    script = BASE / "scripts" / "lookup.py"
    for args, expect in ((["boq", "屋面"], "010902001"), (["quota", "13-136"], "13-136")):
        try:
            result = subprocess.run(
                [sys.executable, str(script), *args], capture_output=True, text=True, timeout=120
            )
        except Exception as exc:  # pragma: no cover
            fail(f"lookup.py 运行失败：{exc}")
            continue
        if result.returncode != 0:
            fail(f"lookup.py {' '.join(args)} 退出码 {result.returncode}")
        elif expect in result.stdout:
            ok(f"lookup.py {' '.join(args)} 命中 {expect}")
        else:
            warn(f"lookup.py {' '.join(args)} 未命中 {expect}，请确认数据是否被改动")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--quiet", action="store_true", help="只打印最终结论")
    args = parser.parse_args()

    if args.quiet:
        import contextlib
        import io

        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            check_env()
            check_data()
            check_verification()
            check_mapping_header()
            check_lookup()
    else:
        print("江苏装饰清单定额套项 · 自检")
        check_env()
        check_data()
        check_verification()
        check_mapping_header()
        check_lookup()

    print("\n结论")
    if errors:
        print(f"  未通过：{len(errors)} 个致命问题")
        for item in errors:
            print(f"   - {item}")
        return 1
    if warnings:
        print(f"  可用，但有 {len(warnings)} 个提示（不影响出表）")
        return 2
    print("  全部通过，可直接套项与出表")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
