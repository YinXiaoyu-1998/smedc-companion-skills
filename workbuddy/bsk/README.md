# browser-skill profile（可选第二套宿主路径）

这一目录提供与 `workbuddy/overlays/`（web-access / CDP Proxy profile）**互斥**的第二套
WorkBuddy 适配：用宿主 `browser-skill`（`bsk` CLI + Chrome 扩展 Agent Window）完成网页采集。

两套 profile 都从**同一份未改动的 `skills/` 源码**生成，都不修改 Codex 源文件。一次安装
只启用其中一套；`workbuddy/bsk/build.py install` 会把选中的那套覆盖到 WorkBuddy 发现根。

## 为什么会有两套

| | web-access profile | browser-skill profile |
| --- | --- | --- |
| 浏览器通道 | CDP Proxy `localhost:3456` 直连 Chrome | `bsk` CLI + Chrome 扩展 Agent Window |
| 一次性配置 | `config.env` 偏好 | CLI 安装 + 扩展安装 + 配对 |
| **每次运行的人工授权** | **需要**（Chrome 每次远程调试连接都弹「允许」，新浏览器会话要重做） | **不需要**（配对持久，daemon 由 agent 自行保证） |
| 美团登录态 | 复用日常浏览器 cookie | 复用同 profile cookie jar（持久） |
| 下载 | 无 download 事件 API，需手工校验/重命名 `.com.google.Chrome.*` 临时文件 | `bsk download --out` 原生落盘 |
| iframe | 手写递归 `eval` 穿透 `contentDocument` | VOM `@eN` refs（选择器只搜主文档） |
| 主要代价 | 无人值守不可靠 | 需额外安装 CLI + 扩展；SKILL.md 示例与实际 CLI 有出入；daemon 需常驻 |

完整命令表、配置步骤、版本陷阱与下载规则见 [`references/browser-skill.md`](references/browser-skill.md)。

## 使用

```bash
# 生成 / 校验 overlay
python3 workbuddy/bsk/build.py build
python3 workbuddy/bsk/build.py check

# 安装到 WorkBuddy 发现根（会覆盖该根下同名 skill，不碰 Codex 的 ~/.agents/skills）
python3 workbuddy/bsk/build.py install --root ~/.workbuddy/skills
python3 workbuddy/bsk/build.py verify --root ~/.workbuddy/skills

# 切回 web-access profile
python3 workbuddy/scripts/install_overlays.py install --root ~/.workbuddy/skills
```

`build.py` 复用 `workbuddy/overlays/build_overlays.py` 的章节级替换机制，只替换浏览器、
下载、宿主能力等章节与顶部优先级说明；业务筛选、原件校验、证据与清理门槛保持不变。
