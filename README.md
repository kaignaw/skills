# Skills

OpenCode skills collection.

## Included skills

### jiangsu-decoration-cost / 江苏装饰清单定额套项

把江苏省建筑装饰设计做法（DXF 做法明细、图纸说明、文字清单）套用为 2024 江苏清单（GB/T 50854-2024）与 2026 江苏省建筑与装饰工程消耗量子目，并生成可用于 GTJ/GCCP 建模的 xlsx。

内置数据：

- 477 条 2024 江苏清单主表（GB/T 50854-2024 的 472 条 + 江苏〔2025〕第 12 号公告增补的 5 条；477 条已核对）
- 3133 条 2026 江苏消耗量定额主表（3133 条已核对：77 条历史人工复核 + 3056 条官方 PDF 表格线逐列比对）
- `verification_evidence.csv` 核对证据表（3610 条 = 清单 477 + 定额 3133，每个已核对条目一个证据ID）
- 96 行清单定额套用示例；`assets/mapping_template.csv` 20 列空模板

主要脚本：

```bash
# 环境与数据自检（先跑这个）
python3 jiangsu-decoration-cost/scripts/preflight.py

# 查询清单编码（带核对状态）
python3 jiangsu-decoration-cost/scripts/lookup.py boq 屋面
python3 jiangsu-decoration-cost/scripts/lookup.py boq 011101001 --json

# 查询定额编号
python3 jiangsu-decoration-cost/scripts/lookup.py quota 保温
python3 jiangsu-decoration-cost/scripts/lookup.py quota --status 待核对 --chapter 第十三章

# 覆盖率审计与待核对队列
python3 jiangsu-decoration-cost/scripts/audit_coverage.py
python3 jiangsu-decoration-cost/scripts/build_review_queue.py --out work/review_queue.csv

# 校验并生成 xlsx（--print-header 打印标准 20 列表头）
python3 jiangsu-decoration-cost/scripts/validate_mapping.py --print-header
python3 jiangsu-decoration-cost/scripts/validate_mapping.py work/清单定额套用.csv
python3 jiangsu-decoration-cost/scripts/build_xlsx.py \
  --mapping work/清单定额套用.csv \
  --dxf work/dxf/dxf_text.csv \
  -o 成果/装饰工程清单与定额套用表.xlsx
```

安装到 OpenCode：

```bash
# 项目级
mkdir -p .opencode/skills
cp -a jiangsu-decoration-cost .opencode/skills/

# 全局
mkdir -p ~/.config/opencode/skills
cp -a jiangsu-decoration-cost ~/.config/opencode/skills/
```

数据来源、版本和使用边界见 `jiangsu-decoration-cost/references/sources.md` 与 `jiangsu-decoration-cost/SKILL.md`。
