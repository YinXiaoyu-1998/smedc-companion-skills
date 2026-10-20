# SMEDC 配套 Skills

面向企业资料中枢（Small and Medium Enterprises Data Center）的独立工作流。
每个 `skills/<name>/` 子目录维护自己的指导、引用、脚本、配置与测试。[English](README.md)。

## 技能目录

| Skill | 用途与前置条件 |
| --- | --- |
| [smedc-business-analysis](skills/smedc-business-analysis/SKILL.md) | 基于受权 SMEDC 数据生成经营诊断、周报和月报 HTML；需要核心 Skill 和已认证会话。 |
| [smedc-delivery-ledger](skills/smedc-delivery-ledger/SKILL.md) | 原始收货单上传、关联检疫照片、服务端每日 PDF／ZIP 交付；需要核心 Skill 及归档交付启用，不在本地生成台账。 |
| [download-meituan-business-data](skills/download-meituan-business-data/SKILL.md) | 导出原始营业 XLSX。 |
| [download-meituan-dish-sales](skills/download-meituan-dish-sales/SKILL.md) | 导出原始菜品销售 XLSX。 |
| [download-meituan-delivery-ledger](skills/download-meituan-delivery-ledger/SKILL.md) | 分批导出收货单 ZIP，验证每单一份原始 XLSX。 |
| [reply-meituan-reviews](skills/reply-meituan-reviews/SKILL.md) | 采集九列评价表，保留已有回复，只为未回复且有正文的评价起草；仅发布明确获批的新稿，需要本仓库的定制回复文案 Skill。 |
| [review-responder](skills/review-responder/SKILL.md) | 定制中文餐饮商家回复文案；原始归属信息保留在 Skill 内。 |

仅操作美团需要浏览器能力及用户自行完成的美团登录，不需要 SMEDC 账号。
上传 SMEDC 另需用户明确要求、核心 Skill 及已认证 admin。浏览器选择、下载处理和回复审批细则
只在所链接的 Skills 中维护，README 不重复操作手册。

## 版本归属

[官方核心 Skill](https://github.com/YinXiaoyu-1998/smedc-mcp-skill/blob/main/skills/smedc-mcp/SKILL.md)
维护唯一批准的 launcher 精确安装 pin，以及更新、登录流程。Companion 使用该 pin 和 MCP entry
`smedc`，不选 npm `latest`，不从服务元数据自行改 pin，也不另定安装版本。
包发布、服务部署、租户配置分别核对。

Skill 修订以来源 Git commit 和子目录标识，不使用 launcher 版本号代替。
更新本仓库不等于更新核心 Skill、launcher 或本机已安装副本。缺少前置项时停止数据访问，
安装或升级仅在用户授权范围内进行。

## 安装与更新

使用 `~/.agents/skills`（Windows 为 `%USERPROFILE%\.agents\skills`）。以下仅为**首次安装示例**，
只执行用户请求的 Skill 对应命令，目标目录必须不存在；临时 checkout 路径已存在时另选新路径。

需要 SMEDC 访问时，只安装核心子目录：

```bash
mkdir -p ~/.agents/skills
git clone https://github.com/YinXiaoyu-1998/smedc-mcp-skill.git /tmp/smedc-mcp-skill
cp -R /tmp/smedc-mcp-skill/skills/smedc-mcp ~/.agents/skills/smedc-mcp
```

配套仓库只需克隆一次，再复制请求范围内的子目录：

```bash
git clone https://github.com/YinXiaoyu-1998/smedc-companion-skills.git /tmp/smedc-companion-skills
cp -R /tmp/smedc-companion-skills/skills/smedc-business-analysis ~/.agents/skills/smedc-business-analysis
cp -R /tmp/smedc-companion-skills/skills/smedc-delivery-ledger ~/.agents/skills/smedc-delivery-ledger
cp -R /tmp/smedc-companion-skills/skills/download-meituan-business-data ~/.agents/skills/download-meituan-business-data
cp -R /tmp/smedc-companion-skills/skills/download-meituan-dish-sales ~/.agents/skills/download-meituan-dish-sales
cp -R /tmp/smedc-companion-skills/skills/download-meituan-delivery-ledger ~/.agents/skills/download-meituan-delivery-ledger
cp -R /tmp/smedc-companion-skills/skills/review-responder ~/.agents/skills/review-responder
cp -R /tmp/smedc-companion-skills/skills/reply-meituan-reviews ~/.agents/skills/reply-meituan-reviews
```

更新已有安装时，获取默认分支并记录 commit；比较请求范围内的完整子目录，先保留本地定制。
暂存并校验替换内容，将恢复副本放在所有 Skill 发现目录之外，再完整替换子目录。
不要覆盖合并、留下旧文件，或在发现目录内创建备份 Skill。确认文件和宿主实际加载的新副本后，
再移除恢复副本并报告完成；需要宿主重载时明确报告待完成。不得静默安装未请求的配套技能或依赖。
核心 Skill 遵循独立的[替换流程](https://github.com/YinXiaoyu-1998/smedc-mcp-skill/blob/main/skills/smedc-mcp/references/update-skill.md)。

## 开发

```bash
python3 -m pip install -r skills/smedc-business-analysis/requirements-dev.txt
python3 scripts/validate_all_skills.py
```

定向检查：

```bash
python3 -m unittest discover -s skills/smedc-business-analysis/tests -v
python3 -m unittest discover -s skills/smedc-delivery-ledger/tests -v
```

Delivery-ledger 测试仅使用 Python 标准库；business-analysis 元数据测试另用 PyYAML。
运行和数据清理要求由各 Skill 维护。临时报表、下载数据和执行流水账不放入本仓库。
