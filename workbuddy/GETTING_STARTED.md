# 在 WorkBuddy 安装企业智脑（SMEDC）配套 Skills

以下是同一台电脑上的 WorkBuddy、Chrome 和 BrowserSkill 本地连接流程。需要 Git、Python 3.10+
以及核心 Skill 要求的 Node.js 22+ 和 npm。命令示例使用 macOS/Linux shell，Windows 的 CLI
安装命令和终端设置见各官方指南。

## 1. 克隆配套仓库并检查缺项

```bash
git clone https://github.com/YinXiaoyu-1998/smedc-companion-skills.git
cd smedc-companion-skills
python3 workbuddy/scripts/preflight.py
```

只读自检列出本机缺失的组件和修复方法。安装后也可以在任一已安装的配套 Skill 目录中运行同一条
`preflight.py` 命令。SMEDC 身份、WorkBuddy 能否发现 Skill 和美团登录态需要在 WorkBuddy
会话里核实。

## 2. 安装核心 Skill，连接 SMEDC 并登录

首次安装核心 Skill 时，复制官方仓库中的 Skill 子目录。已有安装时按核心 Skill 的更新流程处理。

```bash
core_checkout=$(mktemp -d "${TMPDIR:-/tmp}/smedc-core.XXXXXX")
git clone https://github.com/YinXiaoyu-1998/smedc-mcp-skill.git "$core_checkout"
mkdir -p ~/.workbuddy/skills/smedc-mcp
cp -R "$core_checkout/skills/smedc-mcp/." ~/.workbuddy/skills/smedc-mcp/
```

1. 按[核心 Skill 的官方安装指引](https://github.com/YinXiaoyu-1998/smedc-mcp-skill/blob/main/skills/smedc-mcp/SKILL.md#official-install-or-update)
   安装其中指定的 launcher 版本并运行 `self-check`。版本和平台路径都以核心 Skill 为准。
2. 按 [WorkBuddy 的 MCP 指南](https://www.codebuddy.ai/docs/zh/workbuddy/From-Beginner-to-Expert-Guide/Function-Description/MCP-Guide)
   在 WorkBuddy 添加或确认名为 `smedc` 的本地 stdio MCP。使用核心 Skill 给出的 launcher
   绝对路径、唯一参数 `serve` 和同一份 URL 环境变量。保留其他 MCP 连接器。
3. 开一个 WorkBuddy 新会话，请它加载 `smedc-mcp` 并调用 `smedc_auth_status`。
   如果需要认证，通过核心 Skill 的 `smedc_login` 打开官方页面，由本人完成登录，回到会话再确认状态。
   后续工作流还需要员工账号拥有对应的中央配置与权限。

## 3. 安装和连接 BrowserSkill

1. 按[腾讯的 BrowserSkill 安装指引](https://github.com/Tencent/BrowserSkill/blob/main/AGENT_INSTALL.md)
   安装 `bsk` CLI，并按指南把 `browser-skill` 安装或启用在 WorkBuddy。宿主命令调用应能执行
   `bsk --version`。如果 CLI 在默认的 `~/.local/bin`，每次新的 shell 调用都用完整路径或设置
   好该次调用的 PATH。Windows 的默认可执行文件为 `bsk.exe`。
2. **先检查 daemon**。在 WorkBuddy 运行 `BSK_AUTO_START=0 bsk status --json`。确认没有 daemon
   或启动中的后台任务时，请 WorkBuddy 用宿主管理的后台任务运行
   `BSK_AUTO_START=0 bsk daemon start --foreground`，再用另一次工具调用复查 `status --json`。
   后续调用使用同一个 `BSK_HOME`。权限错误或超时应先诊断，避免重复启动。
3. 安装官方 Chrome 扩展并开启**本地连接**。本地连接可用时配对是可选的。需要验证连接身份时，
   在 daemon 已运行后执行 `BSK_AUTO_START=0 bsk daemon pair`，将 private link 粘贴到扩展的配对
   设置，直至显示 Connected · Verified。将配对链接留在本机设置界面。步骤见[官方扩展连接指引](https://github.com/Tencent/BrowserSkill/blob/main/AGENT_INSTALL.md#4-connect-the-browser-extension)。
4. 运行 `BSK_AUTO_START=0 bsk browsers --json` 和 `BSK_AUTO_START=0 bsk doctor`，确认所需的 Chrome
   实例已连接、体检退出成功且无 FAIL。`doctor` 可能同步宿主的 BrowserSkill 文件，由本步骤单独运行。请 WorkBuddy 在新会话里加载 `browser-skill`，用 Agent Window 打开一个
   示例页，读取页面后结束测试会话。这一步验证当前 WorkBuddy 会话可实际调用 BrowserSkill。
5. 使用同一个 Chrome 实例。在 Agent Window 打开美团管家，由员工完成美团登录和验证码。检查页面
   里的账户、品牌、报表权限。

## 4. 安装配套 Skills

回到配套仓库根目录，按[安装与验证](INSTALL.md)运行 `check`、`install`、`verify`。
然后开一个新 WorkBuddy 会话，加载 `smedc-workflows` 和 `download-meituan-business-data`。
再次运行本地自检修复缺项。自然周周报等工作流需要的宿主通用 Skills 可按各自的官方说明
装入 WorkBuddy。

## 5. 第一次下载验收

在新 WorkBuddy 会话发出「按每日美团入库的来源采集阶段，只下载前一营业日的营业数据原件」。
先用原生 SMEDC 工具读取身份、中央配置和权限，再进入美团「自助营业取数」，核对查询条件，
按[网页操作手册](references/browser-skill.md)第 6 节对报表 iframe 触发一次导出。

本次只做本地下载和校验，返回匹配日期、门店和查询范围的原件、绝对路径及验证结果。下载文件
请保存在本地工作区或 `~/Downloads`。定时任务启用、上传、评价发布和发送邮件属于独立动作。
