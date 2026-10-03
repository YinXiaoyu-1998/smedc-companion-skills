# smedc-companion-skills

这是 SMEDC（Small and Medium Enterprises Data Center）的 companion Codex skills 仓库。

本仓库采用 sibling skills 布局：每个 skill 都在 `skills/` 下独立拥有 `SKILL.md`、metadata、脚本、配置、测试和开发依赖。仓库根目录只负责安装说明和跨 skill 校验。

## Skills

- `skills/smedc-business-analysis/`：基于 SMEDC 结构化经营数据，生成租户中立的经营诊断、周会报表和月会报表。
- `skills/smedc-delivery-ledger/`：带收货单号的进货台帐查询、法定 CSV 导出、按门店/月维护 CSV，以及按收货单号关联检疫证明照片的使用指引。
- `skills/download-meituan-dish-sales/`：按营业日期范围下载美团菜品销售原始 XLSX，用户要求时上传至 SMEDC `dishes`。
- `skills/download-meituan-business-data/`：按营业日期范围下载美团营业数据原始 XLSX，用户要求时上传至 SMEDC `business`。
- `skills/download-meituan-delivery-ledger/`：按收货日期筛选已收货单据，逐页下载 ZIP 并验证每单一份的原始 XLSX，供后续按需上传至 SMEDC `delivery_ledger`。

## 安装

需要访问 SMEDC 时，先安装核心前置 skill。仅从美团下载需要 Computer Use 和美团浏览器登录会话，无需 SMEDC 账号：

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

安装三个美团下载 skills 时，复用上面的 companion 仓库 checkout（若尚未克隆，先克隆），再复制各自的 subtree：

```bash
cp -R /tmp/smedc-companion-skills/skills/download-meituan-dish-sales ~/.agents/skills/download-meituan-dish-sales
cp -R /tmp/smedc-companion-skills/skills/download-meituan-business-data ~/.agents/skills/download-meituan-business-data
cp -R /tmp/smedc-companion-skills/skills/download-meituan-delivery-ledger ~/.agents/skills/download-meituan-delivery-ledger
```

以上为首次安装示例。若目标目录已经存在，先比较版本并保留本地修改；不要直接复制进已有 skill 目录。

下载 skills 默认保存到当前用户的 `~/Downloads`（不可用时使用 `~/Desktop`），使用通用 `meituan_...` 文件名并保留原始导出内容。三个技能统一使用 Chrome 下载事件与原生保存框处理 `ERR_BLOCKED_BY_CLIENT`；该方式已在菜品、营业报表验证，收货单自动回放尚未验证。上传 SMEDC 需要用户提出上传要求、核心 `smedc-mcp` skill 和已登录的 admin 账号。美团凭据由用户在浏览器中自行输入。本仓库不捆绑浏览器自动化运行环境。

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
