# WorkBuddy 网页交互：`web-access` / CDP 路径

本文件是 WorkBuddy 宿主下所有「打开网页 → 查询 → 导出 → 下载原件」步骤的**权威指引**。
凡是业务 skill 里针对原宿主写的浏览器选择、内置浏览器、系统保存框、下载事件等待、
事件注册、截图定位等段落，在 WorkBuddy 副本中一律以本文件为准。业务筛选条件、原件
字节完整性、日期／门店／口径对账、证据留存与清理门槛**不受影响**，仍按各 skill 原文执行。

本文件不含企业名、门店名单、来源账号、收件人或时间表，这些值在运行时从中央冻结快照读取。

## 1. 先判断这条路能不能走

| 能力 | WorkBuddy 状态 | 前置条件 |
| --- | --- | --- |
| 加载 `web-access` skill、启动 CDP Proxy | 支持 | 宿主已安装该 skill；Node.js 22+ |
| 直连用户日常 Chrome/Edge，复用登录态 | 支持 | 按 `web-access` 的原生前置配置完成浏览器远程调试授权；来源站点由员工自行登录 |
| 页面内导航、DOM 读写、点击、滚动、截图 | 支持 | CDP Proxy 已连接 |
| 穿透 iframe / Shadow DOM 定位业务控件 | 支持 | 见第 4 节 |
| 触发导出并把原件落到本机、校验、重命名 | 支持 | 见第 5 节 |
| 日期口径计算（北京时间、前一营业日、自然周） | 支持 | 本地 `date` / Python 标准库 |
| 原生 `mcp__smedc__*` 中央动作（claim/check/record、上传） | 支持 | 核心 skill 已登录并取得当前权限 |
| 定时触发的来源采集 | **不保证可用** | CDP 授权不是一次性的，见下节；授权失效时该来源阶段记为 blocked，不得伪造或空跑 |
| `waitForEvent("download")` / 45 秒下载事件注册 | **不支持** | CDP Proxy 没有下载事件 API；不要照抄原宿主的 JS 片段 |
| 系统原生「保存」对话框（Open and Save Panel）的 GUI 操作 | **不支持** | 宿主没有窗口级 GUI 控制；下载不走这条路 |
| 静态层（WebFetch / curl / Jina）直接取数 | **不适用** | 后台是需登录态的 SPA，静态层只拿到壳页面；业务数据在 iframe 内 |

> **前置配置的归属**：浏览器远程调试授权、`check-deps.mjs` 的浏览器偏好和连接时的
> 「允许」确认，都是 `web-access` skill 自身要求的前置配置，按它的 SKILL.md 执行即可，
> 不是本适配层额外引入的步骤。Chrome >=144 默认关闭远程调试连接，员工需在地址栏打开
> `chrome://inspect/#remote-debugging` 启用，并在连接弹窗中点「允许」。agent 不代替员工
> 勾选或点确认、不搬运 Cookie、不改 UA、不绕过安全警告，也不反复重试或改走私有客户端。
>
> 反过来，**本适配层不要求安装任何非宿主原生组件**：不安装 `bsk` CLI、不安装 Chrome
> BrowserSkill 扩展、不搭建第二套浏览器通道。任何要求额外安装第三方浏览器桥的旧指引
> 都已从 WorkBuddy 副本中移除。

### 一次性设置，还是每次都要做？

| 项目 | 是否一次设置 | 依据 |
| --- | --- | --- |
| `config.env` 里 `WEB_ACCESS_BROWSER=chrome` | **是**（持久文件） | 避免每次 `check-deps.mjs` 返回 `exit 2` 询问偏好；由员工确认后写入 |
| `chrome://inspect/#remote-debugging` 开关 | **否**（每个浏览器会话） | Chrome 官方中文文档：「您需要在每个新浏览器会话开始时允许远程调试」 |
| 连接时的「允许」授权弹窗 | **否，每次连接请求** | Chrome 官方原文：`every time ... Chrome will show a dialog to the user and ask for their permission` |
| Chrome 保持运行 | **否，每次运行** | 官方注明该连接方式要求用户启动 Chrome；退出后 `DevToolsActivePort` 与调试端口失效 |
| CDP Proxy 长驻 | 尽量保持 | 停止或重启后需重新连接并重新授权 |

**结论：这不是一劳永逸的设置。** 今天做完、过几天的定时自动下载**不能保证可用**：只要
Chrome 重启过、调试会话结束或 Proxy 重连，就可能再次弹出「允许」对话框，需要员工在场点击。
无人值守时该来源阶段应如实记为 `blocked`、整轮 `partial`，不得空跑或伪造结果。

这是 Chrome 的防滥用设计（防止恶意程序静默接管已登录的浏览器），既不是本适配层的缺陷，
也不能通过关闭安全提示或改走私有客户端绕过。若业务要求真正的无人值守采集，当前这条
CDP 路径做不到：只能在员工在场时手动触发，或改用不依赖人工授权的来源接入方式 —— 后者
属于宿主/产品能力变更，不在本适配层范围内。

一手来源：
[Chrome 开发者博客：Chrome DevTools MCP 调试现有浏览器会话](https://developer.chrome.com/blog/chrome-devtools-mcp-debug-your-browser-session)
（M144 引入、每次连接弹窗）、
[Chrome 开发者文档中文版](https://developer.chrome.google.cn/docs/extensions/ai/build-with-ai)
（每个新浏览器会话都要允许）。

## 2. 启动与就绪判断

1. 加载宿主的 `web-access` skill 并按其 SKILL.md 执行前置检查脚本
   `scripts/check-deps.mjs`。`exit 2` 表示浏览器偏好未设置：可用 `--browser <id>` 做本次
   临时覆盖，不要擅自改写员工配置；`exit 1` 按脚本输出的「Agent 处理顺序」先自动恢复
   （如用系统命令唤起浏览器），仍失败再请员工完成授权。
2. 检查通过后，按 skill 要求向员工展示自动化风险须知，再启动 CDP Proxy。
3. Proxy 默认在 `http://localhost:3456`。用 `curl -s http://localhost:3456/targets`
   确认可用；不要操作员工已打开的 tab，所有操作在自己创建的后台 tab 中进行。
4. **`/new` 或 `/navigate` 返回不等于内容就绪。** 它们只代表基础文档加载完成。导航后
   必须用 `/eval` 检查目标业务内容是否真的出现；空白、加载态、验证页、登录跳转都可能
   在默认 15 秒观察窗口内继续变化。只有目标内容已获取、或观察窗口结束后仍有明确阻碍，
   才能继续提取或报告失败。
5. 任务结束用 `/close` 关闭自己创建的 tab，保留员工原有 tab。Proxy 不要主动停止。

## 3. CDP Proxy API 速查

URL 一律通过 **POST body** 原样传入，不要拼进 query，避免带参数的地址被切分；
`target` 走 query。旧资料里 `GET /new?url=...` 的写法已废弃。

```bash
# 列出 tab / 新建后台 tab / 页面信息
curl -s http://localhost:3456/targets
curl -s -X POST --data-raw 'https://pos.meituan.com/web/operation/main#/' http://localhost:3456/new
curl -s "http://localhost:3456/info?target=ID"

# 执行 JS：查询 DOM、读写元素、触发状态变更、提交表单
curl -s -X POST "http://localhost:3456/eval?target=ID" -d 'document.title'

# 点击（JS el.click()）／真实鼠标点击（算用户手势）
curl -s -X POST "http://localhost:3456/click?target=ID" -d 'button.submit'
curl -s -X POST "http://localhost:3456/clickAt?target=ID" -d 'button.upload'

# 导航、截图、滚动、关闭
curl -s -X POST --data-raw 'https://example.com' "http://localhost:3456/navigate?target=ID"
curl -s "http://localhost:3456/screenshot?target=ID&file=/tmp/shot.png"
curl -s "http://localhost:3456/scroll?target=ID&direction=bottom"
curl -s "http://localhost:3456/close?target=ID"
```

`/eval` 是主要的「眼睛和手」：先看页面结构再决定下一步。站点内交互产生的链接是可靠的，
提取 URL 时保留完整参数。`web-access` skill 的 `references/cdp-api.md` 有更详细的
JS 提取模式与错误处理，需要时加载。

## 4. `pos.meituan.com` 站点模式（2026-11 实测）

`web-access` skill 自身的站点经验文件 `references/site-patterns/pos.meituan.com.md`
记录了该后台的经验，确定目标站点后**先读它**。以下是本适配层复用的要点：

- 顶层文档只是一层壳（正文多为续费通知），真正的业务页面在 **iframe** 内。iframe 的
  `src` 与实际文档 URL 不同；判断／定位要按 `contentDocument.location.href`，不要按 `src`。
- `document.querySelectorAll` 找不到 iframe 内元素。用递归 eval 逐层读 `contentDocument`，
  按 `location.href` 关键字匹配目标业务 iframe，再在其中 `querySelector`。
- 业务按钮（如「批量导出」）用 `el.click()` 或 `/click` **不生效**，不触发导出请求。
  必须在目标 iframe 的 `window` 上派发完整鼠标事件序列（2026-11-25 验证）：

  ```js
  const btn = doc.querySelector('button[title="批量导出"]');
  const r = btn.getBoundingClientRect();
  const mk = (type, extra) => new win.MouseEvent(type, {
    bubbles: true, cancelable: true, view: win,
    clientX: r.x + r.width/2, clientY: r.y + r.height/2, button: 0, buttons: 1, ...extra
  });
  btn.dispatchEvent(mk('pointerdown'));
  btn.dispatchEvent(mk('mousedown'));
  btn.dispatchEvent(mk('pointerup', {buttons: 0}));
  btn.dispatchEvent(mk('mouseup', {buttons: 0}));
  btn.dispatchEvent(mk('click', {buttons: 0}));
  ```

  其中 `doc` / `win` 是目标 iframe 的 `contentDocument` / `contentWindow`。
- 判定点击是否生效：读该 iframe 的 `performance.getEntriesByType('resource')` 看是否出现
  导出/download 请求，或观察下载目录是否出现 `.com.google.Chrome.*` 临时文件。
  不要凭「按钮被点过」就认定导出已提交。
- `/clickAt` 是真实鼠标手势，需要触发文件选择框时用；本套下载流程优先用上面的事件序列，
  因为它能穿透 iframe 并在正确的 `window` 上派发。

站点经验是会过期的提示而非保证。按经验操作失败时回退到「重新看 DOM 结构」的通用模式，
并把验证过的更新写回宿主 `web-access` 的站点经验文件（只写确认过的事实）。

## 5. 下载落地处理（与原宿主的保存框流程不同）

**关键差异**：WorkBuddy CDP 触发的下载不会走标准的 download 事件，也不会弹出可自动操作
的系统保存框。Chrome 会把脚本触发的下载记为中断状态（History 的 downloads 表
`target_path` 为空、`state=2`、`received_bytes=0`），文件停留在
`~/Downloads/.com.google.Chrome.XXXXXX` 之类的临时名。因此：

1. 点击导出／下载**之前**先记录本次目标目录、期望文件名、日期范围和当前下载目录里已有的
   临时文件集合，便于事后区分「本次新增」。
2. 点击**一次**。批量导出通常是异步生成，大文件写入临时文件后大小会稳定；不要因为文件名
   还是临时名就以为失败而重复点击，重复点击会生成多份导出任务。
3. 有界等待并观察临时文件大小是否稳定。若页面提供异步下载清单／导出任务，按本次
   报表、申请时间和状态定位任务，生成中不视为已下载；等待须有界，超时保留任务标识和
   进度，续跑先查旧任务，不重复提交导出。
4. 对候选临时文件做**完整性校验**，通过后才复制到目标路径并重命名：

   ```python
   import hashlib, re, shutil, zipfile
   from pathlib import Path

   def land_download(temp: Path, dest: Path) -> dict:
       with zipfile.ZipFile(temp) as z:
           assert z.testzip() is None, "CRC 校验失败"
           names = z.namelist()
           assert "[Content_Types].xml" in names and "xl/workbook.xml" in names
           sheets = [n for n in names if re.match(r"xl/worksheets/sheet\d+\.xml$", n)]
           assert sheets, "没有工作表"
           rows = sum(len(re.findall(rb"<row\b", z.read(n))) for n in sheets)
       assert rows > 0, "工作表无数据行"
       if dest.exists():                       # 同名先核验，不静默覆盖
           if hashlib.sha256(dest.read_bytes()).digest() == hashlib.sha256(temp.read_bytes()).digest():
               return {"path": str(dest), "reused": True, "rows": rows}
           raise ValueError("同名文件内容不同，改用新的批次/运行子目录")
       shutil.copy2(temp, dest)               # 保留原始字节
       assert hashlib.sha256(dest.read_bytes()).digest() == hashlib.sha256(temp.read_bytes()).digest()
       temp.unlink()                          # 只在校验通过后删除临时文件
       return {"path": str(dest), "reused": False, "rows": rows}
   ```

   ZIP 类原件（如收货单批次）同样先 `ZipFile.testzip()`，再检查成员路径不含绝对路径／
   `..` 越界／符号链接，解压到该批独立目录。
5. 完成判据是**本地文件**实际存在、非空、日期／范围正确、XLSX/ZIP 结构完整、与页面
   查询结果对得上。下载事件返回、页面「完成」提示、临时文件出现，都不能单独作为成功依据。
6. 排除 HTML 错误页、`.crdownload`、未写完的临时文件；验证失败保留原文件与错误原因，
   报告阻塞，不重放上传。

## 6. 日期口径

所有相对日期按北京时间解析，续跑保持原范围，不硬编码演示日期。用命令取真实时间，
不要心算时间戳：

```bash
TZ=Asia/Shanghai date "+%Y-%m-%d %H:%M:%S %Z"
TZ=Asia/Shanghai date -v-1d "+%Y-%m-%d"     # macOS(BSD date)：前一自然日
TZ=Asia/Shanghai date -d "yesterday" "+%Y-%m-%d"   # GNU date(Linux)
```

自然周边界、跨月分段和逐日导出用 Python `datetime` / `zoneinfo` 计算，逐段保留
原始请求边界，首尾截到请求日期，保证无遗漏、无重叠。

## 7. 安全边界与失败处理

- 不读取、记录或迁移 Cookie、密码、验证码、下载签名 URL；错误只报告安全摘要。
- 不把下载地址当普通网页导航，不把行级营业／评价数据贴进聊天。
- 登录由员工在官方页面完成；目标内容拿不到且判断登录能解决时，请员工登录后再继续，
  不索取凭据。
- 远程调试授权失效、浏览器不在线、Proxy 连不上：保存精确阻塞与待续范围，标记该来源
  阶段 blocked；其他已获授权且可独立验证的阶段仍可继续。整轮按 `partial` 收尾，
  不得描述为 `succeeded`。
- 中央动作（上传、评价同步、发布、邮件）仍只通过原生 `mcp__smedc__*` 工具分步完成，
  不自建 HTTP／JSON-RPC／私有客户端。浏览器采集成功只证明取得原件，不证明同步或入库成功。
