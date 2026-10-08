# smedc-companion-skills

这是 SMEDC（Small and Medium Enterprises Data Center）的配套智能体 skills 仓库。

本仓库采用 sibling skills 布局：每个 skill 都在 `skills/` 下独立拥有 `SKILL.md`、metadata、脚本、配置、测试和开发依赖。仓库根目录只负责安装说明和跨 skill 校验。

## Skills

- `skills/smedc-business-analysis/`：基于 SMEDC 结构化经营数据，生成租户中立的经营诊断、周会报表和月会报表。
- `skills/smedc-delivery-ledger/`：原始收货单上传、收货单关联检疫照片，以及归档发布后的服务端自动更新的每日 PDF 就绪检查和 ZIP 下载协调。已移除本地 XLSX/CSV 导出和按月维护。
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

business-analysis skill 需要已认证的 `smedc-mcp` session，使用 `smedc-mcp-launcher@0.8.2` 和 MCP entry `smedc`。如果缺少前置项，必须先停止报表数据访问，并在安装前请求员工明确授权。它不会自动安装其他 companion skill。

delivery-ledger skill 使用同一个核心前置项上传原始收货单和操作检疫照片。PDF 流程使用已公开发布并独立验证的核心 pin `smedc-mcp-launcher@0.8.2`，还需要服务端启用归档交付。流程等待导入实际 applied，说明台账会自动更新，完成后即可下载，是否就绪以查询结果为准，下载前检查覆盖状态，再准备已有 PDF 并获取新 ZIP 短链。员工 Agent（包括管理员）不能通过 MCP 或 HTTP 触发 PDF 生成。旧 `export_ledger.py`、`export_ledger_csv.py` 和按月维护已移除；不生成本地 PDF/XLSX/CSV，也不再需要 `openpyxl`。归档交付尚未启用时说明不可用，等待服务端切换。不会自动安装其他 companion skill。

安装三个美团下载 skills 时，复用上面的 companion 仓库 checkout（若尚未克隆，先克隆），再复制各自的 subtree：

```bash
cp -R /tmp/smedc-companion-skills/skills/download-meituan-dish-sales ~/.agents/skills/download-meituan-dish-sales
cp -R /tmp/smedc-companion-skills/skills/download-meituan-business-data ~/.agents/skills/download-meituan-business-data
cp -R /tmp/smedc-companion-skills/skills/download-meituan-delivery-ledger ~/.agents/skills/download-meituan-delivery-ledger
```

以上为首次安装示例。若目标目录已经存在，先比较版本并保留本地修改；不要直接复制进已有 skill 目录。

在 Codex 中，这三个技能优先使用内置 Chromium 浏览器（`iab`）完成登录、导出和下载。只有用户指定本机浏览器，或内置浏览器缺少必需能力/会话时才回退，并在切换前说明原因；不会仅因本机 Chrome 已登录就切换。

下载 skills 默认保存到当前用户的 `~/Downloads`（不可用时使用 `~/Desktop`），使用通用 `meituan_...` 文件名并保留原始导出内容。三个技能统一使用 Chrome 下载事件与原生保存框处理 `ERR_BLOCKED_BY_CLIENT`；默认连续等待下载事件 45 秒，外层工具调用设为 60 秒，每个文件/批次核对结果后最多自动重试一次。菜品、营业已在本机 Chrome 验证；一批 92 张收货单也已在内置浏览器采用较长等待成功下载并验证。这些记录不保证所有导出都在 45 秒内完成。上传 SMEDC 需要用户提出上传要求、核心 `smedc-mcp` skill 和已登录的 admin 账号。美团凭据由用户在浏览器中自行输入。业务流程适用于具备相应能力的智能体；浏览器 API 示例针对提供 `cua_repl` / `tab.playwright` / `cua.getApp` 的环境。其他智能体需要等价的浏览器、下载及本地文件操作能力，并在自身环境验证下载行为。本仓库不捆绑浏览器自动化运行环境。

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

delivery-ledger 契约测试仅使用 Python standard library。business-analysis 测试套件仅为了校验 `agents/openai.yaml` 使用 PyYAML；需要时安装其开发依赖：

```bash
python3 -m pip install -r skills/smedc-business-analysis/requirements-dev.txt
```
