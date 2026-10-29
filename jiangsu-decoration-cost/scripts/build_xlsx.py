#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Build the five-sheet decoration cost workbook from CSV/JSON data.

The main input is a mapping table with the same 20 columns as
data/mapping_examples.csv.  Blank "清单编码/清单名称" cells are intentional:
they mark continuation rows that share the bill item of the row above.

Example:
  python3 scripts/build_xlsx.py \
      --mapping work/清单定额套用.csv \
      --dxf work/dxf/dxf_text.csv \
      --notes work/编制依据.md \
      -o 成果/装饰工程清单与定额套用表.xlsx

Requires: openpyxl (pip install openpyxl)
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import re
import sys
from pathlib import Path

try:
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
    from openpyxl.utils import get_column_letter
except ImportError:  # pragma: no cover
    sys.exit("需要 openpyxl：pip install openpyxl")


MAPPING_HEADERS = [
    "序号",
    "部位/分部",
    "做法编号",
    "做法名称",
    "GTJ构件/做法建议",
    "做法层序",
    "图纸做法条文",
    "清单子项",
    "清单编码",
    "清单名称",
    "项目特征描述",
    "计量单位",
    "工程量计算规则",
    "清单工作内容",
    "定额编号",
    "定额子目名称",
    "定额所属章节",
    "定额计量单位",
    "定额工作内容",
    "套用说明 / 备注",
]

HEADER_FILL = PatternFill("solid", fgColor="1F4E79")
HEADER_FONT = Font(name="微软雅黑", size=10, bold=True, color="FFFFFF")
BODY_FONT = Font(name="宋体", size=9)
WARN_FILL = PatternFill("solid", fgColor="FFF2CC")
ALT_FILL = PatternFill("solid", fgColor="EAF2F8")
THIN = Side(style="thin", color="BFBFBF")
BORDER = Border(left=THIN, right=THIN, top=THIN, bottom=THIN)

MAPPING_WIDTHS = [5, 16, 9, 14, 24, 6, 30, 15, 11, 14, 28, 7, 34, 26, 10, 28, 24, 8, 26, 46]
SOURCE_WIDTHS = [12, 24, 10, 32, 50, 45]
BOQ_MASTER_WIDTHS = [6, 12, 24, 8, 24, 24, 16, 38, 50, 40, 24, 30, 10, 22, 10, 12, 16, 9, 30, 28, 40]
QUOTA_MASTER_WIDTHS = [6, 10, 44, 8, 24, 30, 7, 40, 24, 10, 22, 10, 12, 16, 50, 26, 40]
DXF_WIDTHS = [11, 11, 14, 90]
NOTES_WIDTHS = [20, 120]


def read_table(path: Path) -> tuple[list[str], list[list]]:
    """Read a UTF-8-BOM/UTF-8/GBK CSV, or a JSON array of objects/arrays."""
    if path.suffix.lower() == ".json":
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            data = data.get("rows", [])
        if not data:
            return [], []
        if isinstance(data[0], dict):
            headers = list(data[0].keys())
            return headers, [[row.get(h, "") for h in headers] for row in data]
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
    if not rows:
        return [], []
    return rows[0], rows[1:]


def normalize_row(row: list, n: int = 20) -> list:
    row = list(row[:n])
    return row + [""] * (n - len(row))


FEATURE_INDEX = MAPPING_HEADERS.index("项目特征描述")
FEATURE_SPLIT_RE = re.compile(r"[\n；;]+")
FEATURE_PREFIX_RE = re.compile(r"^\s*\d+\s*[.、．)）](?!\d)\s*")


def number_features(text: str) -> str:
    """把项目特征拆成逐条编号的多行（1.xxx / 2.xxx）。

    输入用 `；`（或换行）分隔即可，不必手写序号；已有 `1.`/`1、` 前缀会先去掉，
    所以对已编号的内容重复执行结果不变。
    """
    raw = str(text or "").strip()
    if not raw:
        return ""
    # “——（并入…）”“（并入…）”这类整格说明不是特征条目，保持原样。
    if raw[:1] in ("—", "-", "（", "("):
        return raw
    parts = [part.strip() for part in FEATURE_SPLIT_RE.split(raw) if part.strip()]
    if len(parts) == 1 and "。" in parts[0]:
        parts = [part.strip() for part in parts[0].split("。") if part.strip()]
    items = [FEATURE_PREFIX_RE.sub("", part) for part in parts]
    return "\n".join(f"{index}.{item}" for index, item in enumerate(items, 1))


def with_numbered_features(row: list) -> list:
    row = list(row)
    if len(row) > FEATURE_INDEX:
        row[FEATURE_INDEX] = number_features(row[FEATURE_INDEX])
    return row


def is_warning(text: str) -> bool:
    markers = ("待确认", "待核对", "无对应", "未核实", "暂按", "需换算", "需确认")
    return any(marker in text for marker in markers)


def write_sheet(ws, headers: list[str], rows: list[list], widths: list[int], freeze: bool = True) -> None:
    ws.append(headers)
    for row in rows:
        ws.append(row)

    for col, width in enumerate(widths[: len(headers)], 1):
        ws.column_dimensions[get_column_letter(col)].width = width
    for col in range(len(widths) + 1, len(headers) + 1):
        ws.column_dimensions[get_column_letter(col)].width = 18

    for cell in ws[1]:
        cell.fill = HEADER_FILL
        cell.font = HEADER_FONT
        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        cell.border = BORDER
    ws.row_dimensions[1].height = 30 if len(headers) > 6 else 24

    for row_idx in range(2, ws.max_row + 1):
        for col_idx in range(1, len(headers) + 1):
            cell = ws.cell(row=row_idx, column=col_idx)
            cell.font = BODY_FONT
            cell.alignment = Alignment(vertical="top", wrap_text=True)
            cell.border = BORDER

    if freeze:
        ws.freeze_panes = "A2"
    if ws.max_row >= 2:
        ws.auto_filter.ref = f"A1:{get_column_letter(len(headers))}{ws.max_row}"
    ws.sheet_view.showGridLines = False
    ws.page_setup.orientation = "landscape"
    ws.page_setup.fitToWidth = 1
    ws.page_setup.fitToHeight = 0
    ws.sheet_properties.pageSetUpPr.fitToPage = True


def style_mapping(ws, rows: list[list]) -> None:
    """Shade alternating bill-item groups and highlight unresolved notes."""
    group_index = 0
    previous_no = object()
    for row_idx, row in enumerate(rows, 2):
        no = row[0]
        if no != previous_no:
            group_index += 1
            previous_no = no
        if group_index % 2 == 0:
            for col_idx in range(1, len(MAPPING_HEADERS) + 1):
                ws.cell(row=row_idx, column=col_idx).fill = ALT_FILL
        note = str(row[19]) if len(row) > 19 else ""
        if is_warning(note):
            ws.cell(row=row_idx, column=20).fill = WARN_FILL
        # Rough row height based on the longest wrapped cell.
        lengths = []
        for col_idx, value in enumerate(row[: len(MAPPING_HEADERS)], 1):
            width = MAPPING_WIDTHS[col_idx - 1]
            text = str(value) if value is not None else ""
            lines = sum(max(1, math.ceil(len(part) / max(width - 1, 4))) for part in text.split("\n"))
            lengths.append(lines)
        ws.row_dimensions[row_idx].height = min(120, max(22, max(lengths, default=1) * 13.5))


def count_verified(rows: list[list], headers: list[str]) -> int:
    if "核对状态" not in headers:
        return 0
    idx = headers.index("核对状态")
    return sum(1 for row in rows if len(row) > idx and str(row[idx]).strip() == "已核对")


def default_notes(
    boq_count: int,
    quota_count: int,
    mapping_count: int,
    boq_done: int = 0,
    quota_done: int = 0,
) -> list[list[str]]:
    boq_scope = (
        f"清单主表 {boq_count} 条（GB/T 50854-2024 全量 472 条 + 江苏增补 5 条），"
        f"已逐条核对 {boq_done} 条；"
    )
    quota_scope = (
        f"定额主表 {quota_count} 条（《江苏省建筑与装饰工程消耗量（2026）》全量），"
        f"已逐条核对 {quota_done} 条。"
    )
    return [
        ["编制依据与使用说明", ""],
        ["1. 清单依据", "《房屋建筑与装饰工程工程量计算标准》GB/T 50854-2024（江苏省 2024 版清单计量标准，自 2026-06-01 起执行）。清单编码、名称、项目特征、计量单位、工程量计算规则和工作内容取自该标准。"],
        ["2. 定额依据", "《江苏省建筑与装饰工程消耗量（2026）》（苏建价〔2026〕76 号，自 2026-06-01 起施行）。"],
        ["3. 数据范围", boq_scope + quota_scope + "主表“核对状态”列标明每条是否已回查原文；“待核对”条目仅为候选编码，使用前必须按原文页码复核。"],
        ["4. 套项原则", "清单按实体（部位/构造）列项，定额按施工层、材料、厚度、做法拆分子目；一个清单项下可对应多条定额子目。后续定额行留空清单字段，表示沿用上一条清单项。"],
        ["5. 项目特征", "项目特征描述按条分行编号（1.、2.、3.…），每条对应一项需要组价人还原的做法要素；编号仅为阅读方便，不改变清单项目特征的内容口径。"],
        ["6. 使用限制", f"共 {mapping_count} 条套用明细。带“待确认/待核对/无对应/需换算”等字样的备注为待确认事项，使用前应由造价专业人员复核，不得直接把推定子目当作正式依据。"],
    ]


def read_notes(
    path: Path | None,
    boq_count: int,
    quota_count: int,
    mapping_count: int,
    boq_done: int = 0,
    quota_done: int = 0,
) -> list[list[str]]:
    if not path:
        return default_notes(boq_count, quota_count, mapping_count, boq_done, quota_done)
    text = path.read_text(encoding="utf-8-sig")
    rows: list[list[str]] = []
    for raw in text.splitlines():
        line = raw.rstrip()
        if not line:
            rows.append(["", ""])
            continue
        if line.startswith("#"):
            rows.append([line.lstrip("#").strip(), ""])
        elif "|" in line:
            left, right = line.split("|", 1)
            rows.append([left.strip(), right.strip()])
        else:
            rows.append([line.strip(), ""])
    return rows


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    base = Path(__file__).resolve().parent.parent
    parser.add_argument("--mapping", type=Path, required=True, help="清单定额套用 CSV/JSON")
    parser.add_argument("--boq", type=Path, default=base / "data/boq_2024_jiangsu.csv", help="清单主表 CSV")
    parser.add_argument("--quota", type=Path, default=base / "data/quota_2026_jiangsu.csv", help="定额主表 CSV")
    parser.add_argument("--dxf", type=Path, default=None, help="DXF 提取后的 dxf_text.csv，可选")
    parser.add_argument("--notes", type=Path, default=None, help="编制依据 Markdown/文本，可选")
    parser.add_argument("-o", "--out", type=Path, required=True, help="输出 xlsx 路径")
    parser.add_argument("--no-feature-numbering", action="store_true", help="项目特征描述保持原样，不自动加 1./2./3. 序号")
    args = parser.parse_args()

    headers, rows = read_table(args.mapping)
    if headers[: len(MAPPING_HEADERS)] != MAPPING_HEADERS:
        print("警告：mapping 表头与标准 20 列不完全一致，将按列序写入。", file=sys.stderr)
        print("标准表头：" + " | ".join(MAPPING_HEADERS), file=sys.stderr)
    rows = [normalize_row(row) for row in rows]
    if not args.no_feature_numbering:
        rows = [with_numbered_features(row) for row in rows]

    boq_headers, boq_rows = read_table(args.boq)
    quota_headers, quota_rows = read_table(args.quota)

    wb = Workbook()
    ws = wb.active
    ws.title = "清单定额套用"
    write_sheet(ws, MAPPING_HEADERS, rows, MAPPING_WIDTHS)
    style_mapping(ws, rows)

    ws2 = wb.create_sheet("清单库(2024-江苏)")
    boq_widths = BOQ_MASTER_WIDTHS if "核对状态" in boq_headers else SOURCE_WIDTHS
    write_sheet(ws2, boq_headers, boq_rows, boq_widths)

    ws3 = wb.create_sheet("定额子目(江苏2026)")
    quota_widths = QUOTA_MASTER_WIDTHS if "核对状态" in quota_headers else SOURCE_WIDTHS
    write_sheet(ws3, quota_headers, quota_rows, quota_widths)

    if args.dxf:
        dxf_path = args.dxf / "dxf_text.csv" if args.dxf.is_dir() else args.dxf
        dxf_headers, dxf_rows = read_table(dxf_path)
        ws4 = wb.create_sheet("工程做法原文(DXF)")
        write_sheet(ws4, dxf_headers, dxf_rows, DXF_WIDTHS)

    notes = read_notes(
        args.notes,
        len(boq_rows),
        len(quota_rows),
        len(rows),
        count_verified(boq_rows, boq_headers),
        count_verified(quota_rows, quota_headers),
    )
    ws5 = wb.create_sheet("编制依据与说明")
    write_sheet(ws5, ["项目", "内容"], notes, NOTES_WIDTHS, freeze=False)
    for row_idx in range(2, ws5.max_row + 1):
        ws5.row_dimensions[row_idx].height = 38
    ws5.column_dimensions["A"].width = 20
    ws5.column_dimensions["B"].width = 120

    args.out.parent.mkdir(parents=True, exist_ok=True)
    wb.save(args.out)
    print(f"已生成：{args.out.resolve()}")
    print(f"清单 {len(boq_rows)} 条；定额 {len(quota_rows)} 条；套用明细 {len(rows)} 行")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
