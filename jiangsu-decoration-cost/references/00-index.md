# 文件地图与阅读顺序

不确定该读哪个文件时先看这张表。所有路径都相对技能根目录。

## 1. 按任务选文件

| 任务 | 必读 | 选读 | 直接运行 |
|---|---|---|---|
| 查清单编码、名称、单位、项目特征 | `SKILL.md`「30 秒上手」 | `references/boq_2024_jiangsu.md` | `scripts/lookup.py boq …` |
| 查定额子目、章、页码 | `SKILL.md`「30 秒上手」 | `references/quota_2026_jiangsu.md` | `scripts/lookup.py quota …` |
| 新项目完整套项 | `references/workflow.md` | `references/mapping_rules.md` | `extract_dxf.py` → `validate_mapping.py` → `build_xlsx.py` |
| 判断某个做法列哪个清单 | `references/mapping_rules.md` §2–§9 | `references/workflow.md` §4 | — |
| 定额怎么拆、单位怎么换 | `references/workflow.md` §5 | `references/mapping_rules.md` §10 | — |
| 20 列怎么填、怎么续行 | `references/workflow.md` §6 | `data/mapping_examples.csv` | `validate_mapping.py --print-header` |
| 版本/文号/来源/可信度 | `references/sources.md` | — | `audit_coverage.py` |
| 已有表只想出 xlsx | `SKILL.md`「只转格式」 | — | `build_xlsx.py --mapping` |
| 主表疑似有错、要复核 | `references/sources.md` §4 | `references/sample_project_notes.md` | `verify_boq_from_ocr.py` / `verify_quota_from_pdf.py` |
| 重建主表 | `references/sources.md` §4 | `references/workflow.md` | `build_boq_index.py` / `build_quota_index.py` |

## 2. 推荐阅读顺序（第一次做项目）

1. `SKILL.md`：30 秒上手、数据边界、20 列、8 条易错判定、红线。
2. `references/workflow.md`：输入盘点 → DXF 提取 → 做法树 → 清单 → 定额 → 20 列 → 出表 → 检查清单。
3. 做到某分部时再翻 `references/mapping_rules.md` 对应小节，不必通读。
4. 需要引用来源或解释“为什么这条能直接用”时读 `references/sources.md`。
5. 交付前对照 `references/workflow.md` §8 检查清单。

熟手路径：`SKILL.md` → `lookup.py` → 写表 → `validate_mapping.py` → `build_xlsx.py`。

## 3. 文件清单

| 路径 | 作用 | 规模 |
|---|---|---|
| `SKILL.md` | 技能入口：路由、速查、红线 | ~150 行 |
| `references/workflow.md` | 全流程展开、20 列字段规则、交付检查清单 | ~270 行 |
| `references/mapping_rules.md` | 按屋面/外墙/楼地面/墙裙/天棚/油漆等分部的判定规则与条文依据 | ~200 行 |
| `references/sources.md` | 依据版本、文号、URL、SHA256、核对方式、数据限制、版本记录 | ~150 行 |
| `references/sample_project_notes.md` | 样本项目 7 个已知待确认点 | ~30 行 |
| `references/boq_2024_jiangsu.md` | 清单主表浏览版：江苏增补 5 条、附录分布、查询示例 | ~100 行 |
| `references/quota_2026_jiangsu.md` | 定额主表浏览版：历史人工复核 59 条清单、使用提示 | ~80 行 |
| `data/*.csv` | 两张主表 + 证据 + 示例 + 改名明细 | 见 `SKILL.md` 数据表 |
| `data/manifest.json` | 机器可读的版本、条数、字段、覆盖率、入口命令 | — |
| `scripts/preflight.py` | 环境与数据自检 | — |
| `scripts/lookup.py` | 查清单/定额/示例，`--json` 机器可读 | — |
| `scripts/extract_dxf.py` | DXF → `dxf_entities/lines/text.csv` | — |
| `scripts/validate_mapping.py` | 校验 20 列套用表，附主表核对状态与原文页码 | — |
| `scripts/build_xlsx.py` | 生成五张工作表的 xlsx | — |
| `scripts/audit_coverage.py` | 覆盖率、证据完整性、重复编码、空字段 | — |
| `scripts/build_review_queue.py` | P0/P1/P2 复核队列 | — |
| `scripts/verify_boq_from_ocr.py` | 清单名称按官方 PDF OCR 复核 | — |
| `scripts/verify_quota_from_pdf.py` | 定额名称按 PDF 表格线逐列复核 | — |
| `scripts/build_boq_index.py` | 从 HTML 重建清单主表（继承核对结论） | — |
| `scripts/build_quota_index.py` | 从 PDF 文本重建定额主表（继承核对结论） | — |
| `assets/example_output.xlsx` | 样本成果，看版式用 | — |
| `assets/mapping_template.csv` | 20 列空模板，复制后填写 | — |

## 4. 术语

- **清单**：GB/T 50854-2024 的 9 位编码项目，按实体/部位列项，带项目特征与计算规则。
- **定额 / 消耗量**：江苏省 2026 消耗量子目（`章-序号`，如 `13-136`），按施工层/材料/厚度拆分，带单位与工作内容。
- **套用表**：20 列 CSV，一个清单组 + 若干定额行，是本技能的唯一交付输入。
- **`已核对`**：编号、物理页码、名称层级、单位与原文一致；不等于构造/消耗量已复核。
