# Capability mapping and hard limits（browser-skill profile）

本文件是 **browser-skill profile** 的能力映射。生成 overlays 时随每个已安装 skill 分发，
与 web-access profile 的 `workbuddy/HOST_MAP.md` 互斥；权威网页操作手册是
`workbuddy/references/browser-skill.md`。

## Host prerequisites（一次性 vs 每轮）

| 项目 | 一次性？ | 说明 |
| --- | --- | --- |
| 安装 `bsk` CLI（默认 `~/.local/bin/bsk`） | **是** | 按官方 AGENT_INSTALL.md |
| 安装 Chrome 扩展 + `bsk daemon pair` 配对 | **是** | 员工把 private link 粘进扩展连接设置；配对密钥不入日志 |
| 美团登录 | **是** | 同 Chrome profile cookie jar，Agent Window 与用户窗口共享 |
| `bsk doctor` 全绿 | **是**（升级后需复查） | CLI/扩展 version skew 时 `bsk update` 并重启 daemon |
| **daemon 常驻** | **否，进程级** | agent 每轮 `status --json` probe；不在时用宿主后台任务拉起 `daemon start --foreground`。无需员工操作 |
| `cooperate sync` 的 context / observation | **否，每次交互** | agent 自动调用；导航或人工输入后需重新 sync |

**与 web-access profile 的关键差别**：Chrome >=144 的 CDP 路径在每次远程调试连接时弹
「允许」、每个新浏览器会话还要重做，无人值守不可靠。browser-skill 走扩展配对（一次性）
+ 常驻 daemon（agent 可自保证）+ 自建 Agent Window tab，**没有每次人工授权弹窗**。
因此定时来源采集的可行性从「基本不可」提升为「有条件可行」；剩余条件是 daemon/扩展在线。

## Fully equivalent

| 能力 | 机制 |
| --- | --- |
| 中央工作流工具 | 原生 `mcp__smedc__*`（claim/check/record、状态查询） |
| 官方绑定 / 认证会话 | `entryName=smedc`、`mcp__smedc__`；核心 skill 登录 |
| 网页导航、DOM 读写、点击、截图 | `bsk navigate` / `snapshot` / `observe` / `click` / `screenshot` |
| iframe / shadow-root 控件 | VOM `@eN` refs（CSS 选择器只搜主文档） |
| **下载落盘** | `bsk download <trigger> --out <path>` 原生捕获，无需处理 Chrome 临时文件 |
| 登录/验证码人工协助 | `bsk request-help`（扩展 human help 默认 enabled） |
| 本地文件校验、日期计算、原子状态 | Bash / Python 标准库 / `wb_state.py` |

## Equivalent with adaptation（含限制）

| 项目 | 机制 | 残余差异 |
| --- | --- | --- |
| 借用员工标签页 | `bsk tab borrow` | 默认 `borrow_confirmation: always`，每次要确认；用自建 Agent Window tab 规避 |
| 远程连接场景 | — | 官方注明 remote upload/download unsupported |
| 每步交互 | `cooperate sync --policy target` | 必须传对 `context_id` 与顶层 `observation_id`；evaluate 缺 observation 会被拒 |
| CLI 文档 | `bsk <cmd> --help` | 自带 SKILL.md 示例与实际 CLI 有出入（`bsk open` / `--url` / `--expression` 不存在） |
| 下载异常 | `download_path_mismatch` | 浏览器可能把文件落到别处，需查下载列表后决定是否重试 |
| 定时续轮 | `wb_state.py` | 无 Goal 生命周期，本地哈希链状态是降级而非中央回执 |
| 宿主定时任务 | `automation_update` | 只建 PAUSED，确切时间表需员工确认；无 projectId/model 字段 |

## Not substitutable（硬限制）

1. **原生邮件身份**：WorkBuddy 的 Agent Mail 发件人不是中央冻结的 `allowedSender`，且缺
   逐字节 `provider_readback`。**邮件阶段 blocked**，周报本地交付、评价新稿留在审阅表。
2. **Goal lifecycle**：无 `get_goal`/`create_goal`/`update_goal`；`wb_state.py` 是本地降级。
3. **JS `tools` 注入**：`native-adapters.js` 需要可调用宿主工具对象的求值环境，本宿主没有；
   中央动作由 agent 分步调用原生工具，禁止私有 HTTP/JSON-RPC 客户端。
4. **无人值守的绝对保证**：daemon 是普通进程，宿主回收/重启后需 agent 重新拉起；扩展断开
   或员工退出 Chrome 仍会阻塞来源阶段。

## Consequences that must be reported

- 邮件阶段 blocked 的完成轮是 `partial`，不是 `succeeded`。
- daemon/扩展不可用时来源阶段 `blocked`，保留精确待续范围，不空跑、不重放。
- 安装不激活租户、不授予上传/发布/发信权限、不修改中央配置。
