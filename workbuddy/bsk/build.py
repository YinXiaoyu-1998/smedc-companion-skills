#!/usr/bin/env python3
"""Generate / install the browser-skill (bsk) profile of the WorkBuddy overlays.

Reuses the section-aware generator in ``workbuddy/overlays/build_overlays.py``
but substitutes the browser/download/host chapters for ``bsk`` equivalents.
The repository's ``skills/`` tree is read-only here, exactly as in the
web-access profile; Codex sources stay byte-for-byte unchanged.

    python3 workbuddy/bsk/build.py build
    python3 workbuddy/bsk/build.py check
    python3 workbuddy/bsk/build.py install --root ~/.workbuddy/skills
    python3 workbuddy/bsk/build.py verify  --root ~/.workbuddy/skills
"""

from __future__ import annotations

import argparse
import importlib.util
import shutil
import sys
from pathlib import Path

BSK = Path(__file__).resolve().parent                 # workbuddy/bsk
WORKBUDDY = BSK.parent                                # workbuddy
ROOT = WORKBUDDY.parent                               # repository root
SKILLS = ROOT / "skills"
OUT = BSK / "generated"
MANUAL = "`workbuddy/references/browser-skill.md`"

BROWSER_SECTION = f"""## 浏览器选择（browser-skill 特化）

本副本使用宿主 `browser-skill`（`bsk` CLI + Chrome 扩展的 Agent Window），直连员工日常
Chrome profile 并复用其登录态。**不使用** CDP Proxy / `web-access` 通道。完整命令表见
{MANUAL}。

- 一次性配置：安装 `bsk` CLI、安装 Chrome 扩展、完成 `bsk daemon pair` 配对、
  `bsk doctor` 全绿；美团登录由员工在页面完成，cookie 持久。
- 每轮运行：确认 daemon 在跑（`BSK_AUTO_START=0 bsk status --json`）。WorkBuddy 会回收
  shell 子进程，daemon 不在时用宿主后台任务启动
  `BSK_AUTO_START=0 bsk daemon start --foreground`，并在**另一次**调用里复查 status。
  这一步由 agent 自行完成，不需要员工操作。
- 会话：`bsk session start --browser <instance-id> --no-focus --json` →
  `bsk navigate --session <SID> <URL>` → `bsk cooperate sync --session <SID> --policy target`
  → `bsk snapshot` / `bsk observe`；结束 `bsk session stop <SID>`。
- **只用 CLI 实际存在的子命令**：`bsk open`、`navigate --url`、`evaluate --expression`
  在本机 CLI 上不存在（自带 SKILL.md 示例与实际版本有出入），一律以 `bsk <cmd> --help`
  为准，见 {MANUAL} 第 3 节。
- 全部操作在 Agent Window 自建 tab 内完成，不借用员工标签页（默认
  `borrow_confirmation: always` 会要求确认）。不读取 Cookie/凭据、不改 UA、不绕过确认。

"""

DOWNLOAD_SECTION = f"""## 下载落地与恢复（browser-skill 特化）

`bsk` 有原生下载捕获（`bsk download --out`），但 **2026-11-25 在美团「自助营业取数」
真实导出中该路径不可用**：业务控件在 iframe 内，VOM 报 `geometry incomplete`，
`download` / `click` / `scroll-to` 均返回 `target_covered`。此时按
{MANUAL} 第 6 节改用 `evaluate --expect` 派发完整鼠标事件序列，并校验、
重命名 `.com.google.Chrome.*` 临时文件。**不要反复重试点击**（会生成多份导出任务）。
下面的通用规则适用于 `bsk download` 可用的场景；两条路径最终都以本地文件校验为准。

1. 先完成筛选与按钮定位，再 `bsk cooperate sync --session <SID> --policy target --json`
   取得 `context_id` / `observation_id`。点击型下载必须带这两个值。
2. 用 `bsk download <trigger> --out <绝对路径> --session <SID> --context <CTX>`
   `--observation <OBS> --timeout 2m --json` 一步完成点击、捕获与落盘。
   `trigger` 是本轮快照核实的 `@eN` ref 或 CSS 选择器；**iframe 内控件必须用 ref**。
3. 默认拒绝覆盖；只有明确要替换时才加 `--overwrite`。同名先核验，不静默覆盖。
4. `download_path_mismatch` 表示浏览器把文件落到别处、`--out` 没产出：在浏览器下载列表
   找到该文件，决定使用或删除后再决定是否重试，不要盲目重复点击导出。
5. 超时、`dialog_pending` 或 `effect_state: unknown` 时先 `bsk sync` 检查状态，
   **绝不重放写动作**。异步导出按本次报表、申请时间与状态定位，有界等待，生成中不视为已下载。
6. 以本地文件实际存在、非空、日期/范围正确、XLSX/ZIP 完整性作为完成依据：
   ZIP `testzip()`，XLSX 检查 `[Content_Types].xml`、`xl/workbook.xml` 与工作表行数。
   工具返回成功不替代文件校验。

业务筛选、分段策略、原件字节完整性、证据留存与清理门槛仍按本 skill 其余章节执行。

"""

COMPAT_SECTION = f"""## 智能体与工具兼容性（browser-skill 特化）

本技能描述通用业务流程。在 WorkBuddy 的 browser-skill profile 下，浏览器操作使用
`bsk` CLI，本地文件检查使用命令行与 Python 标准库；完整指引见 {MANUAL}。
原文列举的其他宿主接口不适用于本副本；缺少相应能力时按该手册第 1 节如实报告阻塞。
业务筛选、原件校验、证据与清理门槛保持不变。

"""

RECORDING_NOTE = """## 录制证据范围（原宿主历史记录）

本节在原宿主 SKILL.md 中记录的是该宿主当时的界面观察，不构成 WorkBuddy 的操作依据，
也不证明这些行为在当前站点仍然成立。本副本不沿用其浏览器与下载结论，一律以
`workbuddy/references/browser-skill.md` 为准。业务侧的日期口径、筛选、字段与原件校验
要求仍以本 skill 正文和中央冻结快照为准；未改动的原始记录保留在仓库 `skills/` 下。

"""

COMBO_SECTION = f"""## 查询和导出（browser-skill 特化）

1. 按 {MANUAL} 第 4 节启动 `bsk` 会话，打开
   `https://pos.meituan.com/web/operation/main#/` 或复用已登录的美团后台标签。
   登录、验证码由员工在页面完成。
2. 进入 **报表中心 → 营业报表 → 套餐销售统计**。菜单不可用时，可尝试录制中观察到的直达页 `https://pos.meituan.com/web/report/pack-sale#/rms-report/pack-sale`。确认标题、统计方式和营业日期控件，按当前可见控件操作。
3. **统计方式**选「套餐明细」。在「营业日期」的两个日期控件中选择同一个营业日，分别核对起止值。打开门店树，选用户要求的门店并核对实际勾选项；勾选「按门店统计」。在「更多筛选」中勾选「显示菜品规格」，取消「同名菜品合并统计」。菜品分类、菜品名称、订单分类、菜品下单来源均选「全部」，以取得可入库的完整门店日来源。
4. 每次修改日期或筛选后，点「查询」，等待结果刷新，复核当前条件后再点「导出」。只有当前查询明确无数据时才将该日标为无数据。表格当前页条数不能代表全量。页面若提示额外限制，保留已确认范围并报告该限制。
5. 点击「导出」前先 `cooperate sync` 取得控制 context，再用
   `bsk download <@eN> --out <路径> --session <SID> --context <CTX> --observation <OBS>`
   一次点击并落盘。若页面转入「下载清单记录」，按本次套餐报表、营业日和申请时间定位任务，
   有界等待生成完成后再下载；只在确认没有进行中的导出或下载后才重试。

"""

TAKEOUT_SECTION = f"""## 打开报表（browser-skill 特化）

按 {MANUAL} 第 4 节启动 `bsk` 会话并打开
`https://pos.meituan.com/web/operation/main#/`（或复用已登录标签）。登录与验证码由员工
在页面完成，不迁移 Cookie。daemon 不可用时由 agent 自行拉起，不切换到其他浏览器通道。

1. 打开 **报表中心 → 平台外卖订单明细**，以标题及门店、订单来源、外卖订单号、收银订单号等列确认报表。导航不可用时，在同一会话尝试录制观察到的直达页 `https://pos.meituan.com/web/report/orderListWM#/rms-report/orderListWM`，随后核对标题。不要混用店内或全渠道订单明细。
2. 先按“长范围优先按月导出”规划当前段，再按“本次输入”设置日期口径、该段起止范围、门店、订单集合、状态及其他筛选。历史月份按当前和目标年月定位，不重放录制中的点击次数。菜单切换、重置及导航后重新读取最终筛选。
3. **每次修改搜索参数或订单集合标签后，都先点“查询”，等待刷新完成并核对，再点“导出”**。查询后又改任何参数，必须重新查询。记录实际生效条件和可见总条数（如提供）；一页行数不是总数。零结果如实报告，不创建假数据。

"""

WORKFLOW_BROWSER_REF = f"""# 浏览器选择与恢复（browser-skill 特化）

本 profile 只使用宿主 `browser-skill` 的 `bsk` CLI，完整指引见 {MANUAL}。
CDP Proxy / `web-access` 通道的规则在这里**不适用**。

1. 一次性配置是 CLI + 扩展 + 配对 + `bsk doctor` 全绿；美团登录态走同 profile cookie jar，
   持久有效。每轮只需确认 daemon 在跑，agent 可自行拉起，无需员工每次授权。
2. 复用同一 Agent Window 会话完成查询、导出、下载清单与文件落地；换会话前先核对已发
   导出是否仍在生成，保留 runId、日期窗口、导出 ID 和重试计数。
3. daemon 或扩展不可用时保存精确阻塞与待续范围，只阻塞相关来源阶段；其他已获授权且
   可独立验证的阶段继续，整轮按 partial 收尾。
4. 不搬运 Cookie、不改 UA、不猜接口、不绕过 borrow 确认或扩展的 Automation 设置。

本文件由 `workbuddy/bsk/build.py` 生成，请勿手工编辑。
"""

HOST_REF_NOTE = f"""> **WorkBuddy 副本（browser-skill profile）：本文件不适用**

本文件描述原宿主的运行机制，在本副本中整体不适用，且未做逐句改写，以免产生似是而非的
等价指令。权威运行规则见 `workbuddy/HOST_MAP.md`、`workbuddy/WORKFLOWS.md` 与
{MANUAL}；中央 claim/check/record、证据与清理门槛以 `workbuddy/WORKFLOWS.md` 和中央
冻结快照为准。未改动的正本保留在仓库 `skills/` 下供审阅对照。
"""

BANNER = """<!-- WorkBuddy overlay (browser-skill profile). Generated by workbuddy/bsk/build.py.
     The Codex source files in skills/<name>/ are unchanged. Apply this overlay
     only inside the WorkBuddy skill discovery root. -->

"""

HOST_NOTE = f"""## WorkBuddy 宿主适配 · browser-skill profile（最高优先级）

本副本是 **browser-skill 特化版**，与 web-access / CDP Proxy profile 互斥。下文及本 skill
的 references 中，凡涉及浏览器选择、登录态、下载等待、宿主工具或定时任务的段落，
若与本节冲突，一律以本节、{MANUAL} 和 `workbuddy/HOST_MAP.md` 为准；
业务筛选、原件校验、证据与清理门槛保持不变。

- 浏览器：`bsk` CLI + Chrome 扩展 Agent Window，复用同 profile 登录态。配对是一次性的，
  daemon 由 agent 每轮确认/拉起，**没有每次人工授权弹窗**。
- 下载：`bsk download --out` 原生落盘；不需要处理 Chrome 临时文件或系统保存框。
- 只用 CLI 真实存在的子命令（见手册第 3 节）；不要用 `bsk open` / `--url` / `--expression`。
- 定时与续轮：无 Goal 生命周期，用 `workbuddy/scripts/wb_state.py` 的本地 run 状态文件；
  时间表由员工确认后才通过宿主 `automation_update` 安装。定时触发时若 daemon/扩展不可用，
  来源阶段记为 blocked、整轮 partial。
- 邮件：宿主邮件身份与中央冻结的 `allowedSender` 不一致，且缺原生读回能力，按官方降级
  记为 blocked + 本地交付，见 `workbuddy/scripts/wb_mail.py`；不换发件人、不发信。
- 中央动作仍只通过原生 `mcp__smedc__*` 工具完成；不另写 HTTP、JSON-RPC 或私有客户端。
- 原宿主流程不受影响：仓库内 `skills/` 下任何文件都未被本 overlay 修改。


"""

REFERENCE_NOTE = f"""> **WorkBuddy 宿主优先级（browser-skill profile）**：本文件涉及浏览器选择、登录态、
> 下载等待、宿主工具与定时任务的段落，一律以 {MANUAL}、`workbuddy/HOST_MAP.md`、
> `workbuddy/WORKFLOWS.md` 以及 SKILL.md 顶部的优先级章节为准。业务筛选、原件校验、
> 证据与清理门槛不变。此文件由 `workbuddy/bsk/build.py` 生成，请勿手工编辑。

"""

WORKFLOWS_SKILL = """---
name: smedc-workflows
description: >-
  WorkBuddy 宿主（browser-skill profile）的企业智脑（SMEDC）工作流入口：每日美团入库、
  评价处理和自然周经营周报。分别选择、复用官方核心与业务技能；原宿主与 web-access profile
  请使用各自的 SKILL.md。
---

<!-- WorkBuddy overlay (browser-skill profile). Generated by workbuddy/bsk/build.py. -->

# 企业智脑工作流（WorkBuddy · browser-skill profile）

仓库 `skills/smedc-workflows/` 的原版文件一个字节都未改动；本副本与 web-access profile 互斥。

1. 先读 `workbuddy/bsk/README.md`、`workbuddy/HOST_MAP.md` 与
   `workbuddy/references/browser-skill.md`，确认能力映射和已知限制。
2. 安装与覆盖见 `workbuddy/bsk/README.md`；三个工作流的具体运行见 `workbuddy/WORKFLOWS.md`。
3. 中央配置、身份、指定安装、claim/check/record 全部通过原生 `mcp__smedc__*` 工具读取和提交；
   不自建 HTTP、JSON-RPC 或调度客户端。
4. 定时运行：宿主 `automation_update` 只创建 PAUSED 任务，确切时间表必须员工确认；
   未结束轮用 `workbuddy/scripts/wb_state.py` 的本地状态文件续接，不另开第二轮。
   每轮先确认 `bsk` daemon 与扩展连接；不可用时来源阶段如实记为 blocked、整轮 partial。
5. 浏览器来源读取使用 `bsk` CLI 的 Agent Window（配对一次、登录态持久、daemon 由 agent
   保证），下载用 `bsk download --out` 原生落盘。完整命令表见
   `workbuddy/references/browser-skill.md`。不借用员工标签页、不改扩展 Automation 设置。
6. 邮件阶段按官方降级：`workbuddy/scripts/wb_mail.py plan` 记录 blocked 并本地交付，不发信。
7. 安装本身不启用任务、不授予发布或发信权限；评价发布仍须中央现行持续授权内的门店与稿件批准。

正常完成只留简短结果；需要人工处理时指出精确缺项。
"""

# Runtime adapter files distributed into each installed skill so that
# workbuddy/... references resolve from the installed skill directory.
ADAPTER_FILES = {
    "README.md": BSK / "README.md",
    "bsk/README.md": BSK / "README.md",
    "HOST_MAP.md": BSK / "HOST_MAP.md",
    "WORKFLOWS.md": BSK / "WORKFLOWS.md",
    "INSTALL.md": BSK / "INSTALL.md",
    "references/browser-skill.md": BSK / "references/browser-skill.md",
    "scripts/wb_state.py": WORKBUDDY / "scripts/wb_state.py",
    "scripts/wb_schedule.py": WORKBUDDY / "scripts/wb_schedule.py",
    "scripts/wb_mail.py": WORKBUDDY / "scripts/wb_mail.py",
    "scripts/wb_browser.py": WORKBUDDY / "scripts/wb_browser.py",
}
SKIP_PARTS = {"__pycache__", ".DS_Store"}
SKIP_SUFFIXES = {".pyc"}


def load_base():
    spec = importlib.util.spec_from_file_location(
        "wb_overlays", WORKBUDDY / "overlays" / "build_overlays.py")
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


# Whole-sentence replacements that must run before the generic word fixes.
# They rewrite the download/save-panel advice for bsk's native `--out` capture.
BSK_SENTENCES = (
    ("取得本次请求范围内的原始 `.xlsx`，完成本地保存与只读验证。使用 **Computer Use** 操作浏览器及必要的原生保存窗口；当前环境若有明确覆盖此报表的专用工具，优先使用其等价查询、导出和保存能力。读取当前工具文档后再调用，以下接口名只适用于提供相应能力的环境。",
     "取得本次请求范围内的原始 `.xlsx`，完成本地落地与只读验证。浏览器操作使用宿主 `browser-skill` 的 `bsk` CLI，下载落地见 `workbuddy/references/browser-skill.md` 第 6 节。"),
    ("取得指定日期口径、时间范围、门店及订单状态的原始 `.xlsx`，完成本地保存并验证。使用 Computer Use（浏览器及必要的原生窗口操作）完成美团界面流程；若当前环境有覆盖此报表的专用工具，优先使用等价的查询、导出和保存能力。",
     "取得指定日期口径、时间范围、门店及订单状态的原始 `.xlsx`，完成本地落地并验证。浏览器操作使用宿主 `browser-skill` 的 `bsk` CLI，下载落地见 `workbuddy/references/browser-skill.md` 第 6 节。"),
    ("需要浏览器读取/操作、公开信息检索及本地 XLSX 生成/检查能力。先读当前工具文档，使用运行环境实际支持的接口；Codex 的 `cua_repl`、`tab.playwright`、`iab` 只是示例，不假定其他智能体具备它们。",
     "需要浏览器读取/操作及本地 XLSX 生成/检查能力。在 browser-skill profile 下浏览器操作使用 `bsk` CLI，见 `workbuddy/references/browser-skill.md`；本地文件检查使用命令行与 Python 标准库。"),
    ("导出可能很快完成并直接打开系统保存对话框", "导出可能很快完成并直接触发下载"),
    ("若直接出现保存对话框，就选择目标目录，按实际日期命名，保留 `.xlsx` 后保存。",
     "若直接触发下载，用 `bsk download --out <路径>` 直接落盘并按实际日期命名，保留 `.xlsx`。"),
    ("5. 若直接出现保存对话框，进入下一步。", "5. 若直接触发下载，进入下一步。"),
    ("6. 在保存对话框选择目标目录，按实际日期命名并保留 `.xlsx` 后保存。",
     "6. 用 `bsk download --out <路径>` 落地到目标目录，按实际日期命名并保留 `.xlsx`。"),
    ("4. 等待生成并检查原生保存窗口。演示中的首批生成约需 40 秒；短暂没有窗口不等于失败。分段检查生成状态和保存窗口，不反复点击导出。",
     "4. 有界等待生成，用 `bsk snapshot` / `bsk observe` 分段检查导出状态。演示中的首批生成约需 40 秒；短暂没有下载结果不等于失败，不反复点击导出。"),
    ("按“下载捕获、系统保存框与恢复”先准备捕获，再点 **导出** 一次。",
     "先 `cooperate sync` 取得控制 context，再用 `bsk download --out` 准备落盘，然后点 **导出** 一次。"),
    ("6. 可能直接出现保存框或下载文件，也可能提示 **前往下载清单**。直接下载进入保存与验证；",
     "6. 可能直接触发下载，也可能提示 **前往下载清单**。直接下载用 `bsk download --out` 落盘并验证；"),
    ("**导出完成**后按“下载捕获、系统保存框与恢复”准备捕获，再点该行 **下载**。",
     "**导出完成**后先 `cooperate sync`，再用 `bsk download --out` 落盘并点该行 **下载**。"),
    ("2. 直接出现保存框或下载事件时，进入“下载捕获与保存”。",
     "2. 直接触发下载时，按 `workbuddy/references/browser-skill.md` 第 6 节用 `bsk download --out` 处理。"),
    ("确认该任务显示“下载成功”后点该行“下载”，捕获下载结果或系统保存窗口。下载事件超时不代表没有保存窗口：先检查原生保存框及实际文件，再决定恢复；不能因超时连续点击下载。",
     "确认该任务显示“下载成功”后点该行“下载”，用 `bsk download --out` 捕获并落盘。超时不代表文件不存在：先 `bsk sync` 检查状态、核对 `--out` 目标路径及实际文件，再决定恢复；`effect_state: unknown` 时绝不重放点击。"),
)


def _bsk_wording(text: str) -> str:
    """Rewrite any surviving web-access wording in a legacy replacement value."""
    pairs = (
        ("宿主 `web-access` skill 的 CDP 路径", "宿主 `browser-skill` 的 `bsk` CLI"),
        ("`workbuddy/references/web-access.md` 第 5 节", "`workbuddy/references/browser-skill.md` 第 6 节"),
        ("web-access.md 第 5 节", "`bsk download --out`（见 browser-skill.md 第 6 节）"),
        ("见 `workbuddy/references/web-access.md`", "见 `workbuddy/references/browser-skill.md`"),
        ("web-access CDP 会话", "bsk Agent Window"),
        ("直接产生下载临时文件", "直接触发下载"),
        ("下载临时文件", "下载结果"),
    )
    for old, new in pairs:
        text = text.replace(old, new)
    return text


def configured() -> dict[str, dict[str, str]]:
    base = load_base()
    base.BANNER = BANNER
    base.HOST_NOTE = HOST_NOTE
    base.REFERENCE_NOTE = REFERENCE_NOTE
    base.WORKFLOWS_SKILL = WORKFLOWS_SKILL
    # bsk-specific sentences first, then the legacy wording fixes with any
    # web-access phrasing rewritten for this profile.
    base.REPLACEMENTS = BSK_SENTENCES + tuple(
        (old, _bsk_wording(new)) for old, new in base.REPLACEMENTS)
    base.SECTION_REPLACEMENTS = {
        "智能体与工具兼容性": COMPAT_SECTION,
        "用 Computer Use 查询和导出": COMBO_SECTION,
        "打开报表": TAKEOUT_SECTION,
        "浏览器选择": BROWSER_SECTION,
        "浏览器与工具": BROWSER_SECTION,
        "浏览器准备": BROWSER_SECTION,
        "下载事件与 ERR_BLOCKED_BY_CLIENT 处理": DOWNLOAD_SECTION,
        "下载捕获与保存": DOWNLOAD_SECTION,
        "下载捕获、系统保存框与恢复": DOWNLOAD_SECTION,
        "录制证据范围": RECORDING_NOTE,
        "录制证据与限制": RECORDING_NOTE,
    }
    base.FULL_FILE_REPLACEMENTS = {
        "smedc-workflows/browser.md": WORKFLOW_BROWSER_REF,
        "smedc-workflows/gmail.md": HOST_REF_NOTE,
        "smedc-workflows/installation.md": HOST_REF_NOTE,
        "smedc-workflows/invocation.md": HOST_REF_NOTE,
        "smedc-workflows/runtime.md": HOST_REF_NOTE,
        "reply-meituan-reviews/browser-recovery.md": HOST_REF_NOTE,
        "reply-meituan-reviews/email-notifications.md": HOST_REF_NOTE,
    }
    return base.generate()


def copy_tree(src: Path, dst: Path) -> int:
    n = 0
    for path in src.rglob("*"):
        if not path.is_file() or any(p in SKIP_PARTS for p in path.parts):
            continue
        if path.suffix in SKIP_SUFFIXES:
            continue
        target = dst / path.relative_to(src)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, target)
        n += 1
    return n


def committed() -> dict[tuple[str, str], str]:
    return {(p.relative_to(OUT).parts[0],
             "/".join(p.relative_to(OUT).parts[1:])): p.read_text(encoding="utf-8")
            for p in OUT.rglob("*.md") if len(p.relative_to(OUT).parts) >= 2}


def cmd_build(_: argparse.Namespace) -> int:
    overlays = configured()
    if OUT.exists():
        shutil.rmtree(OUT)
    OUT.mkdir(parents=True)
    for name, files in overlays.items():
        for rel, text in files.items():
            target = OUT / name / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(text, encoding="utf-8")
    print(f"generated {len(overlays)} skills / {sum(len(f) for f in overlays.values())} files")
    return 0


def cmd_check(_: argparse.Namespace) -> int:
    expected = {(name, rel): text
                for name, files in configured().items() for rel, text in files.items()}
    current = committed()
    problems = []
    for key in sorted(set(expected) | set(current)):
        if key not in current:
            problems.append(f"missing: {key[0]}/{key[1]}")
        elif key not in expected:
            problems.append(f"stale: {key[0]}/{key[1]}")
        elif expected[key] != current[key]:
            problems.append(f"out of date: {key[0]}/{key[1]}")
    if problems:
        print("\n".join(problems), file=sys.stderr)
        return 1
    print(f"ok: {len(expected)} browser-skill overlay files match the sources")
    return 0


def cmd_install(args: argparse.Namespace) -> int:
    root = Path(args.root).expanduser().resolve()
    if root == Path.home() or root == Path.home() / ".agents" / "skills":
        raise SystemExit("refusing to install into a home or Codex discovery root")
    for name in sorted(p.name for p in OUT.iterdir() if p.is_dir()):
        dst = root / name
        dst.mkdir(parents=True, exist_ok=True)
        n = copy_tree(SKILLS / name, dst) + copy_tree(OUT / name, dst)
        for rel, src in ADAPTER_FILES.items():
            target = dst / "workbuddy" / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, target)
            n += 1
        print(f"installed {name}: {n} files")
    print(f"ok: browser-skill profile installed under {root}")
    return 0


def cmd_verify(args: argparse.Namespace) -> int:
    root = Path(args.root).expanduser().resolve()
    problems = []
    names = sorted(p.name for p in OUT.iterdir() if p.is_dir())
    for name in names:
        dst = root / name
        if not dst.is_dir():
            problems.append(f"missing installed skill: {name}")
            continue
        text = (dst / "SKILL.md").read_text(encoding="utf-8")
        if "browser-skill profile" not in text or "bsk" not in text:
            problems.append(f"{name}/SKILL.md: wrong profile")
        # Descriptive mentions ("mutually exclusive with web-access") are fine;
        # only actionable web-access instructions are a profile leak.
        for marker in ("localhost:3456", "workbuddy/references/web-access.md",
                       "按 web-access.md", "check-deps.mjs", "`.com.google.Chrome.*` 临时文件落地"):
            if marker in text:
                problems.append(f"{name}/SKILL.md: web-access instruction {marker!r} survived")
        for rel in ("references/browser-skill.md", "HOST_MAP.md", "WORKFLOWS.md",
                    "INSTALL.md", "bsk/README.md"):
            if not (dst / "workbuddy" / rel).is_file():
                problems.append(f"{name}: adapter file {rel} missing")
        host_map = dst / "workbuddy/HOST_MAP.md"
        if host_map.is_file() and "browser-skill profile" not in host_map.read_text(encoding="utf-8"):
            problems.append(f"{name}: HOST_MAP.md is still the web-access copy")
    if problems:
        print("\n".join(problems), file=sys.stderr)
        return 1
    print(f"ok: {len(names)} installed skills are on the browser-skill profile")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    for cmd, fn in (("build", cmd_build), ("check", cmd_check),
                    ("install", cmd_install), ("verify", cmd_verify)):
        p = sub.add_parser(cmd)
        if cmd in ("install", "verify"):
            p.add_argument("--root", default="~/.workbuddy/skills")
        p.set_defaults(func=fn)
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
