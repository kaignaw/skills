#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Build the 2026 Jiangsu quota lookup index from the official PDF text.

The official 2026 consumption PDF has a text layer, but its tables use merged
headers, superscripts and multi-column names.  This script extracts one row per
unique quota code and keeps the physical PDF page number so every automatically
extracted name can be checked against the original.

Typical use:
  pdftotext -layout js2026.pdf js2026.txt
  python3 scripts/build_quota_index.py --text js2026.txt

Or let the script call pdftotext:
  python3 scripts/build_quota_index.py --pdf js2026.pdf

The 59 verified seed rows are used to override names/units for the project
subset.  All other rows are marked "自动提取" and must be verified by page before
being used as a formal quota name.
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
DEFAULT_SEED = BASE / "data" / "quota_2026_jiangsu_seed.csv"
DEFAULT_OUT = BASE / "data" / "quota_2026_jiangsu_index.csv"

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
        return f"第{CN[number]}章 {self.chapters.get(number, '')}".strip()

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

        seen: set[str] = set()
        unique: list[dict[str, object]] = []
        for item in items:
            code = str(item["定额编号"])
            if code in seen:
                continue
            seen.add(code)
            unique.append(item)
        return unique


def read_seed(path: Path | None) -> dict[str, dict[str, str]]:
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
        raise SystemExit(f"无法解码种子库：{path}")
    return {row["定额编号"]: row for row in csv.DictReader(text.splitlines())}


def write_index(items: list[dict[str, object]], seed: dict[str, dict[str, str]], out: Path) -> list[list[str]]:
    name_counts = Counter(str(item["定额子目名称"]) for item in items)
    headers = [
        "序号", "定额编号", "定额子目名称", "计量单位", "章", "节", "页码",
        "工作内容", "名称质量", "数据来源", "备注",
    ]
    rows: list[list[str]] = []
    for number, item in enumerate(items, 1):
        code = str(item["定额编号"])
        if code in seed:
            verified = seed[code]
            name = verified["定额子目名称"]
            unit = verified["计量单位"]
            chapter = verified["章"]
            section = verified["节"]
            work = verified["工作内容"]
            quality = "已核对"
            source = "项目种子库"
            note = "已核对；全量索引中的同名条目以此为准"
        else:
            name = str(item["定额子目名称"])
            unit = str(item["计量单位"])
            chapter = str(item["章"])
            section = str(item["节"])
            work = str(item["工作内容"])
            quality = "自动提取"
            source = "2026消耗量官方PDF"
            notes: list[str] = []
            if unit == "见表":
                notes.append("计量单位见表，需回查原文")
            if not work:
                notes.append("工作内容未提取，需回查原文")
            if len(name) < 4:
                notes.append("名称过短，需回查原文")
            if name_counts[name] > 1:
                notes.append("同名子目，需按页码/项目特征区分")
            note = "；".join(notes)
        rows.append(
            [
                str(number), code, name, unit, chapter, section, str(item["页码"]),
                work, quality, source, note,
            ]
        )

    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(headers)
        writer.writerows(rows)
    return rows


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--text", type=Path, help="pdftotext -layout 生成的文本文件")
    parser.add_argument("--pdf", type=Path, help="官方 PDF；未给 --text 时调用 pdftotext")
    parser.add_argument("--seed", type=Path, default=DEFAULT_SEED, help="59 条已核对种子库")
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT, help="输出索引 CSV")
    parser.add_argument("--no-seed", action="store_true", help="不使用种子库覆盖")
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
        seed = {} if args.no_seed else read_seed(args.seed)
        rows = write_index(items, seed, args.out)

        if args.raw_json:
            import json
            args.raw_json.write_text(json.dumps(items, ensure_ascii=False, indent=1), encoding="utf-8")

        print(f"唯一子目：{len(items)}")
        print(f"已核对：{sum(1 for row in rows if row[8] == '已核对')}")
        print(f"自动提取：{sum(1 for row in rows if row[8] == '自动提取')}")
        print(f"有备注：{sum(1 for row in rows if row[10])}")
        print(f"输出：{args.out}")
        return 0
    finally:
        if temp_path is not None:
            temp_path.unlink(missing_ok=True)


if __name__ == "__main__":
    raise SystemExit(main())
