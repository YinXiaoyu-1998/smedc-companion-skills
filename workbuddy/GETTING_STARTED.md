# 全新用户上手：WorkBuddy + 企业智脑（SMEDC）配套 Skills

这份文档是**唯一入口**。它面向一台还没装过任何东西的电脑：从零开始，到能跑通
「每日美团入库」的来源采集（导出并下载一份原始 XLSX，不上传 SMEDC）。

**先说清楚**：前置步骤里确实有几件需要你本人手动做的事（装 CLI、装浏览器扩展、
配对、登录美团）。这些属于 WorkBuddy 宿主与其浏览器组件自身的要求，无法由 agent 代劳，
但绝大多数**只需要做一次**。文档会逐步给出命令、链接和验证方式；每一步都可以用
`preflight.py` 检查「现在还缺什么」。

## 第 0 步：先跑环境自检

```bash
git clone https://github.com/YinXiaoyu-1998/smedc-companion-skills.git
cd smedc-companion-skills
python3 workbuddy/scripts/preflight.py
```

`preflight.py` 是**只读**的，不安装、不写配置、不启动进程。它按当前 profile 逐项检查，
输出 `[ OK ]` / `[ WARN ]` / `[ MISS ]`，最后给一份「还需要做（N 项）」清单，每项都带
具体修复命令。装完任何东西后重跑一次，直到没有 `MISS`。需要机器可读结果时加 `--json`。

## 第 1 步：选一套 profile（两套互斥，只能启用一套）

| | browser-skill profile（**推荐**） | web-access profile |
| --- | --- | --- |
| 适合 | 定时自动同步、无人值守 | 零额外安装、员工在场的单次手工导出 |
| 一次性配置 | 装 `bsk` CLI + Chrome 扩展 + 配对 + 美团登录 | `config.env` 浏览器偏好 |
| 每次运行 | agent 自动确认 daemon 并拉起，**无人工授权弹窗** | **Chrome 每次连接都弹「允许」，新浏览器会话要重做** |
| 下载 | `bsk download --out`；美团 iframe 报表需走事件序列 + 临时文件落地（见手册第 6 节） | 手工校验/重命名 `.com.google.Chrome.*` 临时文件 |
| 无人值守 | 有条件可行（daemon/扩展在线即可） | **不可靠，不推荐** |

**本仓库推荐 browser-skill profile**，因为定时同步最怕「每次要人点允许」。若你只要偶尔手动
导一份、不想装任何额外组件，选 web-access。两套从同一份未改动的 `skills/` 源码生成，
随时可用安装器切换。

> 装完后，判断当前是哪一套：读任意已安装 skill 的 `SKILL.md` 顶部，
> 「WorkBuddy 宿主适配 · browser-skill profile」或「WorkBuddy 宿主适配」（web-access）。
> 两个 profile 的手册可能同时残留在 `workbuddy/references/` 下，**只读与你当前 profile
> 对应的那一份**（`browser-skill.md` 或 `web-access.md`），不要混用。

## 第 2 步：准备基础环境

```bash
# 1) 核心 skill 仓库（登录 SMEDC 需要）
git clone https://github.com/YinXiaoyu-1998/smedc-mcp-skill.git /tmp/smedc-mcp-skill
mkdir -p ~/.workbuddy/skills
cp -R /tmp/smedc-mcp-skill/skills/smedc-mcp ~/.workbuddy/skills/smedc-mcp

# 2) 配套 skills 仓库（本仓库，第 0 步已 clone）
# 3) Node.js 22+（web-access profile 必需；browser-skill profile 也建议装）
node --version
```

WorkBuddy 的 skill 发现根是 `~/.workbuddy/skills`。**不要**把 WorkBuddy 副本装进
Codex 的 `~/.agents/skills`，两个宿主互不干扰。

## 第 3 步（browser-skill profile）：安装浏览器组件

这一节是全新用户最容易卡住的地方，按顺序做：

### 3.1 安装 `bsk` CLI

按官方安装指引操作：<https://github.com/Tencent/BrowserSkill/blob/main/AGENT_INSTALL.md>
安装器默认放到 `~/.local/bin/bsk`（Windows 为 `bsk.exe`，可用 `BSK_INSTALL_DIR` 改位置）。
若命令找不到，先修 `PATH` 或直接用绝对路径，不要重复安装。

```bash
~/.local/bin/bsk --version          # 验证可运行
export PATH="$HOME/.local/bin:$PATH"
```

### 3.2 安装 Chrome 扩展并配对

- 扩展安装与连接步骤：<https://github.com/Tencent/BrowserSkill/blob/main/AGENT_INSTALL.md#4-connect-the-browser-extension>
- 需要远程/配对场景时看：<https://github.com/Tencent/BrowserSkill/blob/main/docs/remote-extension-connection.md>

```bash
BSK_AUTO_START=0 bsk daemon pair    # 若提示 pairing_required
```

把命令给出的 **private link** 粘贴到扩展的连接设置里，等界面显示 Connected / Verified。
配对密钥不要写进日志或报告。独立 `BSK_HOME` 需要单独配对；不要自动开启 skip/trust-local。

### 3.3 启动 daemon 并体检

WorkBuddy 会回收 shell 子进程，所以 daemon 要用宿主的**后台任务**长期运行：

```bash
BSK_AUTO_START=0 bsk daemon start --foreground     # run_in_background: true
# 在另一次工具调用里复查：
BSK_AUTO_START=0 bsk status --json
BSK_AUTO_START=0 bsk browsers --json               # 记下 instance_id
BSK_AUTO_START=0 bsk doctor                        # 不能有 FAIL
```

`status` 里应能看到 `pid`、至少一个 `browsers` 条目、`extension_version`。
`doctor` 报 `version skew`（CLI 与扩展版本不一致）时虽标记 still usable，仍建议
`bsk update` 并重启 daemon。若扩展显示未连接，重跑 3.2 的配对，再 `bsk doctor`。

> 每轮定时运行前 agent 会自己 probe `status`；daemon 不在时会自行用后台任务拉起。
> 这一步**不需要你每次操作**。宿主重启/空闲退出后才可能需要重新拉起。

### 3.4 登录美团（你本人完成，一次即可）

由 agent 打开 Agent Window 后，你在页面里自行登录美团管家；登录态存于同一 Chrome
profile 的 cookie jar，后续复用。agent 不接触密码、验证码、Cookie。
可用 `bsk snapshot` 看到顶部账号信息来确认已登录。

## 第 3 步（web-access profile，备选）：CDP 前置

```bash
node <web-access skill>/scripts/check-deps.mjs        # 首次可能 exit 2
```

1. Chrome 需 >= 144。地址栏打开 `chrome://inspect/#remote-debugging`，启用
   「允许对此浏览器实例进行远程调试」。
2. `exit 2` 表示未设偏好：由你确认后把 `WEB_ACCESS_BROWSER=chrome`（或 `edge`）
   写入 `<web-access skill>/config.env`；单次可用 `--browser chrome` 覆盖。
3. 连接时 Chrome 会弹授权框，点「允许」。成功标志：`proxy: ready (...)` 且
   `curl -s http://localhost:3456/targets` 返回 tab 数组；`/json/version` 返回 404
   或日志 `non-101` 表示授权未通过。
4. 保持 Chrome 运行，不要主动停 CDP Proxy。

**这不是一次性设置**：Chrome 每次请求远程调试会话都会弹「允许」，每个新浏览器会话
还要重新允许。因此无人值守定时采集不能依赖这套 profile，详见
`workbuddy/INSTALL.md` 第 3 节。

## 第 4 步：安装配套 skills

```bash
cd smedc-companion-skills
python3 workbuddy/overlays/build_overlays.py --check       # 确认 overlay 与源码一致

# browser-skill profile（推荐）
python3 workbuddy/bsk/build.py build
python3 workbuddy/bsk/build.py check
python3 workbuddy/bsk/build.py install --root ~/.workbuddy/skills
python3 workbuddy/bsk/build.py verify  --root ~/.workbuddy/skills

# 或者 web-access profile
python3 workbuddy/scripts/install_overlays.py install --root ~/.workbuddy/skills
python3 workbuddy/scripts/install_overlays.py check   --root ~/.workbuddy/skills
```

安装器会把 `skills/<name>/` 完整子树、生成的 overlay 和 `workbuddy/` 运行期文件集
（`GETTING_STARTED.md`、`HOST_MAP.md`、`WORKFLOWS.md`、`INSTALL.md`、对应手册、
`scripts/wb_*.py`）分发进**每个**已安装 skill 的目录，使所有 `workbuddy/...` 引用都能解析。
它只覆盖、不删除，你的本地定制会保留。

装完让 WorkBuddy 重新加载已安装 skill（新开一个会话最稳妥），然后重跑：

```bash
python3 workbuddy/scripts/preflight.py --profile browser-skill
```

直到输出「环境已就绪」。

## 第 5 步：首次运行自检（不上传 SMEDC）

对新会话说：「按每日美团入库的来源采集阶段，下载前一营业日的营业数据原件，不要上传」。

预期链路：`smedc-workflows` 加载 → `wb_state.py resume` → 中央只读身份/配置/权限 →
`bsk` 会话与 `cooperate sync` → 报表中心 → 自助营业取数 → 设置单日营业日期 → 查询 →
导出 → 下载落到 `~/Downloads/.com.google.Chrome.XXXXXX` → 校验完整性 →
复制到 `~/Downloads/meituan_business_YYYYMMDD_YYYYMMDD.xlsx` → 报告绝对路径。

**美团 iframe 报表的已知陷阱**（两条 profile 都会遇到）：业务控件在 iframe 内，
普通 click 不生效；需按对应手册（`browser-skill.md` 第 6 节 / `web-access.md` 第 4 节）
用完整鼠标事件序列派发一次，再处理临时文件。手册里有可直接复制的命令与脚本，
**不要反复重试点击**（会生成多份导出任务）。

首次自检只做「下载 + 本地校验」，**不要上传**。上传 SMEDC 需要你另行明确要求，且走
核心 skill `smedc-mcp` 的权限与原文件规则。

## 常见问题

| 现象 | 处理 |
| --- | --- |
| `preflight.py` 报多处 MISS | 按输出顺序逐项修复，每修一项重跑一次 |
| `bsk: command not found` | `export PATH="$HOME/.local/bin:$PATH"`，或用绝对路径 |
| `extension connected` 为 0 | 重做第 3.2 配对；`bsk doctor` 看 hint |
| `daemon start` 后立刻退出 | 必须用宿主后台任务机制跑 `--foreground`，不要 `nohup` / `&`；另一次调用复查 status |
| `permission_denied: observation_required` / `observation_changed` | `evaluate` 用 `--expect` 并省略 `--observation`（见 `browser-skill.md` 第 6 节） |
| `target_covered` / `element_not_visible` | iframe 几何缺失，按手册派发事件序列，不要重试几何点击 |
| `waitForEvent` / 系统保存框 | 这些是原宿主机制，本副本已移除，不要从旧资料里照抄 |
| 两个手册同时存在 | 只读 SKILL.md 顶部标记对应的那一份 |
| 想切换 profile | 重跑另一套安装器即可（会覆盖同名 skill），再让 WorkBuddy 重载 |

## 边界（安装本身不会做的事）

- 不启用租户、不授予上传/发布/发信权限、不改变中央配置。
- 不创建定时任务；`wb_schedule.py` 只渲染 PAUSED 规格，确切时间表必须由你确认。
- 邮件阶段因宿主发件人身份与中央 `allowedSender` 不一致、且缺原生读回，按官方降级
  记为 blocked + 本地交付，整轮 `partial`。
- 下载的原始文件属于第三方业务数据，**不要提交进任何仓库**；默认落在 `~/Downloads`。
