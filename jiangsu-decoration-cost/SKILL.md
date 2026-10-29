---
name: 江苏装饰清单定额套项
description: 把江苏省建筑装饰设计做法（DXF 做法明细、图纸说明、文字清单）套用为 2024 江苏清单（GB/T 50854-2024）与 2026 江苏省建筑与装饰工程消耗量子目，并生成可用于 GTJ/GCCP 建模的 xlsx。只要用户提到江苏、2024 清单、2026 消耗量、装饰套项、工程做法明细、DXF 转清单、清单定额对照、GTJ 构件做法，或要求查 2024 江苏清单编码、使用 477 条清单主表、查 2026 江苏消耗量子目编号、使用 3133 条定额主表、核对清单定额覆盖率，或要求把建筑/装饰做法整理成清单和定额表，就应使用本技能；即使用户没有明确说“套定额”，只要任务涉及把做法落到清单编码和定额子目，也应使用。
compatibility: Python 3.10+；生成 xlsx 需要 openpyxl；重建主表另行需要 beautifulsoup4 / pdfplumber / pdftotext。核心数据已内置，日常套项无需联网。
---

# 江苏装饰清单定额套项

江苏省 2024 清单（GB/T 50854-2024）+ 2026 消耗量（苏建价〔2026〕76 号）的套项流程、已核对主表和产出脚本。
**默认交付**：五张工作表的 xlsx（清单定额套用 / 清单库 / 定额子目 / DXF 原文 / 编制依据）。

数据版本 `2.1.0`（2026-10-29）。只适用于江苏省 2024 清单 + 2026 消耗量；其他省份或 2014 定额请先说明不适用，不要混用编码。

## 30 秒上手

```bash
# 0) 环境自检（缺依赖、表头错、数据损坏会直接报出来）
python3 scripts/preflight.py

# 1) 查编码 / 查子目（先查内置数据，不要凭记忆报编号）
python3 scripts/lookup.py boq 屋面
python3 scripts/lookup.py quota 保温 --chapter 第十章
python3 scripts/lookup.py quota 13-136 --json

# 2) 写表：复制 assets/mapping_template.csv 为 work/清单定额套用.csv，再校验
python3 scripts/validate_mapping.py work/清单定额套用.csv

# 3) 出成果
python3 scripts/build_xlsx.py --mapping work/清单定额套用.csv \
  --dxf work/dxf/dxf_text.csv --notes work/编制依据.md \
  -o 成果/装饰工程清单与定额套用表.xlsx
```

`lookup.py` 子命令：`boq`（477 条清单）、`quota`（3133 条定额）、`mapping`（96 行示例）；`boqindex`/`index` 是旧别名，指向同一张主表。
`validate_mapping.py --print-header` 打印标准 20 列表头，可直接复制；`--strict` 把警告当失败。

## 任务路由

| 我要做的事 | 先读 | 再运行 |
|---|---|---|
| 查清单编码 / 定额编号 | 本文「30 秒上手」 | `lookup.py` |
| 完整套项（DXF→清单→定额→xlsx） | `references/workflow.md` | `extract_dxf.py` → `validate_mapping.py` → `build_xlsx.py` |
| 判断某做法该列哪个清单、怎么拆定额 | `references/mapping_rules.md` | — |
| 确认版本、文号、页码、核对可信度 | `references/sources.md` | `audit_coverage.py` |
| 看 20 列字段规则、续行、示例 | `references/workflow.md` §6 | `validate_mapping.py --print-header` |
| 直接改现有表出 xlsx | 本文「只转格式」 | `build_xlsx.py --mapping` |
| 重建主表（一般不需要） | `references/sources.md` §4 | `build_*_index.py` |

全部文件与阅读顺序见 `references/00-index.md`。

## 数据（只读，改动前先读 `references/sources.md`）

| 文件 | 条数 | 说明 |
|---|---|---|
| `data/boq_2024_jiangsu.csv` | 477 | 清单主表：472 条国标 + 5 条江苏增补，全部 `已核对`（官方 PDF OCR 逐行比对） |
| `data/quota_2026_jiangsu.csv` | 3133 | 定额主表，全部 `已核对`；`页码` = **PDF 物理页码** |
| `data/verification_evidence.csv` | 3610 | 每个 `已核对` 条目一条证据（来源/URL/SHA256/页码/摘录/核对人） |
| `data/mapping_examples.csv` | 96 | 完整套用示例：多定额行、续行、待确认备注 |
| `data/example_dxf_text.csv` | 206 | 样本 DXF 提取结果，可对照试跑 |

- `已核对` 只证明 **编号 + 页码 + 名称层级 + 单位** 与原文一致，不证明项目特征、构造、消耗量已复核；组价前仍建议按 `页码` 回查。
- 江苏增补 5 条（`010103003`、`011601016`–`011601019`）是地方项目，不能写成国标项目。
- 表内出现 `待核对` 时按候选处理，回查后先补 `核对状态/证据ID` 再写入成果；正常应为 0 条。

## 套项主流程（细节在 `references/workflow.md`）

1. **提原文**：DXF 用 `extract_dxf.py`（默认图层 `图名、说明`，自动分栏、按栏内 Y 降序还原）；残缺句保留并标“待核对”，不要替设计补内容。
2. **拆层不拆项**：先识别层（结构/找坡/保温/找平/防水/结合/面层/保护/骨架），再定清单实体。一个清单项下多个定额子目是正常的。
3. **配清单**：`lookup.py boq` 查 9 位编码；项目特征写全材料、厚度、强度等级、粘结方式、层数、上翻高度、基层、部位。
4. **配定额**：`lookup.py quota` 找候选后按 `页码` 回查；厚度差优先“基本子目 + 每增减”，按实际差值算次数；材料不同工艺相同才可换算并在备注写明依据。
5. **写 20 列**：同一 `序号` 首行填清单字段，后续定额行留空；“含在××内”写进备注。
6. **校验再出表**：`validate_mapping.py` → `build_xlsx.py`。

## 20 列套用表（顺序固定）

```text
序号 | 部位/分部 | 做法编号 | 做法名称 | GTJ构件/做法建议 | 做法层序 | 图纸做法条文 | 清单子项 | 清单编码 | 清单名称 | 项目特征描述 | 计量单位 | 工程量计算规则 | 清单工作内容 | 定额编号 | 定额子目名称 | 定额所属章节 | 定额计量单位 | 定额工作内容 | 套用说明 / 备注
```

- 第 20 列表头必须是 `套用说明 / 备注`（斜杠两侧有空格），否则 `validate_mapping.py` 直接报错。
- `计量单位` 是清单单位，`定额计量单位` 是定额单位，两列不能混。
- `项目特征描述` 用 `；` 分隔、一条一行写，不用手写序号：`build_xlsx.py` 会自动排成 `1.xxx` / `2.xxx` 多行（`--no-feature-numbering` 可关闭）。
- 模板：`assets/mapping_template.csv`（只有表头）。

## 最容易错的判定（完整条文见 `references/mapping_rules.md`）

| 做法 | 清单 | 定额 | 备注 |
|---|---|---|---|
| 屋面找平/保护层 | `010902004` 屋面刚性层 | 见 §2.1 | 也可统一为 `011101006`，一张表只能选一个口径 |
| 屋面保温兼找坡 | `011001001` | `10-17` 等 | 陶粒找坡属 J.6.5 类推，备注写明“待确认” |
| 楼面找平 | `011101006` / 细石混凝土 `011101007` | `12-28`~`12-34` | 块料自带粘结层不另列 |
| 屋面卷材防水 | `010902001` | `9-41` 起 | 上翻 ≤300mm 并入楼地面 |
| 墙面保温 | `011001003` | `10-61`(m³) 或 `10-42`(10m²) | 两种口径不能混用 |
| 干挂石材 | `011203001` | `13-136` + 骨架 `13-194/13-195`(t) | 骨架必须单列 |
| 吊顶 | `011302001` | 龙骨 + 吊筋 + 面层 | 铝合金条板 `14-31+14-35/36+14-64` |
| 金属面油漆 | `011402003` | `15-130/131/133` | 2026 无专项子目，只能就近换算并标注 |

单位换算速查：`10m²` 定额量 = 面积 ÷ 10；`10m` = 长度 ÷ 10；保温板 m³ = 面积 × 厚度(m)；厚度调整按 5mm 步距算次数。

## 只转格式

已有 20 列表格，只要 xlsx：`build_xlsx.py --mapping 表.csv -o 成果.xlsx`（`--dxf`、`--notes` 可选）。表头不标准时脚本按列序写入并告警，交付前用 `--print-header` 对齐。

## 质量红线

1. 不编造编码、编号、子目名称、单位；查不到写“待查 / 无对应子目”。
2. 不把 `待核对` 条目当已确认名称；不把提取的项目特征当逐字原文。
3. 不把结构层混进装饰清单；保留时标“结构专业，仅供建模对照”。
4. 不重复列辅助层；标准要求单列的（钢骨架、吊筋、防护剂）不漏。
5. 不把清单单位套到定额单位上。
6. 不隐藏假设：类推、换算、待确认、图纸残缺都写进备注，并在编制说明里汇总。
7. 交付前跑一遍 `validate_mapping.py`，确认五张表可打开、每个清单组首行有编码、每条定额行有单位。

样本项目里 7 个已知待确认点见 `references/sample_project_notes.md`（外墙原文残缺、陶粒找坡、银粉保护剂、耐酸漆、卵石灌浆、EPS 两种口径、50mm 垫层调整两次）。

## 目录结构

```text
SKILL.md                      # 本文件：路由 + 速查 + 红线
references/
  00-index.md                 # 文件地图与阅读顺序（不确定读哪个就看它）
  workflow.md                 # 六步工作流、20 列字段规则、检查清单
  mapping_rules.md            # 按分部拆的判定规则与条文依据
  sources.md                  # 版本/文号/来源/SHA256/核对方式与限制
  sample_project_notes.md     # 样本项目已知待确认项
  boq_2024_jiangsu.md         # 清单主表浏览版（附录分布、增补 5 条）
  quota_2026_jiangsu.md       # 定额主表浏览版（历史复核清单）
scripts/
  preflight.py                # 环境 + 数据 + 表头自检（先跑这个）
  extract_dxf.py              # DXF → dxf_text.csv
  lookup.py                   # 查清单/定额/示例
  validate_mapping.py         # 校验 20 列套用表（--print-header 出表头）
  build_xlsx.py               # 出五表 xlsx
  audit_coverage.py           # 覆盖率/证据完整性审计
  build_review_queue.py       # 待核对队列（P0/P1/P2）
  verify_boq_from_ocr.py      # 清单主表复核（官方 PDF OCR）
  verify_quota_from_pdf.py    # 定额主表复核（PDF 表格线逐列）
  build_boq_index.py          # 重建清单主表
  build_quota_index.py        # 重建定额主表
data/                         # 两张主表 + 证据 + 示例 + 名额复核明细
assets/                       # 示例成果 xlsx、表头模板
```
