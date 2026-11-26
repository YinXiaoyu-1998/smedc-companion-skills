# WorkBuddy 能力映射

| 能力 | WorkBuddy 路径 |
| --- | --- |
| SMEDC 身份和中央工作流动作 | 安装官方核心 Skill 及 launcher 后，以 `smedc` 为名接入原生 stdio MCP，再登录 |
| 网页导航和采集 | BrowserSkill CLI + Chrome 扩展，用独立 Agent Window 复用本机 Chrome 登录态 |
| 美团报表 iframe 下载 | 「自助营业取数」用 `evaluate --expect` 触发一次，并核验 Chrome 临时原件 |
| 支持点选的其他直接下载 | `bsk download <trigger> --out <path>` 一次点击并捕获，完成后校验原件 |
| 本地续轮 | `workbuddy/scripts/wb_state.py` 保存哈希链状态，中央关轮通过 MCP 读回 |
| 定时规格 | `workbuddy/scripts/wb_schedule.py` 渲染 PAUSED 规格，时间表由员工确认 |
| 邮件 | WorkBuddy 邮件身份与中央冻结的 `allowedSender` 不符，且缺逐字节 `provider_readback`，记录 blocked，文件本地交付 |

浏览器操作以[网页操作手册](references/browser-skill.md)为准。每轮先检查 daemon、扩展连接和
当前账户，使用自建 Agent Window。登录过期、扩展失联或 Chrome 退出时，保留待续范围，
将来源阶段记为 `blocked`。邮箱阻塞的工作流保留审阅表或最终 HTML，以 `partial` 关轮。

WorkBuddy 通过原生工具分步完成中央 claim/check/record。原宿主的 Goal 接口和注入工具对象的
JS 适配器在这里无对应接口。浏览器 `evaluate` 仅用来操作已确认的页面控件。
真实定时触发仍待验收，定时启动时需能在宿主中恢复 daemon，并确认浏览器与登录态可用。
