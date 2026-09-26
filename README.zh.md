# smedc-companion-skills

这是 SMEDC（Small and Medium Enterprises Data Center）的 companion Codex skills 仓库。

本仓库采用 sibling skills 布局：每个 skill 都在 `skills/` 下独立拥有 `SKILL.md`、metadata、脚本、配置、测试和开发依赖。仓库根目录只负责安装说明和跨 skill 校验。

## Skills

- `skills/smedc-business-analysis/`：基于 SMEDC 结构化经营数据，生成租户中立的经营诊断、周会报表和月会报表。
- `skills/smedc-delivery-ledger/`：带收货单号的进货台帐查询、法定 CSV 导出、按门店/月维护 CSV，以及按收货单号关联检疫证明照片的使用指引。

## 安装

先安装核心前置 skill：

```bash
mkdir -p ~/.agents/skills
git clone https://github.com/YinXiaoyu-1998/smedc-mcp-skill.git /tmp/smedc-mcp-skill
cp -R /tmp/smedc-mcp-skill/skills/smedc-mcp ~/.agents/skills/smedc-mcp
```

安装 business-analysis skill 时，只复制它自己的 subtree：

```bash
mkdir -p ~/.agents/skills
git clone https://github.com/YinXiaoyu-1998/smedc-companion-skills.git /tmp/smedc-companion-skills
cp -R /tmp/smedc-companion-skills/skills/smedc-business-analysis ~/.agents/skills/smedc-business-analysis
```

安装 delivery-ledger skill 时同样只复制它自己的 subtree：

```bash
mkdir -p ~/.agents/skills
git clone https://github.com/YinXiaoyu-1998/smedc-companion-skills.git /tmp/smedc-companion-skills
cp -R /tmp/smedc-companion-skills/skills/smedc-delivery-ledger ~/.agents/skills/smedc-delivery-ledger
```

business-analysis skill 需要已认证的 `smedc-mcp` session，使用 `smedc-mcp-launcher@0.6.0` 和 MCP entry `smedc`。如果缺少前置项，必须先停止报表数据访问，并在安装前请求员工明确授权。它不会自动安装其他 companion skill。

delivery-ledger skill 使用同一个已认证的 `smedc-mcp` 前置项来查询台帐、准备带收货单号的 CSV 导出和按门店/月维护源数据、以及操作检疫证明照片。它不会自动安装其他 companion skill。

## 开发

运行仓库级检查：

```bash
python3 scripts/validate_all_skills.py
```

直接运行单个 skill 检查：

```bash
python3 -m unittest discover -s skills/smedc-business-analysis/tests -v
python3 /Users/xiaoyuyin/.codex/skills/.system/skill-creator/scripts/quick_validate.py skills/smedc-business-analysis
python3 -m unittest discover -s skills/smedc-delivery-ledger/tests -v
python3 /Users/xiaoyuyin/.codex/skills/.system/skill-creator/scripts/quick_validate.py skills/smedc-delivery-ledger
```

运行时脚本只使用 Python standard library。business-analysis 测试套件仅为了校验 `agents/openai.yaml` 使用 PyYAML；需要时从 business-analysis subtree 安装开发依赖：

```bash
python3 -m pip install -r skills/smedc-business-analysis/requirements-dev.txt
```
