#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Build the full GB/T 50854-2024 BOQ index with Jiangsu 2025 No.12 additions.

Input is the public HTML full text of GB/T 50854-2024. The official PDF is a
scanned image PDF; this parser uses the HTML for the table structure and keeps
the official PDF/OCR as a cross-check. Jiangsu additions are transcribed from
the official attachment of 苏建价〔2025〕第12号 (2025-12-19).

The output is the single authoritative BOQ master table (477 rows).  Rows that
already carry verification data in the existing master table are preserved by
清单编码, so rebuilding the table never silently drops a reviewed row back to
"待核对".  A row without preserved evidence is written as "待核对" and must be
checked against the official PDF page before formal use.

Usage:
  python3 scripts/build_boq_index.py --html 50854.html
  python3 scripts/build_boq_index.py --html 50854.html --out /tmp/boq.csv --no-preserve
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
    "项目特征", "工程量计算规则", "工作内容", "数据来源", "江苏差异",
    "核对状态", "核对方式", "核对人", "核对日期", "核对批次",
    "原文页码", "原文摘录", "证据ID", "备注",
]

VERIFY_FIELDS = [
    "核对状态", "核对方式", "核对人", "核对日期", "核对批次",
    "原文页码", "原文摘录", "证据ID",
]

AUDIT_BATCH = "audit-2026-10-29"
AUDIT_DATE = "2026-10-29"

# 江苏省住建厅〔2025〕第12号公告附件1、2：国标未列、江苏增补的清单项。
JIANGSU_ADDITIONS = [
    {
        "清单编码": "010103003", "清单名称": "建筑垃圾外运", "计量单位": "t",
        "附录": "附录A 土石方工程", "节": "A.3 平整场地及其他", "表号": "江苏增补（附件1）",
        "项目特征": "建筑垃圾类别",
        "工程量计算规则": "按建筑垃圾质量计算",
        "工作内容": "1.装卸；2.外运；3.消纳",
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
        "数据来源": "江苏省住建厅〔2025〕第12号公告 附件2",
        "江苏差异": "江苏增补；GB/T 50854-2024 无此清单编码",
        "备注": "城镇老旧小区改造、历史文化街区改造发生时可计列；其他城市更新改造项目确需发生时可参照。",
    },
]

# 网页全文的附录 H 标题缺失（只有“附录 H”），用官方 PDF 目录补全。
APPENDIX_TITLES = {"H": "门窗工程"}


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
    title = match.group(2).strip() or APPENDIX_TITLES.get(match.group(1), "")
    return f"附录{match.group(1)} {title}".strip()


def format_section(value: str) -> str:
    text = compact(value)
    # 网页 H.2 标题带一个竖线伪字符“金属╱门”，官方 PDF 为“金属门”。
    text = text.replace("╱", "").replace("／", "")
    match = re.match(r"([A-R])\.(\d+)(.*)", text)
    if not match:
        return text
    return f"{match.group(1)}.{match.group(2)} {match.group(3)}".strip()


def repair_section(section: str, appendix: str, table_no: str, caption: str) -> str:
    """用表号纠正网页缺失/串位的节标题。

    网页全文缺少 H.1 的 h3 标题，并把 010801001～010801006 归到了上一节
    “G.4 其他规定”。表号 H.1.1 和表题“木门”仍可靠，因此按表号回填节标题。
    """
    section = section.replace("╱", "").replace("／", "")
    table = re.search(r"表([A-R])\.(\d+)\.\d+", compact(table_no))
    if not table:
        return section
    letter, number = table.group(1), table.group(2)
    expected = f"{letter}.{number}"
    if section.startswith(expected + " ") or section == expected:
        if appendix.startswith(f"附录{letter}"):
            return section

    title = ""
    caption_match = re.match(
        rf"表{re.escape(letter)}\.{re.escape(number)}\.\d+(.*)", compact(caption)
    )
    if caption_match:
        title = re.split(r"[（(]编码", caption_match.group(1), maxsplit=1)[0].strip()
    if not title:
        current = re.match(r"^[A-R]\.\d+\s*(.*)$", section)
        title = current.group(1).strip() if current else ""
    return f"{expected} {title}".strip()


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
        caption = record["表号"]
        record["附录"] = format_appendix(record["附录"])
        record["节"] = format_section(record["节"])
        record["表号"] = table_number(caption)
        record["节"] = repair_section(record["节"], record["附录"], record["表号"], caption)
        record["项目特征"] = clean_lines(record["项目特征"])
        record["工程量计算规则"] = clean_rule(record["工程量计算规则"])
        record["工作内容"] = clean_lines(record["工作内容"])
        unit, note = normalize_units(record)
        record["计量单位"] = unit
        record["数据来源"] = "GB/T 50854-2024"
        record["江苏差异"] = ""
        record["备注"] = note
        for key in VERIFY_FIELDS:
            record[key] = ""
        record["核对状态"] = "待核对"
        if record["清单编码"].startswith("0116"):
            record["江苏差异"] = "江苏公告：高层/超高层施工措施费不单独列项；另增补011601016-011601019。"
        out.append(record)

    existing = {r["清单编码"] for r in out}
    for record in JIANGSU_ADDITIONS:
        if record["清单编码"] in existing:
            raise SystemExit(f"江苏增补编码与国标重复：{record['清单编码']}")
        addition = dict(record)
        for key in VERIFY_FIELDS:
            addition[key] = ""
        addition.update(
            {
                "核对状态": "已核对",
                "核对方式": "官方公告附件逐条核对",
                "核对人": "audit",
                "核对日期": AUDIT_DATE,
                "核对批次": AUDIT_BATCH,
                "原文摘录": f"{addition['清单编码']} {addition['清单名称']} {addition['计量单位']}",
                "证据ID": f"EV-BOQ-{addition['清单编码']}",
            }
        )
        out.append(addition)
    out.sort(key=lambda r: r["清单编码"])
    for i, record in enumerate(out, 1):
        record["序号"] = str(i)
    return out


def load_preserved(path: Path | None) -> dict[str, dict[str, str]]:
    """按清单编码保留已有主表中的核对结论和原文页码。"""
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
    rows = list(csv.DictReader(text.splitlines()))
    if not rows:
        return {}
    kept: dict[str, dict[str, str]] = {}
    for row in rows:
        code = (row.get("清单编码") or "").strip()
        if not code:
            continue
        kept[code] = {
            key: (row.get(key) or "").strip()
            for key in VERIFY_FIELDS
            if (row.get(key) or "").strip()
        }
    return kept


def main() -> int:
    base = Path(__file__).resolve().parent.parent
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--html", type=Path, required=True, help="GB/T 50854-2024 全文 HTML")
    parser.add_argument("--out", type=Path, default=base / "data" / "boq_2024_jiangsu.csv", help="输出清单主表")
    parser.add_argument(
        "--preserve-from",
        type=Path,
        default=base / "data" / "boq_2024_jiangsu.csv",
        help="从该主表按清单编码继承核对状态/原文页码",
    )
    parser.add_argument("--no-preserve", action="store_true", help="不继承已有核对结论")
    args = parser.parse_args()

    rows = build(args.html)
    preserved = {} if args.no_preserve else load_preserved(args.preserve_from)
    for record in rows:
        for key, value in preserved.get(record["清单编码"], {}).items():
            record[key] = value

    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("w", encoding="utf-8-sig", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(rows)

    status = Counter(r["核对状态"] for r in rows)
    print(f"写入 {args.out}：{len(rows)} 条")
    print("核对状态：" + "，".join(f"{k} {v}" for k, v in status.items()))
    print(f"国标编码 {sum(1 for r in rows if r['数据来源'] == 'GB/T 50854-2024')} 条；江苏增补 {len(JIANGSU_ADDITIONS)} 条")
    nine_digit = sum(1 for r in rows if re.fullmatch(r"\d{9}", r["清单编码"]))
    print(f"唯一编码 {len({r['清单编码'] for r in rows})} 条；9位编码 {nine_digit} 条")
    missing_page = [r["清单编码"] for r in rows if not r["原文页码"]]
    if missing_page:
        print(f"缺少原文页码 {len(missing_page)} 条：{', '.join(missing_page)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
