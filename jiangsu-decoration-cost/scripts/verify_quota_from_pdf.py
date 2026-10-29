#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""用官方 PDF 的表格线 + 文字坐标逐列核对定额主表。

`build_quota_index.py` 用 `pdftotext -layout` 的整行文本、按字符列位切分名称；
本脚本是独立的第二条路径：用 pdfplumber 读取 PDF 的表格边框线，得到每一行表头
在“当前列”各自的单元格范围，再按编号所在列拼接名称。合并单元格（一个表头横跨
若干子目列）由线框天然区分，不依赖字符对齐猜测。

核对结论分三种：

  * 一致：单元格还原出的每一级都能在主表名称中找到 → 标 `已核对`，名称不动；
  * 可补全：主表除首段（节/表名）外的每一级都能在单元格里找到，但单元格多出
    若干级（主表漏级）→ 按单元格补全名称，标 `已核对` 并在备注记原名称；
  * 冲突：主表有单元格里找不到的层级（很可能是错列/错字）→ 保持 `待核对`，
    写入报告，交人工按页码复核。

用法：
  python3 scripts/verify_quota_from_pdf.py --pdf js2026.pdf --report work/quota_verify.csv
  python3 scripts/verify_quota_from_pdf.py --pdf js2026.pdf --apply

依赖：pdfplumber（`pip install pdfplumber`）。
"""

from __future__ import annotations

import argparse
import csv
import re
from collections import Counter
from datetime import date
from pathlib import Path

try:
    import pdfplumber
except ImportError:  # pragma: no cover
    raise SystemExit("需要 pdfplumber：pip install pdfplumber")

BASE = Path(__file__).resolve().parent.parent
DATA = BASE / "data"
MASTER = DATA / "quota_2026_jiangsu.csv"
EVIDENCE = DATA / "verification_evidence.csv"

PDF_SHA = "da0d02eeb9f2f8fd4e8434c392ab449ac9cc2c0eff522d3cdf93282357ff61dc"
PDF_URL = "http://jsszfhcxjst.jiangsu.gov.cn/art/2026/5/19/art_8639_11773294.html"
SOURCE_NAME = "江苏省建筑与装饰工程消耗量（2026）官方 PDF"
SOURCE_VERSION = "江苏省建筑与装饰工程消耗量（2026）"

CODE_RE = re.compile(r"^\d{1,2}-\d{1,4}$")
UNIT_LINE_RE = re.compile(r"计量单位[：:]\s*(\S+)")
UNIT_TOKEN_RE = re.compile(
    r"^\d*(?:\.\d+)?(?:m|m²|m³|㎡|m2|m3|t|kg|个|只|套|座|根|台班|台|组|副|块|樘|处|项|扇|台次|套天|天|%)$"
)
UNIT_LONG_RE = re.compile(
    r"^\d*(?:\.\d+)?(?:"
    r"(?:m|m²|m³|㎡|m2|m3)?(?:外形面积|水平投影面积|投影面积|展开面积|净面积|斜面积)"
    r")$"
)
ROW_LABELS = {
    "项", "目", "项目", "类别", "编码", "编号", "名称", "单", "位", "单位",
    "消耗量", "基础", "计算", "子目",
}
PUA_RE = re.compile(r"[\ue000-\uf8ff]")


def norm(text: str) -> str:
    text = (
        text.replace("（", "(").replace("）", ")")
        .replace("～", "~").replace("－", "-").replace("—", "-")
        .replace("　", "")
    )
    return re.sub(r"[\s·]", "", text).lower()


def loose(text: str) -> str:
    """比对用宽松形式：去掉私用区上下标字形和名称内的单位符号。"""
    text = PUA_RE.sub("", text)
    text = norm(text)
    for token in ("mm", "m²", "m³", "㎡", "m2", "m3", "m", "φ", "Φ", "ø"):
        text = text.replace(token, "")
    return text


def read_csv(path: Path) -> list[dict[str, str]]:
    raw = path.read_bytes()
    for encoding in ("utf-8-sig", "utf-8", "gb18030"):
        try:
            return list(csv.DictReader(raw.decode(encoding).splitlines()))
        except UnicodeDecodeError:
            continue
    raise SystemExit(f"无法解码：{path}")


class PageContext:
    """一页的表格线、文字行和编号位置，只解析一次。"""

    def __init__(self, page) -> None:
        self.page = page
        self.words = page.extract_words()
        self.chars = page.chars
        self.seps = [
            (float(line["x0"]), float(line["top"]), float(line["bottom"]))
            for line in page.lines
            if abs(line["x0"] - line["x1"]) < 0.7
        ]
        ordered = sorted(self.words, key=lambda word: (word["top"], word["x0"]))
        self.lines: list[list[dict]] = []
        for word in ordered:
            if self.lines and abs(word["top"] - self.lines[-1][0]["top"]) <= 4:
                self.lines[-1].append(word)
            else:
                self.lines.append([word])
        for line in self.lines:
            line.sort(key=lambda word: word["x0"])
        self.codes = [word for word in self.words if CODE_RE.match(word["text"])]

    def separators_at(self, y: float) -> list[float]:
        return sorted({round(x, 1) for x, top, bottom in self.seps if top - 0.6 <= y <= bottom + 0.6})

    def band_index(self, bands: list[float], x: float) -> int | None:
        for index in range(len(bands) - 1):
            if bands[index] <= x <= bands[index + 1]:
                return index
        return None


def undouble(text: str) -> str:
    """PDF 粗体字常被抽成重复字符（“桩桩、、柱柱”），折叠成单字符。"""
    out: list[str] = []
    index = 0
    while index < len(text):
        if index + 1 < len(text) and text[index] == text[index + 1]:
            out.append(text[index])
            index += 2
        else:
            out.append(text[index])
            index += 1
    return "".join(out)


def heading_text(ctx: PageContext, y: float) -> str:
    """表格上方的章节标题文字（含 5.2.1.1 桩、柱 之类的编号行）。"""
    parts: list[str] = []
    for line in ctx.lines:
        if float(line[0]["top"]) >= y:
            continue
        text = undouble("".join(word["text"] for word in line))
        if re.match(r"^\d+(?:\.\d+)+\s*\S", text.strip()):
            parts.append(text)
    return "".join(parts)


def text_of(words: list[dict]) -> str:
    return PUA_RE.sub("", "".join(word["text"] for word in words))


def overlap_length(x0: float, x1: float, left: float, right: float) -> float:
    return max(0.0, min(x1, right) - max(x0, left))


def span_of(bands: list[float], x: float) -> tuple[float, float] | None:
    for index in range(len(bands) - 1):
        if bands[index] <= x <= bands[index + 1]:
            return bands[index], bands[index + 1]
    return None


def column_text(
    ctx: PageContext,
    line: list[dict],
    line_bands: list[float],
    left: float,
    right: float,
    table_center: float = 0.0,
    column_width: float = 0.0,
) -> tuple[str, list[str]]:
    """一行表头在指定列里的文字，以及“跨列含糊、不能算数”的标签。

    表头单元格有合并：一格里可能是一条跨列标签，也可能是若干条被画成同一串
    文字的并列标签。判断依据是这一行的竖线：
      * 文字跨过竖线 → 并列标签，按字符横坐标切到各列（算数）；
      * 文字单元格整格落在本列内 → 本列标签（算数）；
      * 文字单元格横跨本列且盖满 → 合并标签，属于它盖住的每一列（算数）；
      * 文字单元格只搭到本列一部分 → 归属含糊，忽略并回报，交人工看。
    """
    pieces: list[tuple[float, str]] = []
    partial: list[str] = []
    for word in line:
        x0, x1 = float(word["x0"]), float(word["x1"])
        crossing = any(x0 + 1 < band < x1 - 1 for band in line_bands)
        if crossing:
            chars = [
                char for char in ctx.chars
                if x0 - 0.5 <= float(char["x0"]) and float(char["x1"]) <= x1 + 0.5
                and abs(float(char["top"]) - float(word["top"])) <= 1.5
                and left <= (float(char["x0"]) + float(char["x1"])) / 2 <= right
            ]
            text = PUA_RE.sub("", "".join(char["text"] for char in chars))
            if text:
                pieces.append((x0, text))
            continue
        span = span_of(line_bands, (x0 + x1) / 2)
        if span is None:
            continue
        centered = (
            table_center
            and abs((x0 + x1) / 2 - table_center) <= 3
            and (x1 - x0) >= column_width * 0.25
        )
        if centered:
            pieces.append((x0, PUA_RE.sub("", word["text"])))
            continue
        inside = span[0] >= left - 1 and span[1] <= right + 1
        covers = span[0] <= left + 1 and span[1] >= right - 1
        if inside or covers:
            pieces.append((x0, PUA_RE.sub("", word["text"])))
        elif overlap_length(span[0], span[1], left, right) > 1:
            partial.append(PUA_RE.sub("", word["text"]))
    pieces.sort(key=lambda item: item[0])
    return "".join(text for _, text in pieces).strip(), partial


def reconstruct(ctx: PageContext, code: str) -> dict | None:
    """还原某个定额编号所在列的各级表头和单位。"""
    target = next((word for word in ctx.codes if word["text"] == code), None)
    if target is None:
        return None
    y_code = (float(target["top"]) + float(target["bottom"])) / 2
    row = [
        word for word in ctx.codes
        if abs((float(word["top"]) + float(word["bottom"])) / 2 - y_code) <= 4
    ]
    bands = ctx.separators_at(y_code)
    if len(bands) < 3:
        return None
    index = ctx.band_index(bands, (float(target["x0"]) + float(target["x1"])) / 2)
    if index is None or index == 0:
        return None
    left, right = bands[index], bands[index + 1]
    center = (left + right) / 2
    first = min(
        (ctx.band_index(bands, (float(word["x0"]) + float(word["x1"])) / 2) or len(bands))
        for word in row
    )
    first = max(first, 1)
    table_center = (bands[first] + bands[-1]) / 2
    column_width = (bands[-1] - bands[first]) / max(len(bands) - first - 1, 1)

    stop = None
    for line in ctx.lines:
        if float(line[0]["top"]) <= y_code:
            continue
        if any("消耗量" in word["text"] for word in line):
            stop = float(line[0]["top"])
            break
    if stop is None:
        stop = y_code + 140

    levels: list[str] = []
    blob_parts: list[str] = []
    ambiguous: list[str] = []
    unit = ""
    for line in ctx.lines:
        top = float(line[0]["top"])
        if top <= y_code + 2 or top >= stop - 2:
            continue
        line_bands = ctx.separators_at((top + float(line[0]["bottom"])) / 2)
        text, partial = column_text(
            ctx, line, line_bands, left, right, table_center, column_width
        )
        ambiguous.extend(part for part in partial if part.strip())
        half = len(text) // 2
        if half and text == text[:half] * 2:
            text = text[:half]
        if not text:
            continue
        blob_parts.append(text)
        is_unit_row = any(
            word["text"] in ("单", "位", "单位") for word in line
        )
        if is_unit_row and (UNIT_TOKEN_RE.match(text) or UNIT_LONG_RE.match(text)):
            unit = unit or text
            continue
        if text in ROW_LABELS:
            continue
        levels.append(text)

    if not unit:
        for line in ctx.lines:
            if float(line[0]["top"]) >= y_code:
                continue
            text = " ".join(word["text"] for word in line)
            match = UNIT_LINE_RE.search(text)
            if match:
                unit = match.group(1)
    return {
        "tokens": levels,
        "blob": "".join(blob_parts),
        "ambiguous": ambiguous,
        "unit": unit,
        "center": center,
        "row_size": len(row),
    }


def matches(one: str, other: str) -> bool:
    return bool(one) and bool(other) and (one == other or one in other or other in one)


def is_subsequence(small: list[str], big: list[str]) -> bool:
    iterator = iter(big)
    return all(any(token == candidate for candidate in iterator) for token in small)


UNIT_FRAGMENT_RE = re.compile(
    r"^\d+(?:\.\d+)?$"
    r"|^\d*(?:\.\d+)?(?:m|m²|m³|㎡|m2|m3|t|kg|个|只|套|座|根|块|樘|处|项|台次|套天|天|扇)$"
)


def is_unit_fragment(token: str) -> bool:
    """名称里混入的纯单位/纯数字层级（如 m² 的“2”、多打的“10m”）。"""
    return bool(UNIT_FRAGMENT_RE.match(loose(token)))


def judge(
    master: str,
    tokens: list[str],
    blob: str = "",
    headings: str = "",
) -> tuple[str, list[str], str, bool]:
    """返回 (结论, 差异层级, 建议名称, 建议名称是否可直接采用)。

    一致：主表名称已经覆盖本列表头的每一级；
    可补全：表头多出主表没有的层级（主表漏级），或主表混入纯单位/纯数字层级。
            按表头顺序补级、去掉单位碎片，主表原有层级顺序不变；
    冲突：补级会打乱主表原有顺序，或主表正文整段对不上，交人工复核。
    """
    master_tokens = [part for part in master.split("·") if part.strip()]
    if not master_tokens:
        return "冲突", tokens, master, False
    master_loose = [loose(part) for part in master_tokens]
    cell_loose = [loose(part) for part in tokens]
    blob_loose = loose(blob)

    # 主表开头是表上方的章节标题（如“5.2.1.1 桩、柱”），它不在表头单元格里。
    prefix = 0
    while prefix < len(master_tokens) and master_loose[prefix] not in blob_loose:
        prefix += 1

    # 只删“本列表头里确实没有”的单位/数字碎片；表头里真有这一级（如 φ75、20、100t）必须保留。
    dropped = [
        master_tokens[index]
        for index in range(prefix, len(master_tokens))
        if is_unit_fragment(master_tokens[index])
        and master_loose[index] not in blob_loose
    ]
    body_indexes = [
        index for index in range(prefix, len(master_tokens))
        if master_tokens[index] not in dropped
    ]
    # 单位不是层级：单元格里只剩单位（如 10m2、m2）时不要当成名称补进主表。
    extra_cell = [
        token for position, token in enumerate(tokens)
        if not any(matches(cell_loose[position], item) for item in master_loose)
        and not UNIT_TOKEN_RE.match(token)
        and not UNIT_LONG_RE.match(token)
        and token.count("(") < 2
    ]

    if not extra_cell and not dropped:
        return "一致", [], master, False

    # 单元格 → 主表层级；未匹配的单元格层级插到它的下一级之前。
    cell_to_master: dict[int, int] = {}
    used: set[int] = set()
    for position, cell in enumerate(tokens):
        for index in body_indexes:
            if index in used:
                continue
            if matches(cell_loose[position], master_loose[index]):
                cell_to_master[position] = index
                used.add(index)
                break
    anchors: dict[int, list[str]] = {}
    pending: list[str] = []
    for position, cell in enumerate(tokens):
        if position in cell_to_master:
            anchor = cell_to_master[position]
            if pending:
                anchors.setdefault(anchor, []).extend(pending)
                pending = []
        elif not any(matches(cell_loose[position], item) for item in master_loose):
            pending.append(cell)
    tail = pending

    result = list(master_tokens[:prefix])
    for index in body_indexes:
        if index in anchors:
            result.extend(anchors[index])
        result.append(master_tokens[index])
    result.extend(tail)

    kept_master = [
        token for index, token in enumerate(master_tokens)
        if index < prefix or index in body_indexes
    ]
    if not is_subsequence(kept_master, result):
        return "冲突", extra_cell, master, False
    return "可补全", extra_cell or dropped, "·".join(result), True


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--pdf", type=Path, required=True, help="官方 PDF")
    parser.add_argument("--master", type=Path, default=MASTER)
    parser.add_argument("--evidence", type=Path, default=EVIDENCE)
    parser.add_argument("--report", type=Path, help="输出逐条比对明细 CSV")
    parser.add_argument("--batch", default=f"pdf-cell-audit-{date.today().isoformat()}")
    parser.add_argument("--apply", action="store_true", help="写回主表和证据表")
    parser.add_argument("--limit", type=int, default=0, help="只处理前 N 条待核对（调试用）")
    parser.add_argument("--only", default="", help="只处理指定编号（逗号分隔，调试用）")
    args = parser.parse_args()

    rows = read_csv(args.master)
    evidence_rows = read_csv(args.evidence) if args.evidence.exists() else []
    evidence_by_id = {row.get("证据ID", "").strip(): row for row in evidence_rows}
    known = set(evidence_by_id)

    only = {code.strip() for code in args.only.split(",") if code.strip()}
    pending = [
        row for row in rows
        if row.get("核对状态", "").strip() != "已核对" and (not only or row["定额编号"] in only)
    ]
    if args.limit:
        pending = pending[: args.limit]

    report: list[list[str]] = []
    verdicts = Counter()
    repaired: list[tuple[str, str, str]] = []
    cache: dict[int, PageContext] = {}

    with pdfplumber.open(args.pdf) as pdf:
        for row in pending:
            code = row["定额编号"].strip()
            page_no = int(row["页码"])
            if page_no not in cache:
                cache[page_no] = PageContext(pdf.pages[page_no - 1])
            ctx = cache[page_no]
            result = reconstruct(ctx, code)
            if result is None:
                verdicts["无法定位编号列"] += 1
                report.append([code, str(page_no), row["定额子目名称"], "", row["计量单位"], "", "无法定位编号列", ""])
                continue

            tokens = result["tokens"]
            verdict, diff, built, safe = judge(
                row["定额子目名称"],
                tokens,
                result["blob"],
                heading_text(ctx, (float(next(w for w in ctx.codes if w["text"] == code)["top"]))),
            )
            master_unit = row["计量单位"].strip()
            pdf_unit = result["unit"]
            unit_ok = (
                not master_unit
                or master_unit == "见表"
                or not pdf_unit
                or pdf_unit == "见表"
                or loose(master_unit) == loose(pdf_unit)
                or loose(pdf_unit).startswith(loose(master_unit))
            )
            reason = {
                "一致": "通过（名称一致）",
                "可补全": "通过（按单元格补全名称）",
                "冲突": "名称冲突：" + "、".join(diff),
            }[verdict]
            if not unit_ok:
                reason += f"；单位不一致：主表{master_unit}/原文{pdf_unit}"
                verdict = "冲突"

            if result["ambiguous"] and verdict != "冲突":
                reason += "；跨列合并标签（已忽略，需人工确认）：" + "、".join(result["ambiguous"])
            report.append([
                code, str(page_no), row["定额子目名称"], built, master_unit, pdf_unit,
                reason, "、".join(result["ambiguous"]),
            ])
            if verdict == "冲突":
                verdicts["名称冲突"] += 1
                continue
            verdicts["通过"] += 1

            if verdict == "可补全" and built and built != row["定额子目名称"] and safe:
                repaired.append((code, row["定额子目名称"], built))
                row["备注"] = (
                    (row.get("备注", "").strip() + "；" if row.get("备注", "").strip() else "")
                    + f"名称按官方PDF单元格补全（原：{row['定额子目名称']}）"
                )
                row["定额子目名称"] = built
            row["核对状态"] = "已核对"
            row["核对方式"] = "官方PDF表格线逐列核对（机器）"
            row["核对人"] = "pdf-cell-audit"
            row["核对日期"] = date.today().isoformat()
            row["核对批次"] = args.batch
            row["原文摘录"] = f"第{page_no}页 列x≈{result['center']:.0f} 表头：{'·'.join(tokens)}"
            if result["ambiguous"]:
                row["备注"] = (
                    (row.get("备注", "").strip() + "；" if row.get("备注", "").strip() else "")
                    + "本列表头另有跨列合并标签未计入：" + "、".join(result["ambiguous"])
                )
            row["证据ID"] = f"EV-QUOTA-{code}"
            note = row.get("备注", "").strip()
            marker = "PDF表格线逐列核对通过"
            if marker not in note:
                row["备注"] = (note + "；" if note else "") + marker
            evidence_by_id[row["证据ID"]] = {
                "证据ID": row["证据ID"], "数据类别": "定额", "条目编码": code,
                "来源名称": SOURCE_NAME, "来源版本": SOURCE_VERSION, "来源URL": PDF_URL,
                "来源SHA256": PDF_SHA, "物理页码": str(page_no),
                "原文摘录": f"第{page_no}页 列x≈{result['center']:.0f}：{'·'.join(tokens)}"
                            + (f"；单位：{result['unit']}" if result["unit"] else ""),
                "证据文件": args.pdf.name, "核对人": "pdf-cell-audit",
                "核对日期": date.today().isoformat(),
                "备注": "按编号所在列的表格线与单元格还原表头；名称与主表一致"
                        if verdict == "一致" else "按编号所在列的表格线与单元格补全名称",
            }

    print(f"待核对 {len(pending)} 条；通过 {verdicts['通过']}；未通过 {verdicts['名称冲突'] + verdicts['无法定位编号列']}")
    for reason, count in verdicts.most_common():
        print(f"  {reason}：{count}")
    print(f"其中按单元格补全名称 {len(repaired)} 条")
    for code, old, new in repaired[:10]:
        print(f"  {code}：{old} → {new}")

    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        with args.report.open("w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.writer(handle)
            writer.writerow(["定额编号", "页码", "主表名称", "PDF还原名称", "主表单位", "原文单位", "结果", "跨列合并标签"])
            writer.writerows(report)
        print(f"明细：{args.report}")

    if not args.apply:
        print("\n（未写文件；加 --apply 生效）")
        return 0

    with args.master.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)
    fields = list(evidence_rows[0].keys()) if evidence_rows else [
        "证据ID", "数据类别", "条目编码", "来源名称", "来源版本", "来源URL",
        "来源SHA256", "物理页码", "原文摘录", "证据文件", "核对人", "核对日期", "备注",
    ]
    with args.evidence.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for evidence_id in sorted(evidence_by_id, key=lambda key: (len(key), key)):
            writer.writerow(evidence_by_id[evidence_id])
    print(f"已写回 {args.master}；证据 {len(evidence_by_id)} 条（新增 {len(evidence_by_id) - len(known)}）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
