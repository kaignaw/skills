#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Extract readable text from an ASCII DXF drawing.

The drawings used for Chinese decoration schedules are usually AutoCAD 2004
ASCII DXF files with GBK-encoded text on a layer such as "图名、说明".  This
script reads TEXT / MTEXT / ATTRIB entities, keeps their coordinates, optionally
filters by layer, reconstructs text fragments that share a baseline, and groups
the result into drawing columns.

Outputs (written next to --out, or into --out if it is a directory):
  dxf_entities.csv  X, Y, 图层, 文字
  dxf_lines.csv     栏, Y, X起, 文字
  dxf_text.csv      X, Y, 图层, 文字   (same shape as the example workbook sheet)

Only the Python standard library is required.

Example:
  python3 scripts/extract_dxf.py 工程做法明细.dxf -o work/dxf \
      --layer "图名、说明" --columns auto
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import statistics
import sys
from pathlib import Path
from typing import Iterable


TEXT_TYPES = {"TEXT", "MTEXT", "ATTRIB"}


def decode_dxf(path: Path, encoding: str | None = None) -> str:
    data = path.read_bytes()
    candidates = [encoding] if encoding else ["utf-8-sig", "gb18030", "gbk"]
    errors: list[str] = []
    for enc in candidates:
        if not enc:
            continue
        try:
            return data.decode(enc)
        except UnicodeDecodeError as exc:
            errors.append(f"{enc}: {exc}")
    raise SystemExit(
        "无法解码 DXF，请用 --encoding 指定编码。已尝试：\n  " + "\n  ".join(errors)
    )


def iter_pairs(text: str) -> Iterable[tuple[int, str]]:
    """Yield (group code, value) pairs from ASCII DXF text."""
    lines = text.splitlines()
    i = 0
    while i < len(lines) - 1:
        raw_code = lines[i].strip()
        if not re.fullmatch(r"-?\d+", raw_code):
            i += 1
            continue
        yield int(raw_code), lines[i + 1].strip()
        i += 2


def clean_text(value: str) -> str:
    """Turn common DXF control sequences into readable text."""
    value = value.replace("\\P", "\n").replace("\\p", "\n")
    # Very common legacy symbols.
    value = value.replace("%%%", "%").replace("%%d", "°").replace("%%D", "°")
    value = value.replace("%%c", "φ").replace("%%C", "φ")
    value = value.replace("%%p", "±").replace("%%P", "±")
    # MTEXT inline formatting such as \fSimSun|b0|i0|c134|p2; and {\...}
    value = re.sub(r"\\[A-Za-z][^;\\]*;", "", value)
    value = value.replace("{", "").replace("}", "")
    return value.strip()


def parse_entities(text: str) -> list[dict]:
    section: str | None = None
    pending_section = False
    current: dict | None = None
    entities: list[dict] = []

    def flush() -> None:
        nonlocal current
        if not current:
            return
        if current.get("type") in TEXT_TYPES:
            current["text"] = clean_text("".join(current.pop("_chunks", [])))
            if current["text"]:
                entities.append(current)
        current = None

    for code, value in iter_pairs(text):
        if code == 0:
            flush()
            if value == "SECTION":
                pending_section = True
                section = None
            elif value == "ENDSEC":
                pending_section = False
                section = None
            elif section == "ENTITIES":
                current = {
                    "type": value,
                    "layer": "",
                    "x": 0.0,
                    "y": 0.0,
                    "_chunks": [],
                }
            else:
                current = None
            continue

        if code == 2 and pending_section:
            section = value
            pending_section = False
            continue

        if current is None:
            continue
        if code == 8:
            current["layer"] = value
        elif code == 10:
            try:
                current["x"] = float(value)
            except ValueError:
                pass
        elif code == 20:
            try:
                current["y"] = float(value)
            except ValueError:
                pass
        elif code in (1, 3):
            current["_chunks"].append(value)

    flush()
    return entities


def kmeans_1d(values: list[float], k: int) -> tuple[list[float], list[int]]:
    """Small deterministic 1-D k-means used only as a fallback."""
    values = sorted(values)
    if k <= 1:
        return [statistics.mean(values) if values else 0.0], [0] * len(values)
    k = min(k, len(set(values)))
    centers = [values[min(len(values) - 1, int((i + 0.5) * len(values) / k))] for i in range(k)]
    labels = [0] * len(values)
    for _ in range(30):
        new_labels = [min(range(k), key=lambda j: abs(v - centers[j])) for v in values]
        new_centers = []
        for j in range(k):
            group = [v for v, lab in zip(values, new_labels) if lab == j]
            new_centers.append(statistics.mean(group) if group else centers[j])
        if new_labels == labels and all(abs(a - b) < 1e-9 for a, b in zip(centers, new_centers)):
            break
        labels, centers = new_labels, new_centers
    order = sorted(range(k), key=lambda j: centers[j])
    remap = {old: new for new, old in enumerate(order)}
    return [centers[j] for j in order], [remap[lab] for lab in labels]


def detect_columns(
    entities: list[dict], requested: str = "auto", gap: float | None = None
) -> tuple[list[float], list[int]]:
    """Return column centres and one column id per entity.

    Auto mode splits on large horizontal gaps; this matches the common
    three-column "left / middle / right" drawing layout.  If the gaps are not
    clear, it falls back to 1-D k-means with the requested number of columns.
    """
    xs = [e["x"] for e in entities]
    if not xs:
        return [0.0], []
    lo, hi = min(xs), max(xs)
    span = max(hi - lo, 1.0)

    requested_k = None if requested == "auto" else int(requested)
    gap = gap if gap is not None else max(4000.0, span * 0.12)

    uniq = sorted(set(round(x, 1) for x in xs))
    cuts: list[tuple[float, float, float]] = []
    for a, b in zip(uniq, uniq[1:]):
        if b - a >= gap:
            cuts.append((b - a, a, b))
    cuts.sort(reverse=True)

    max_cols = requested_k or 4
    chosen = cuts[: max(0, max_cols - 1)]
    if len(chosen) == (max_cols - 1 if requested_k else len(chosen)) and chosen:
        boundaries = sorted((a + b) / 2 for _, a, b in chosen)
        labels = [sum(x > boundary for boundary in boundaries) for x in xs]
        k = max(labels) + 1
        centers = [
            statistics.mean([x for x, lab in zip(xs, labels) if lab == j])
            for j in range(k)
        ]
        return centers, labels

    if requested_k:
        centers, labels_sorted = kmeans_1d(xs, requested_k)
        # kmeans_1d sorts values internally; map labels back to original order.
        mapping = {id(v): lab for v, lab in zip(sorted(xs), labels_sorted)}
        labels = [mapping[id(x)] for x in xs]
        return centers, labels

    return [statistics.mean(xs)], [0] * len(xs)


def merge_lines(
    entities: list[dict], labels: list[int], tolerance: float, max_x_gap: float
) -> list[dict]:
    lines: list[dict] = []
    by_col: dict[int, list[dict]] = {}
    for entity, label in zip(entities, labels):
        by_col.setdefault(label, []).append(entity)

    for col in sorted(by_col):
        items = sorted(by_col[col], key=lambda e: (-e["y"], e["x"]))
        groups: list[list[dict]] = []
        for item in items:
            if groups and abs(groups[-1][0]["y"] - item["y"]) <= tolerance:
                groups[-1].append(item)
            else:
                groups.append([item])
        for group in groups:
            group.sort(key=lambda e: e["x"])
            # A single visual line can contain two independent labels far apart
            # (for example two wall types side by side).  Split at a large
            # horizontal gap instead of gluing unrelated text together.
            chunks: list[list[dict]] = []
            for item in group:
                if chunks and item["x"] - chunks[-1][-1]["x"] > max_x_gap:
                    chunks.append([item])
                elif chunks:
                    chunks[-1].append(item)
                else:
                    chunks.append([item])
            for chunk in chunks:
                text = "".join(part["text"] for part in chunk)
                lines.append(
                    {
                        "column": col + 1,
                        "y": round(chunk[0]["y"], 1),
                        "x": round(chunk[0]["x"], 1),
                        "text": text,
                    }
                )
    lines.sort(key=lambda r: (r["column"], -r["y"], r["x"]))
    return lines


def write_csv(path: Path, headers: list[str], rows: Iterable[list]) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow(headers)
        writer.writerows(rows)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("dxf", type=Path, help="DXF 文件路径")
    parser.add_argument("-o", "--out", type=Path, default=Path("dxf_out"), help="输出目录")
    parser.add_argument("--layer", default="图名、说明", help='只保留指定图层；传 "*" 保留全部')
    parser.add_argument("--encoding", default=None, help="强制编码，如 gbk / utf-8")
    parser.add_argument("--columns", default="auto", help="栏数：auto 或整数，默认 auto")
    parser.add_argument("--column-gap", type=float, default=None, help="自动分栏的最小水平间距")
    parser.add_argument("--merge-tolerance", type=float, default=60.0, help="同一行文字的 Y 容差，默认 60")
    parser.add_argument("--max-x-gap", type=float, default=3000.0, help="同一行内允许合并的最大水平间距，默认 3000")
    parser.add_argument("--no-merge", action="store_true", help="不合并同一行的文字碎片")
    parser.add_argument("--json", action="store_true", help="额外输出 dxf_text.json")
    args = parser.parse_args()

    text = decode_dxf(args.dxf, args.encoding)
    entities = parse_entities(text)
    if args.layer and args.layer != "*":
        wanted = {name.strip() for name in args.layer.split(",")}
        entities = [e for e in entities if e["layer"] in wanted]
    if not entities:
        print("没有找到符合条件的 TEXT/MTEXT/ATTRIB，请检查 --layer。", file=sys.stderr)
        return 2

    centers, labels = detect_columns(entities, str(args.columns), args.column_gap)
    if args.no_merge:
        lines = [
            {"column": lab + 1, "y": round(e["y"], 1), "x": round(e["x"], 1), "text": e["text"]}
            for e, lab in zip(entities, labels)
        ]
        lines.sort(key=lambda r: (r["column"], -r["y"], r["x"]))
    else:
        lines = merge_lines(entities, labels, args.merge_tolerance, args.max_x_gap)

    out = args.out
    out.mkdir(parents=True, exist_ok=True)
    entity_rows = [[round(e["x"], 1), round(e["y"], 1), e["layer"], e["text"]] for e in entities]
    write_csv(out / "dxf_entities.csv", ["X", "Y", "图层", "文字"], entity_rows)
    write_csv(out / "dxf_text.csv", ["X", "Y", "图层", "文字"], entity_rows)
    write_csv(
        out / "dxf_lines.csv",
        ["栏", "Y", "X起", "文字"],
        [[r["column"], r["y"], r["x"], r["text"]] for r in lines],
    )
    if args.json:
        (out / "dxf_text.json").write_text(
            json.dumps(
                {
                    "source": str(args.dxf),
                    "layer": args.layer,
                    "columns": len(centers),
                    "entities": entity_rows,
                    "lines": lines,
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )

    layers = sorted({e["layer"] for e in entities})
    print(f"读取实体：{len(entities)} 条；图层：{', '.join(layers)}")
    print(f"识别栏数：{len(centers)}；合并后文字行：{len(lines)}")
    print(f"输出目录：{out.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
