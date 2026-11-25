# Installing the browser-skill profile

本 profile 与 web-access / CDP Proxy profile 互斥；一次安装只启用一套。两者都不修改仓库
`skills/` 下的 Codex 源文件，也**不会**写入 Codex 发现根 `~/.agents/skills`。

```bash
python3 workbuddy/bsk/build.py build
python3 workbuddy/bsk/build.py check
python3 workbuddy/bsk/build.py install --root ~/.workbuddy/skills
python3 workbuddy/bsk/build.py verify  --root ~/.workbuddy/skills
```

安装器把 `skills/<name>/` 完整子树、bsk overlay 和 `workbuddy/` 运行期文件集
（`README.md`、`bsk/README.md`、`HOST_MAP.md`、`WORKFLOWS.md`、`INSTALL.md`、
`references/browser-skill.md`、`scripts/wb_*.py`）分发到每个已安装 skill 的目录内，
使所有 `workbuddy/...` 引用都能解析。它只覆盖、不删除，本地定制会保留。

切回 web-access profile：
`python3 workbuddy/scripts/install_overlays.py install --root ~/.workbuddy/skills`。

## 员工侧一次性配置

1. 安装 `bsk` CLI（默认 `~/.local/bin/bsk`）与 Chrome 扩展，按官方 AGENT_INSTALL.md
   完成 `bsk daemon pair` 配对；配对密钥不要写入日志或报告。
2. `BSK_AUTO_START=0 bsk doctor` 全绿；如有 CLI/扩展 version skew，先 `bsk update`
   并重启 daemon。
3. 在 Agent Window 里由员工自行完成美团登录（cookie 持久，agent 不接触凭据）。

## 每轮由 agent 自动完成

- `BSK_AUTO_START=0 bsk status --json` / `browsers --json` probe；daemon 不在时用宿主
  后台任务拉起 `BSK_AUTO_START=0 bsk daemon start --foreground`，另一次调用复查。
- 每次交互前 `cooperate sync --policy target` 取 `context_id` / 顶层 `observation_id`。
- 结束 `bsk session stop <SID>`；不要借用员工标签页（默认 borrow 需确认）。

完整命令表、版本陷阱与下载规则见 `workbuddy/references/browser-skill.md`。
定时规格仍用 `workbuddy/scripts/wb_schedule.py`（只渲染 PAUSED，确切时间表需员工确认）。
