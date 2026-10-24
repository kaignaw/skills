# Skills

OpenCode skills collection.

## Included skills

### jiangsu-decoration-cost / 江苏装饰清单定额套项

把江苏省建筑装饰设计做法（DXF 做法明细、图纸说明、文字清单）套用为 2024 江苏清单（GB/T 50854-2024）与 2026 江苏省建筑与装饰工程消耗量子目，并生成可用于 GTJ/GCCP 建模的 xlsx。

内置数据：

- 26 条已核对清单种子库
- 477 条 2024 江苏清单全量索引（GB/T 50854-2024 的 472 条 + 江苏〔2025〕第 12 号公告增补的 5 条）
- 59 条已核对定额种子库
- 3115 条 2026 江苏消耗量全量索引
- 96 行清单定额套用示例

主要脚本：

```bash
# 查询清单编码
python3 jiangsu-decoration-cost/scripts/lookup.py boqindex 屋面
python3 jiangsu-decoration-cost/scripts/lookup.py boqindex 011101001 --json

# 查询定额编号
python3 jiangsu-decoration-cost/scripts/lookup.py quota 保温
python3 jiangsu-decoration-cost/scripts/lookup.py index 保温

# 校验并生成 xlsx
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
