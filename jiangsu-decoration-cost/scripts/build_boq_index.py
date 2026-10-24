#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Build the full GB/T 50854-2024 BOQ index with Jiangsu 2025 No.12 additions.

Input is the public HTML full text of GB/T 50854-2024. The official PDF is a
scanned image PDF; this parser uses the HTML for the table structure and keeps
the official PDF/OCR as a cross-check. Jiangsu additions are transcribed from
the official attachment of 苏建价〔2025〕第12号 (2025-12-19).

Usage:
  python3 scripts/build_boq_index.py --html 50854.html --out data/boq_2024_jiangsu_index.csv
"""

from __future__ import annotations

import argparse
import csv
import re
from collections import Counter
from pathlib import Path

from bs4 import BeautifulSoup

FIELDS = [
    "序号", "清单编码", "清单名称", "计量单位", "附录", "节", "表号",
    "项目特征", "工程量计算规则", "工作内容", "名称质量", "数据来源", "江苏差异", "备注",
]

# 江苏省住建厅〔2025〕第12号公告附件1、2：国标未列、江苏增补的清单项。
JIANGSU_ADDITIONS = [
    {
        "清单编码": "010103003", "清单名称": "建筑垃圾外运", "计量单位": "t",
        "附录": "附录A 土石方工程", "节": "A.3 平整场地及其他", "表号": "江苏增补（附件1）",
        "项目特征": "建筑垃圾类别",
        "工程量计算规则": "按建筑垃圾质量计算",
        "工作内容": "1.装卸；2.外运；3.消纳",
        "名称质量": "江苏增补（已核对）",
        "数据来源": "江苏省住建厅〔2025〕第12号公告 附件1",
        "江苏差异": "江苏增补；GB/T 50854-2024 无此清单编码",
        "备注": "仅指工程垃圾、拆除垃圾、装修垃圾；工程渣土、工程泥浆按余方弃置/泥浆外运列项。",
    },
    {
        "清单编码": "011601016", "清单名称": "按质论价", "计量单位": "项",
        "附录": "附录R 措施项目", "节": "R.1 措施项目", "表号": "江苏增补（附件2）",
        "项目特征": "",
        "工程量计算规则": "",
        "工作内容": "招标文件或施工合同有质量目标时，以达到质量目标为费用计列条件的施工措施投入。",
        "名称质量": "江苏增补（已核对）",
        "数据来源": "江苏省住建厅〔2025〕第12号公告 附件2",
        "江苏差异": "江苏增补；GB/T 50854-2024 无此清单编码",
        "备注": "措施项目按项计取；江苏公告增补。",
    },
    {
        "清单编码": "011601017", "清单名称": "建筑工人实名制", "计量单位": "项",
        "附录": "附录R 措施项目", "节": "R.1 措施项目", "表号": "江苏增补（附件2）",
        "项目特征": "",
        "工程量计算规则": "",
        "工作内容": "施工现场对人员进行实名制管理，包括封闭式施工现场的进出场门禁系统和生物识别电子卡设备，非封闭式施工现场的移动定位、电子围栏考勤管理设备，现场显示屏，实名制系统使用以及管理等。",
        "名称质量": "江苏增补（已核对）",
        "数据来源": "江苏省住建厅〔2025〕第12号公告 附件2",
        "江苏差异": "江苏增补；GB/T 50854-2024 无此清单编码",
        "备注": "措施项目按项计取；江苏公告增补。",
    },
    {
        "清单编码": "011601018", "清单名称": "特殊施工降效", "计量单位": "项",
        "附录": "附录R 措施项目", "节": "R.1 措施项目", "表号": "江苏增补（附件2）",
        "项目特征": "",
        "工程量计算规则": "",
        "工作内容": "1.城镇老旧小区改造项目、历史文化街区改造项目施工时，由于施工场地非封闭式，施工受行车、行人的干扰导致的人工、机械降效以及为了行车、行人安全发生的防护设施（不包括防护通道）与疏导人员。2.城镇老旧小区改造项目、历史文化街区改造项目施工时，为了不干扰住户的正常作息时间，每天的施工时长缩短而增加的施工降效。",
        "名称质量": "江苏增补（已核对）",
        "数据来源": "江苏省住建厅〔2025〕第12号公告 附件2",
        "江苏差异": "江苏增补；GB/T 50854-2024 无此清单编码",
        "备注": "城镇老旧小区改造、历史文化街区改造发生时可计列；其他城市更新改造项目确需发生时可参照。",
    },
    {
        "清单编码": "011601019", "清单名称": "协管", "计量单位": "项",
        "附录": "附录R 措施项目", "节": "R.1 措施项目", "表号": "江苏增补（附件2）",
        "项目特征": "",
        "工程量计算规则": "",
        "工作内容": "城镇老旧小区改造项目、历史文化街区改造项目施工时，由承包人负责的监管协调违建拆除及恢复工作。",
        "名称质量": "江苏增补（已核对）",
        "数据来源": "江苏省住建厅〔2025〕第12号公告 附件2",
        "江苏差异": "江苏增补；GB/T 50854-2024 无此清单编码",
        "备注": "城镇老旧小区改造、历史文化街区改造发生时可计列；其他城市更新改造项目确需发生时可参照。",
    },
]

SEED_CODES = set()
SEED_PATH = Path(__file__).resolve().parent.parent / "data" / "boq_2024_jiangsu.csv"


def norm(value: str) -> str:
    value = value.replace("\xa0", " ")
    value = re.sub(r"[ \t\r\f\v]+", " ", value)
    value = re.sub(r" *\n *", "\n", value)
    value = re.sub(r"\n+", "\n", value)
    return value.strip()


def compact(value: str) -> str:
    return re.sub(r"\s+", "", norm(value))


CLAUSE_STARTERS = (
    "板与", "墙与", "柱与", "梁与", "楼(地)面", "屋面", "墙面", "天棚", "门窗",
    "楼梯", "台阶", "基础", "阳台", "雨篷", "其他", "设计", "施工", "工程",
    "清单", "项目", "计算", "不应", "不得", "可按", "应按", "需按", "如需",
    "若", "当", "每", "各", "其", "该", "本", "并", "在", "对", "由", "经",
    "从", "为", "是", "有", "无",
)


def clean_lines(value: str, sep: str = "；") -> str:
    """Normalize PDF/HTML line wrapping while keeping list-item boundaries.

    A new line that starts with a list marker (1. / （1） / 一、) starts a new
    item; a line starting with a common clause starter also starts a new item.
    Other lines are treated as wrapped continuations of the previous item.
    """
    lines = [compact(x) for x in norm(value).splitlines() if compact(x)]
    if not lines:
        return ""
    marker = re.compile(r"^(?:\d+[.．、]|[（(]\d+[)）]|[一二三四五六七八九十]+[、.])")
    out: list[str] = []
    for line in lines:
        line = re.sub(r"(?<=\d)\.(?=\D)", ".", line)
        if not out:
            out.append(line)
        elif marker.match(line) or (not out[-1].endswith(("。", "；", "：", "，", "、")) and line.startswith(CLAUSE_STARTERS)):
            out[-1] = out[-1].rstrip("；")
            out.append(line)
        else:
            out[-1] += line
    return sep.join(out).strip("；")

def clean_rule(value: str) -> str:
    """Rules are prose with optional numbered sub-clauses."""
    return clean_lines(value)


def table_grid(table) -> list[tuple[dict[int, str], set[int]]]:
    rows: list[tuple[dict[int, str], set[int]]] = []
    spans: dict[int, tuple[int, str]] = {}
    for tr in table.find_all("tr"):
        cells = tr.find_all(["th", "td"])
        if cells and all(c.name == "th" for c in cells):
            continue
        row: dict[int, str] = {}
        explicit: set[int] = set()
        col = 0
        idx = 0
        while idx < len(cells) or any(c >= col for c in spans):
            if col in spans:
                rem, text = spans[col]
                row[col] = text
                if rem <= 1:
                    del spans[col]
                else:
                    spans[col] = (rem - 1, text)
                col += 1
                continue
            if idx >= len(cells):
                break
            cell = cells[idx]
            idx += 1
            text = norm(cell.get_text("\n", strip=True))
            colspan = int(cell.get("colspan", 1))
            rowspan = int(cell.get("rowspan", 1))
            for k in range(colspan):
                row[col + k] = text
                explicit.add(col + k)
                if rowspan > 1:
                    spans[col + k] = (rowspan - 1, text)
            col += colspan
        while col in spans:
            rem, text = spans[col]
            row[col] = text
            if rem <= 1:
                del spans[col]
            else:
                spans[col] = (rem - 1, text)
            col += 1
        if row:
            rows.append((row, explicit))
    return rows


def parse_national(html_path: Path) -> list[dict[str, str]]:
    soup = BeautifulSoup(html_path.read_text(encoding="utf-8"), "html.parser")
    elements = list(soup.find_all(["h2", "h3", "p", "table"]))
    current_h2 = current_h3 = current_caption = ""
    meta: dict[int, tuple[str, str, str]] = {}
    for el in elements:
        if el.name == "h2":
            current_h2 = compact(el.get_text(" ", strip=True))
        elif el.name == "h3":
            current_h3 = compact(el.get_text(" ", strip=True))
        elif el.name == "p":
            text = compact(el.get_text(" ", strip=True))
            if re.match(r"^表[A-R]\.?\d", text):
                current_caption = text
        elif el.name == "table":
            meta[id(el)] = (current_h2, current_h3, current_caption)

    records: list[dict[str, str]] = []
    last_code: str | None = None
    for table in soup.find_all("table"):
        headers = [compact(x.get_text(" ", strip=True)) for x in table.find_all("th")]
        if not headers or headers[0] != "项目编码":
            continue
        measure = "单位" in headers and "计量单位" not in headers
        h2, h3, caption = meta.get(id(table), ("", "", ""))
        current: dict[str, str] | None = None
        for row, explicit in table_grid(table):
            raw_code = norm(row.get(0, ""))
            match = re.fullmatch(r"(\d{9})", raw_code) if 0 in explicit else None
            if match:
                code = match.group(1)
                current = {
                    "清单编码": code,
                    "清单名称": compact(row.get(1, "")),
                    "计量单位": compact(row.get(2, "")) if measure else compact(row.get(3, "")),
                    "项目特征": "", "工程量计算规则": "", "工作内容": "",
                    "附录": h2, "节": h3, "表号": caption,
                }
                records.append(current)
                last_code = code
            elif current is None:
                if last_code is None:
                    continue
                current = {
                    "清单编码": last_code, "清单名称": "", "计量单位": "",
                    "项目特征": "", "工程量计算规则": "", "工作内容": "",
                    "附录": h2, "节": h3, "表号": caption,
                }
                records.append(current)
            if measure:
                feat = ""
                rule = ""
                work = norm(row.get(3, "")) if 3 in explicit else ""
            else:
                feat = norm(row.get(2, "")) if 2 in explicit else ""
                rule = norm(row.get(4, "")) if 4 in explicit else ""
                work = norm(row.get(5, "")) if 5 in explicit else ""
            for key, value in (("项目特征", feat), ("工程量计算规则", rule), ("工作内容", work)):
                if value:
                    current[key] = (current[key] + "\n" + value).strip() if current[key] else value
            if not current["清单名称"] and row.get(1):
                current["清单名称"] = compact(row.get(1, ""))
            if not current["计量单位"]:
                unit = compact(row.get(2, "")) if measure else compact(row.get(3, ""))
                if unit:
                    current["计量单位"] = unit

    merged: dict[str, dict[str, str]] = {}
    for record in records:
        code = record["清单编码"]
        if code not in merged:
            merged[code] = dict(record)
        else:
            for key in ("项目特征", "工程量计算规则", "工作内容"):
                if record[key]:
                    merged[code][key] = (merged[code][key] + "\n" + record[key]).strip()
            for key in ("清单名称", "计量单位", "附录", "节", "表号"):
                if not merged[code][key] and record[key]:
                    merged[code][key] = record[key]
    return list(merged.values())


def format_appendix(value: str) -> str:
    text = compact(value)
    match = re.match(r"附录([A-R])(.*)", text)
    if not match:
        return text
    return f"附录{match.group(1)} {match.group(2)}".strip()


def format_section(value: str) -> str:
    text = compact(value)
    match = re.match(r"([A-R])\.(\d+)(.*)", text)
    if not match:
        return text
    return f"{match.group(1)}.{match.group(2)} {match.group(3)}".strip()


def table_number(value: str) -> str:
    match = re.search(r"表([A-R]\.\d+\.\d+)", compact(value))
    return f"表{match.group(1)}" if match else compact(value)


def normalize_units(record: dict[str, str]) -> tuple[str, str]:
    unit = compact(record["计量单位"]).replace("m2", "m²").replace("m3", "m³")
    rule = record["工程量计算规则"]
    note = ""
    if not unit and record["清单编码"] in {"010506016", "010506017", "010506018", "010506019", "010506020", "010506021"}:
        unit = "t"
        note = "原表单位为跨行合并单元格t，网页文本未抓到；按同表钢筋项目补正。"
    elif unit == "m":
        if "体积" in rule:
            unit = "m³"
            note = "原文上标丢失，按计算规则“以体积计算”补正为m³。"
        elif "面积" in rule:
            unit = "m²"
            note = "原文上标丢失，按计算规则“以面积计算”补正为m²。"
    return unit, note


def build(html_path: Path) -> list[dict[str, str]]:
    national = parse_national(html_path)
    out: list[dict[str, str]] = []
    for record in national:
        record["附录"] = format_appendix(record["附录"])
        record["节"] = format_section(record["节"])
        record["表号"] = table_number(record["表号"])
        record["项目特征"] = clean_lines(record["项目特征"])
        record["工程量计算规则"] = clean_rule(record["工程量计算规则"])
        record["工作内容"] = clean_lines(record["工作内容"])
        unit, note = normalize_units(record)
        record["计量单位"] = unit
        record["名称质量"] = "已核对" if record["清单编码"] in SEED_CODES else "国标提取"
        record["数据来源"] = "GB/T 50854-2024"
        record["江苏差异"] = ""
        record["备注"] = note
        if record["清单编码"] in SEED_CODES:
            record["备注"] = (record["备注"] + "；" if record["备注"] else "") + "与项目26条种子库名称、单位核对一致。"
        if record["清单编码"].startswith("0116"):
            record["江苏差异"] = "江苏公告：高层/超高层施工措施费不单独列项；另增补011601016-011601019。"
        out.append(record)

    existing = {r["清单编码"] for r in out}
    for record in JIANGSU_ADDITIONS:
        if record["清单编码"] in existing:
            raise SystemExit(f"江苏增补编码与国标重复：{record['清单编码']}")
        out.append(dict(record))
    out.sort(key=lambda r: r["清单编码"])
    for i, record in enumerate(out, 1):
        record["序号"] = str(i)
    return out


def load_seed_codes() -> set[str]:
    if not SEED_PATH.exists():
        return set()
    with SEED_PATH.open(encoding="utf-8-sig", newline="") as fh:
        return {row["清单编码"].strip() for row in csv.DictReader(fh) if row.get("清单编码")}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--html", type=Path, required=True, help="GB/T 50854-2024 全文 HTML")
    parser.add_argument("--out", type=Path, default=Path(__file__).resolve().parent.parent / "data" / "boq_2024_jiangsu_index.csv")
    parser.add_argument("--seed", type=Path, default=Path(__file__).resolve().parent.parent / "data" / "boq_2024_jiangsu.csv")
    args = parser.parse_args()

    global SEED_CODES, SEED_PATH
    SEED_PATH = args.seed
    SEED_CODES = load_seed_codes()
    rows = build(args.html)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("w", encoding="utf-8-sig", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(rows)

    counts = Counter(r["名称质量"] for r in rows)
    print(f"写入 {args.out}：{len(rows)} 条")
    print("质量分层：" + "，".join(f"{k} {v}" for k, v in counts.items()))
    print(f"国标编码 {sum(1 for r in rows if r['数据来源'] == 'GB/T 50854-2024')} 条；江苏增补 {len(JIANGSU_ADDITIONS)} 条")
    nine_digit = sum(1 for r in rows if re.fullmatch(r"\d{9}", r["清单编码"]))
    print(f"唯一编码 {len({r['清单编码'] for r in rows})} 条；9位编码 {nine_digit} 条")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
