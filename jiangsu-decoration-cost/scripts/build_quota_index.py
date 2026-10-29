#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Build the 2026 Jiangsu quota master table from the official PDF text.

The official 2026 consumption PDF has a text layer, but its tables use merged
headers, superscripts and multi-column names.  This script extracts one row per
unique quota code and keeps the physical PDF page number so every automatically
extracted name can be checked against the original.

Typical use:
  pdftotext -layout js2026.pdf js2026.txt
  python3 scripts/build_quota_index.py --text js2026.txt

Or let the script call pdftotext:
  python3 scripts/build_quota_index.py --pdf js2026.pdf

The output is the single authoritative quota master table (3133 rows).  Every
row starts as "待核对"; verification conclusions already present in the existing
master table are carried over by 定额编号, so a rebuild does not reset reviewed
rows.  A "待核对" name is machine-extracted and must be checked against 页码
before it is used as a formal quota name.
"""

from __future__ import annotations

import argparse
import bisect
import csv
import re
import subprocess
import tempfile
from collections import Counter
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
DEFAULT_OUT = BASE / "data" / "quota_2026_jiangsu.csv"

FIELDS = [
    "序号", "定额编号", "定额子目名称", "计量单位", "章", "节", "页码",
    "工作内容", "数据来源", "核对状态", "核对方式", "核对人", "核对日期",
    "核对批次", "原文摘录", "证据ID", "备注",
]

VERIFY_FIELDS = [
    "核对状态", "核对方式", "核对人", "核对日期", "核对批次", "原文摘录", "证据ID",
]

CODE_RE = re.compile(r"(?<!\d)(\d{1,2}-\d{1,4})(?!\d)")
SECTION_RE = re.compile(r"^\s*(\d{1,2}(?:\.\d{1,3}){1,4})\s+([^\s].*)$")
CHAPTER_RE = re.compile(r"^第[一二三四五六七八九十百]+章\s*(.+?)[.．]{2,}")

CN = [
    "零", "一", "二", "三", "四", "五", "六", "七", "八", "九", "十",
    "十一", "十二", "十三", "十四", "十五", "十六", "十七", "十八", "十九",
    "二十", "二十一",
]

SYMBOL_MAP = {
    "\ue015": "m³",
    "\ue01b": "m³",
    "\ue01c": "m²",
    "\ue350": "φ",
    "\uf0b4": "×",
    "\uf03d": "=",
}


def clean_text(value: str) -> str:
    for old, new in SYMBOL_MAP.items():
        value = value.replace(old, new)
    value = value.replace("\u00a0", " ")
    value = re.sub(r"\s+", " ", value)
    return value.strip(" .·、")


def norm_unit(value: str) -> str:
    value = clean_text(value)
    value = value.replace("㎡", "m²").replace("m2", "m²").replace("m3", "m³")
    value = value.replace("M2", "m²").replace("M3", "m³")
    return re.sub(r"\s+", "", value)


def split_cells(text: str, starts: list[int], offset: int = 0) -> list[tuple[int, str]]:
    """Assign whitespace-separated tokens to the nearest quota-code column.

    Fixed-width slicing clips long names (for example "60m（14～19）").  When a
    row has exactly one token per code, document order is more reliable than
    character positions because the PDF sometimes compresses the name row.
    """
    tokens = list(re.finditer(r"\S+", text))
    if not tokens:
        return []
    if len(tokens) == len(starts):
        return [(i, token.group()) for i, token in enumerate(tokens)]

    centers = [start + 3 for start in starts]
    cells: list[tuple[int, str]] = []
    for token in tokens:
        center = offset + (token.start() + token.end()) / 2
        column = min(range(len(centers)), key=lambda i: abs(center - centers[i]))
        value = token.group()
        if cells and cells[-1][0] == column:
            cells[-1] = (column, cells[-1][1] + " " + value)
        else:
            cells.append((column, value))
    return cells


class QuotaText:
    def __init__(self, text: str):
        self.pages = text.split("\f")
        self.lines: list[str] = []
        self.line_pages: list[int] = []
        for page_no, page in enumerate(self.pages, 1):
            for line in page.splitlines():
                self.lines.append(line)
                self.line_pages.append(page_no)

        self.chapters: dict[int, str] = {}
        for line in self.lines[:250]:
            match = CHAPTER_RE.match(line.strip())
            if match:
                self.chapters[len(self.chapters) + 1] = match.group(1).strip().rstrip(".")

        self.section_headings: list[tuple[int, str, int]] = []
        for index, line in enumerate(self.lines):
            if "...." in line:
                continue
            match = SECTION_RE.match(line)
            if not match:
                continue
            try:
                prefix = int(match.group(1).split(".")[0])
            except ValueError:
                continue
            self.section_headings.append(
                (index, f"{match.group(1)} {match.group(2)}".strip(), prefix)
            )
        self.section_indices = [item[0] for item in self.section_headings]

    def chapter_name(self, number: int) -> str:
        title = self.chapters.get(number, "")
        # 目录把第十六章写成“其它零星工程”，正文标题为“其他零星工程”。
        if number == 16:
            title = title.replace("其它", "其他")
        return f"第{CN[number]}章 {title}".strip()

    def section_for(self, header_index: int, chapter_no: int) -> str:
        position = bisect.bisect_right(self.section_indices, header_index - 1) - 1
        while position >= 0:
            _, title, prefix = self.section_headings[position]
            if prefix == chapter_no:
                return title
            position -= 1
        return ""

    def work_content(self, header_index: int) -> str:
        for index in range(header_index - 1, max(-1, header_index - 12), -1):
            line = self.lines[index]
            if "工作内容" not in line:
                continue
            part = re.split(r"工作内容[：:]", line, maxsplit=1)[-1]
            part = re.split(r"计量单位[：:]", part, maxsplit=1)[0]
            parts = [clean_text(part)] if clean_text(part) else []
            for next_index in range(index + 1, header_index):
                next_line = self.lines[next_index]
                if not next_line.strip():
                    break
                if "计量单位" in next_line or ("编" in next_line and "号" in next_line):
                    break
                if SECTION_RE.match(next_line):
                    break
                if next_line.strip() in ("2", "3"):
                    continue
                parts.append(clean_text(next_line))
            return " ".join(part for part in parts if part)
        return ""

    def coefficient_items(self) -> list[dict[str, object]]:
        """解析第二十章的超高降效系数表。

        该章表格不以“编 号”作表头，而是用“子目”，也没有“类别/名称/消耗量”
        行和工作内容。每个表列出 6 个高度区间，每个编号对应一个人工降效系数。
        旧逻辑只识别“编 号”表头，导致 20-1～20-18 全部漏收。
        """
        title = ""
        results: list[dict[str, object]] = []
        for index, line in enumerate(self.lines):
            if "建筑工程超高人工降效系数" in line:
                title = clean_text(line)
            if not re.match(r"^\s*子目\s", line):
                continue
            codes = CODE_RE.findall(line)
            if not codes:
                continue

            unit = ""
            for near in range(index - 1, max(-1, index - 9), -1):
                match = re.search(r"计量单位[：:]\s*(\S+)", self.lines[near])
                if match:
                    unit = norm_unit(match.group(1))
                    break

            heights: list[str] = []
            layers: list[str] = []
            coefficients: list[str] = []
            for near in range(index + 1, min(index + 16, len(self.lines))):
                row = self.lines[near]
                if re.match(r"^\s*子目\s", row):
                    break
                tokens = row.split()
                if not tokens:
                    continue
                if "人工降效" in row and "人工费" in row:
                    coefficients = tokens[-len(codes):]
                elif "～" in row and tokens[0].startswith(("（", "(")):
                    layers = tokens[-len(codes):]
                elif "项目" in row and "～" in row:
                    heights = tokens[-len(codes):]
            if not (len(heights) == len(layers) == len(coefficients) == len(codes)):
                continue

            chapter_no = int(codes[0].split("-")[0])
            for column, code in enumerate(codes):
                layer = layers[column].strip("（）()")
                results.append(
                    {
                        "定额编号": code,
                        "定额子目名称": f"{title}·{heights[column]}m（{layer}层）",
                        "计量单位": unit or "%",
                        "章": self.chapter_name(chapter_no),
                        "节": "20.2 建筑工程超高人工降效系数",
                        "页码": self.line_pages[index],
                        "工作内容": "",
                        "备注": f"人工降效系数{coefficients[column]}%，计算基础为人工费。",
                    }
                )
        return results

    def parse(self) -> list[dict[str, object]]:
        items: list[dict[str, object]] = []
        last_work = ""

        for index, line in enumerate(self.lines):
            if not ("编" in line and "号" in line):
                continue
            matches = list(CODE_RE.finditer(line))
            if not matches:
                continue
            codes = [match.group(1) for match in matches]
            starts = [match.start() for match in matches]

            end = None
            for next_index in range(index + 1, min(index + 45, len(self.lines))):
                candidate = self.lines[next_index]
                if "类别" in candidate and "名称" in candidate and "消耗量" in candidate:
                    end = next_index
                    break
            if end is None:
                end = min(index + 28, len(self.lines))

            global_unit = ""
            unit_line_index = None
            for next_index in range(index - 1, max(-1, index - 16), -1):
                if "计量单位" in self.lines[next_index]:
                    match = re.search(r"计量单位[：:]\s*(.+?)\s*$", self.lines[next_index])
                    if match:
                        global_unit = norm_unit(match.group(1))
                        unit_line_index = next_index
                    break
            if global_unit.endswith("m") and unit_line_index is not None:
                for near in (unit_line_index - 1, unit_line_index + 1, unit_line_index - 2, unit_line_index + 2):
                    if 0 <= near < len(self.lines) and self.lines[near].strip() in ("2", "3"):
                        global_unit = norm_unit(global_unit + self.lines[near].strip())
                        break

            shared: list[str] = []
            specific: list[list[str]] = [[] for _ in codes]
            units: list[list[str]] = [[] for _ in codes]

            for next_index in range(index + 1, end):
                row = self.lines[next_index]
                if not row.strip():
                    continue
                if "工作内容" in row or "计量单位" in row:
                    continue
                if "编" in row and "号" in row:
                    continue
                if "类别" in row and "名称" in row:
                    continue

                if re.search(r"单\s+位", row):
                    label = re.match(r"^\s*单\s+位\s*", row)
                    offset = label.end() if label else 0
                    cells = split_cells(row[offset:], starts, offset)
                    if len(cells) == 1:
                        unit = norm_unit(cells[0][1])
                        if unit and not global_unit:
                            global_unit = unit
                    else:
                        for column, value in cells:
                            value = norm_unit(value)
                            if value:
                                units[column].append(value)
                    continue

                is_item = bool(re.search(r"项\s+目", row))
                label = re.match(r"^\s*项\s+目\s*", row) if is_item else None
                offset = label.end() if label else 0
                raw_text = row[offset:]
                text = clean_text(raw_text)
                if not text:
                    continue
                if text.startswith("注") or SECTION_RE.match(text):
                    continue

                cells = split_cells(raw_text, starts, offset)
                if len(cells) <= 1:
                    if text not in ("项 目", "单 位", "消耗量"):
                        shared.append(text)
                else:
                    for column, value in cells:
                        value = clean_text(value)
                        if value and value not in ("项 目", "单 位", "消耗量"):
                            specific[column].append(value)

            for column in range(len(codes)):
                if not units[column]:
                    continue
                unit = " ".join(units[column])
                if unit == "m":
                    for next_index in range(index + 1, end):
                        if self.lines[next_index].strip() in ("2", "3"):
                            unit = "m" + self.lines[next_index].strip()
                            break
                units[column] = [norm_unit(unit)]

            chapter_no = int(codes[0].split("-")[0])
            section = self.section_for(index, chapter_no)
            section_title = re.sub(r"^\d+(?:\.\d+)+\s*", "", section).strip()

            work = self.work_content(index)
            if work in ("同前。", "同前", "同上。", "同上"):
                work = last_work
            elif work:
                last_work = work

            for column, code in enumerate(codes):
                parts: list[str] = []
                if section_title:
                    parts.append(section_title)
                parts.extend(shared)
                parts.extend(specific[column])
                name_parts: list[str] = []
                for part in parts:
                    part = clean_text(part)
                    if part and part not in name_parts:
                        name_parts.append(part)
                name = "·".join(name_parts)
                if len(name) > 160:
                    name = name[:157] + "…"
                unit = units[column][0] if units[column] else global_unit
                items.append(
                    {
                        "定额编号": code,
                        "定额子目名称": name,
                        "计量单位": unit,
                        "章": self.chapter_name(chapter_no),
                        "节": section,
                        "页码": self.line_pages[index],
                        "工作内容": work,
                    }
                )

        items.extend(self.coefficient_items())
        # 现有条目按正文顺序生成，页码单调不减；稳定排序只把补收的第二十章
        # 系数表插回 733 页，不改变同页条目的先后。
        items.sort(key=lambda item: int(item["页码"]))

        seen: set[str] = set()
        unique: list[dict[str, object]] = []
        for item in items:
            code = str(item["定额编号"])
            if code in seen:
                continue
            seen.add(code)
            unique.append(item)
        return unique


def load_preserved(path: Path | None) -> dict[str, dict[str, str]]:
    """按定额编号保留已有主表中的核对结论。"""
    if path is None or not path.exists():
        return {}
    raw = path.read_bytes()
    for encoding in ("utf-8-sig", "utf-8", "gb18030"):
        try:
            text = raw.decode(encoding)
            break
        except UnicodeDecodeError:
            continue
    else:
        raise SystemExit(f"无法解码已有主表：{path}")
    kept: dict[str, dict[str, str]] = {}
    for row in csv.DictReader(text.splitlines()):
        code = (row.get("定额编号") or "").strip()
        if not code:
            continue
        kept[code] = {
            key: (row.get(key) or "").strip()
            for key in VERIFY_FIELDS
            if (row.get(key) or "").strip()
        }
    return kept


def write_master(
    items: list[dict[str, object]],
    preserved: dict[str, dict[str, str]],
    out: Path,
) -> list[dict[str, str]]:
    name_counts = Counter(str(item["定额子目名称"]) for item in items)
    rows: list[dict[str, str]] = []
    for number, item in enumerate(items, 1):
        code = str(item["定额编号"])
        name = str(item["定额子目名称"])
        unit = str(item["计量单位"])
        work = str(item["工作内容"])
        notes: list[str] = []
        if item.get("备注"):
            notes.append(str(item["备注"]))
        if unit == "见表":
            notes.append("计量单位见表，需回查原文")
        if not work and not str(item.get("备注", "")).startswith("人工降效系数"):
            notes.append("工作内容未提取，需回查原文")
        if len(name) < 4:
            notes.append("名称过短，需回查原文")
        if name_counts[name] > 1:
            notes.append("同名子目，需按页码/项目特征区分")
        row = {
            "序号": str(number),
            "定额编号": code,
            "定额子目名称": name,
            "计量单位": unit,
            "章": str(item["章"]),
            "节": str(item["节"]),
            "页码": str(item["页码"]),
            "工作内容": work,
            "数据来源": "2026消耗量官方PDF",
            "核对状态": "待核对",
            "核对方式": "",
            "核对人": "",
            "核对日期": "",
            "核对批次": "",
            "原文摘录": "",
            "证据ID": "",
            "备注": "；".join(notes),
        }
        for key, value in preserved.get(code, {}).items():
            row[key] = value
        rows.append(row)

    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(rows)
    return rows


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--text", type=Path, help="pdftotext -layout 生成的文本文件")
    parser.add_argument("--pdf", type=Path, help="官方 PDF；未给 --text 时调用 pdftotext")
    parser.add_argument(
        "--preserve-from",
        type=Path,
        default=BASE / "data" / "quota_2026_jiangsu.csv",
        help="从该主表按定额编号继承核对状态",
    )
    parser.add_argument("--no-preserve", action="store_true", help="不继承已有核对结论")
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT, help="输出定额主表")
    parser.add_argument("--raw-json", type=Path, help="可选：同时输出解析后的原始 JSON")
    args = parser.parse_args()

    temp_path: Path | None = None
    try:
        text_path = args.text
        if text_path is None:
            if args.pdf is None:
                parser.error("必须提供 --text 或 --pdf")
            temp = tempfile.NamedTemporaryFile(suffix=".txt", delete=False)
            temp.close()
            temp_path = Path(temp.name)
            subprocess.run(["pdftotext", "-layout", str(args.pdf), str(temp_path)], check=True)
            text_path = temp_path

        text = text_path.read_text(encoding="utf-8")
        items = QuotaText(text).parse()
        preserved = {} if args.no_preserve else load_preserved(args.preserve_from)
        rows = write_master(items, preserved, args.out)

        if args.raw_json:
            import json
            args.raw_json.write_text(json.dumps(items, ensure_ascii=False, indent=1), encoding="utf-8")

        status = Counter(row["核对状态"] for row in rows)
        print(f"唯一子目：{len(items)}")
        print("核对状态：" + "，".join(f"{k} {v}" for k, v in status.items()))
        print(f"有备注：{sum(1 for row in rows if row['备注'])}")
        print(f"输出：{args.out}")
        return 0
    finally:
        if temp_path is not None:
            temp_path.unlink(missing_ok=True)


if __name__ == "__main__":
    raise SystemExit(main())
