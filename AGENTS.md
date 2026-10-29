# AGENTS.md

## Repository shape

- This repo is a catalog of self-contained OpenCode skills, not an application. Each top-level directory is one skill; currently only `jiangsu-decoration-cost/`.
- There is no root package manager, test suite, CI, or build step. Verification is done by running the skill scripts (below).
- Install a skill by copying its whole directory to `.opencode/skills/` (project) or `~/.config/opencode/skills/` (global). Do not assume root-level files are installed with it.
- `jiangsu-decoration-cost/SKILL.md` frontmatter (`name`, `description`, `compatibility`) controls activation; keep `description` trigger-rich. Data version appears in both `SKILL.md` and `data/manifest.json`; update them together.
- Layout is deliberately routed for agents: `SKILL.md` is a short router (quick commands, 20-column table, error-prone mappings, red lines); `references/00-index.md` maps task → file; details live in `references/{workflow,mapping_rules,sources}.md`. Keep `SKILL.md` under ~150 lines — push new detail into a reference file and add one line to `00-index.md`.
- `scripts/preflight.py` is the single readiness check (deps, data counts, `核对状态`, template header, sample lookups). Run it before trusting any other output.

## Working in `jiangsu-decoration-cost`

Run commands from the repo root with the directory prefix, or from inside the skill directory and drop the prefix. Scripts resolve `data/` relative to their own location, so cwd does not affect data lookup.

```bash
# Readiness: deps + data counts + header + lookup smoke test
python3 jiangsu-decoration-cost/scripts/preflight.py

# Lookup: boq=477-row BOQ master table, quota=3133-row quota master table,
# mapping=sample rows. boqindex/index are aliases for the same master tables.
python3 jiangsu-decoration-cost/scripts/lookup.py boq 011101001 --json
python3 jiangsu-decoration-cost/scripts/lookup.py quota 保温 --chapter 第十三章
python3 jiangsu-decoration-cost/scripts/lookup.py quota --status 待核对 --limit 20

# Coverage audit and review queue
python3 jiangsu-decoration-cost/scripts/audit_coverage.py
python3 jiangsu-decoration-cost/scripts/build_review_queue.py --out work/review_queue.csv

# DXF text extraction (defaults to layer 图名、说明)
python3 jiangsu-decoration-cost/scripts/extract_dxf.py plan.dxf -o work/dxf --layer "图名、说明"

# Always validate before building the workbook (--print-header prints the exact 20 columns)
python3 jiangsu-decoration-cost/scripts/validate_mapping.py --print-header
python3 jiangsu-decoration-cost/scripts/validate_mapping.py work/清单定额套用.csv
python3 jiangsu-decoration-cost/scripts/build_xlsx.py \
  --mapping work/清单定额套用.csv \
  --dxf work/dxf/dxf_text.csv \
  --notes work/编制依据.md \
  -o 成果/装饰工程清单与定额套用表.xlsx
```

### Gotchas

- `validate_mapping.py` requires the exact 20-column header. The 20th header is `套用说明 / 备注` **with spaces around the slash**, even though `SKILL.md`/`references/workflow.md` prose writes `套用说明/备注`. Start new tables from `assets/mapping_template.csv` or `validate_mapping.py --print-header` instead of retyping. A nonstandard header is an error in the validator; `build_xlsx.py` only warns and then writes by column position.
- Validation warnings are non-fatal unless `--strict` is passed. Do not treat exit 0 as proof that codes are verified: warnings mark codes missing from the master tables **or still marked `待核对`** (the warning includes the 原文页码).
- Mapping rows use `序号` as the bill-item group ID. Fill all bill fields (`清单编码`/`清单名称`/`计量单位`) only on the group's first row; leave them blank on following quota rows. The validator rejects a continuation row with no preceding bill item and inconsistent names/units within a group.
- CSV input may be UTF-8, UTF-8-BOM, or GB18030. xlsx output requires `openpyxl`.
- `build_xlsx.py` numbers the `项目特征描述` cell: it splits the CSV value on `；`/`;`/newlines (single-item text with `。` splits by sentence) and writes `1.xxx` lines, stripping any existing `1.`/`1、` prefix first, so it is idempotent. `--no-feature-numbering` keeps the value verbatim. Keep mapping CSVs unnumbered and let the builder do it.
- In `lookup.py`, a full quota code (`12-18`) or 9-digit BOQ code is matched exactly; other queries are case-insensitive substring searches across all fields. `--status`/`--quality` filter on `核对状态`.
- `build_xlsx.py` always emits five sheets: `清单定额套用`, `清单库(2024-江苏)`, `定额子目(江苏2026)`, `工程做法原文(DXF)`, `编制依据与说明`. `--dxf` accepts either the `dxf_text.csv` file or its directory. `--boq`/`--quota` default to the two master tables; the notes sheet reports current verified counts.

## Data authority (most important)

- One authoritative table per dataset; there is no seed/index split.
  - `data/boq_2024_jiangsu.csv` = 477 BOQ rows (472 national + 5 Jiangsu additions), all `已核对`: 472 by official-PDF OCR row comparison, 5 from the Jiangsu notice attachment.
  - `data/quota_2026_jiangsu.csv` = 3133 quota rows, all `已核对`: 77 by historical manual review, 3056 by official-PDF table-rule cell comparison (`scripts/verify_quota_from_pdf.py`). `页码` is the **physical PDF page**, not the printed page.
  - `data/verification_evidence.csv` = one evidence row per verified code, keyed by `证据ID` (source name, version, URL, SHA256, page, excerpt, reviewer).
- Both master tables carry `核对状态`, `核对方式`, `核对人`, `核对日期`, `核对批次`, `原文摘录`, `证据ID`; the BOQ table also carries `原文页码`.
- `已核对` only proves code + page + name-level + unit agreement with the source; it does not prove 项目特征/构造/消耗量. Treat any `待核对` row as a candidate code: formal output must either use a `已核对` row or verify it against its page and update status/evidence first. The 26 historical seed rows were re-checked by OCR on 2026-10-29 and now carry `核对批次 = ocr-audit-2026-10-29`; no legacy rows remain.
- Never invent codes, names, or units. Use `—`/`（无对应子目）`/`待查`, and state assumptions, extrapolations, and unresolved items in `套用说明 / 备注`.
- The five Jiangsu-only additions (`010103003`, `011601016`–`011601019`) must not be presented as national GB/T items.
- `scripts/verify_quota_from_pdf.py` re-checks quota names against the official PDF's table rules and word coordinates, column by column (`--report` for a CSV, `--apply` to write; needs `pdfplumber`). It is a second, independent path from `build_quota_index.py`'s `pdftotext -layout` row splitting. It inserts missing header levels (463 rows) but keeps the master's level order; renames are listed in `data/quota_name_review.csv`.
- `scripts/verify_boq_from_ocr.py` re-checks BOQ names against official-PDF OCR JSON (`--dry-run` by default, `--apply` to write, `--recheck-legacy` to upgrade old batches). It does not verify skill semantics (项目特征/构造); it only proves code+page+name agreement.
- Do not hand-edit the master CSVs. Regenerate with `scripts/build_boq_index.py` (needs HTML + `beautifulsoup4`) or `scripts/build_quota_index.py` (needs `pdftotext -layout` and the official PDF). Both merge verification fields by code from `--preserve-from` (default: the current master table), so a rebuild does not reset reviewed rows; pass `--no-preserve` only for a deliberate clean rebuild. Detailed field/item rules live in `references/workflow.md` and `references/mapping_rules.md`; source/version limits in `references/sources.md`.

## Verification

- No tests exist. Smoke check: `preflight.py` exits 0; `audit_coverage.py` reports 477/3133 rows with 477/3133 verified; `validate_mapping.py data/mapping_examples.csv` reports 96 rows, 0 errors, 0 warnings; `build_review_queue.py` writes a queue; then build a workbook to `/tmp` and confirm the five sheet names above.
- `tests/fixtures/*_legacy_seed.csv` are the historical 26/59-row samples. They are regression references only, never a runtime data source.
- Treat `assets/example_output.xlsx` as a layout reference; regenerate output from CSV when changing behavior.
