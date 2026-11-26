#!/usr/bin/env python3
"""Generate, install and verify the BrowserSkill-based WorkBuddy overlays.

    python3 workbuddy/bsk/build.py build
    python3 workbuddy/bsk/build.py check
    python3 workbuddy/bsk/build.py install --root ~/.workbuddy/skills
    python3 workbuddy/bsk/build.py verify --root ~/.workbuddy/skills
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import stat
import sys
import tempfile
from pathlib import Path
from typing import NamedTuple

BSK = Path(__file__).resolve().parent
WORKBUDDY = BSK.parent
ROOT = WORKBUDDY.parent
SKILLS = ROOT / "skills"
OUT = BSK / "generated"
MANUAL = "`workbuddy/references/browser-skill.md`"

HOST_MARKERS = (
    "cua_repl", "tab.playwright", "cua.getApp", "IAB", "iab", "内置浏览器",
    "Computer Use", "mcp__codex_app__", "mcp__codex_apps__", "functions.exec",
    "load_workspace_dependencies", "get_goal", "create_goal", "automation.toml",
    "Gmail", 'tab list("Google Chrome"', "Chrome 原生 app", "Chrome app",
    "waitForEvent", "ERR_BLOCKED_BY_CLIENT", "保存框", "保存对话框", "保存窗口",
)

# Generated overlays must not contain host-specific interfaces, broken JS
# produced by mechanical replacement, or advice that assumes a native Save
# panel / download event API that WorkBuddy does not have.
FORBIDDEN_PATTERNS = (
    r"cua_repl", r"tab\.playwright", r"cua\.getApp", r"cua\.createBrowserTab",
    r"(?<![A-Za-z])[iI][aA][bB](?![A-Za-z])",
    r"内置浏览器", r"内置 Chromium 浏览器", r"Computer Use", r"才回退到",
    r'tab list\("Google Chrome"', r"Chrome 原生 app", r"Chrome app",
    r"mcp__codex_app__", r"mcp__codex_apps__",
    r"gmail_send_email", r"gmail_get_profile", r"gmail_read_email_thread",
    r"gmail_search_email_ids", r"automation\.toml",
    r"waitForEvent", r"timeout_ms", r"downloadIndex", r"ERR_BLOCKED_BY_CLIENT",
    r"web-access", r"const pending",
    r"tab\.click\(", r"\.playwright\.",
    r"保存框", r"保存对话框", r"保存窗口", r"保存面板",
    r"45 秒连续等待", r"60 秒外层", r"连续等待",
)

BROWSER_SECTION = f"""## 浏览器选择（browser-skill 特化）

本副本在 `browser-skill` 的 Agent Window 中使用本机 Chrome 并复用所选实例的登录态。完整命令表见 {MANUAL}。

- 初次配置：安装 `bsk` CLI、启用 Chrome 扩展的本地连接，按需配对，确认 `bsk doctor` 无失败项。
  美团登录或登录过期后的重新认证由员工在页面完成。
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

DOWNLOAD_SECTION = f"""## 下载落地与恢复

先按 {MANUAL} 第 6 节选定本次控件的触发方式，再提交一次。

1. 已验证的美团「自助营业取数」报表 iframe 使用 `evaluate --expect` 的事件序列，
   核对报表、精确 frame URL 和唯一控件后再执行。观察导出任务或新出现的下载，按手册
   校验并落地匹配本次范围的 Chrome 临时文件。
2. 其他页面的目标支持几何点击且可直接下载时，`bsk download <trigger> --out <路径>`
   一次完成点击和捕获，调用前用 `cooperate sync` 取得 context 与 observation。
   文件已开始下载时只观察和校验，异步导出则等待本次任务完成后选定该行的下载控件。
3. 超时、`download_path_mismatch` 或动作结果不明时，先核对下载列表、异步任务和本地
   文件，再决定如何恢复。已有任务或结果未明时保持待续，防止重复提交。
4. 完成以本地原件为准。核对日期、门店和范围，检查文件非空、XLSX/ZIP 结构和内容，
   默认保留已有同名文件。业务筛选、证据和清理门槛见本 Skill 正文及中央冻结快照。

"""

COMPAT_SECTION = f"""## 智能体与工具兼容性（browser-skill 特化）

本技能描述通用业务流程。在 WorkBuddy 中，浏览器操作使用
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

1. 按 {MANUAL} 第 4 节启动 `bsk` 会话，在 Agent Window 打开
   `https://pos.meituan.com/web/operation/main#/`，复用同一 Agent Window 会话。
   登录、验证码由员工在页面完成。
2. 进入 **报表中心 → 营业报表 → 套餐销售统计**。菜单不可用时，可尝试录制中观察到的直达页 `https://pos.meituan.com/web/report/pack-sale#/rms-report/pack-sale`。确认标题、统计方式和营业日期控件，按当前可见控件操作。
3. **统计方式**选「套餐明细」。在「营业日期」的两个日期控件中选择同一个营业日，分别核对起止值。打开门店树，选用户要求的门店并核对实际勾选项；勾选「按门店统计」。在「更多筛选」中勾选「显示菜品规格」，取消「同名菜品合并统计」。菜品分类、菜品名称、订单分类、菜品下单来源均选「全部」，以取得可入库的完整门店日来源。
4. 每次修改日期或筛选后，点「查询」，等待结果刷新并复核当前条件。只有当前查询明确无数据时才将该日标为无数据。表格当前页条数不能代表全量。页面若提示额外限制，保留已确认范围并报告该限制。
5. 按 {MANUAL} 第 6 节选定适用的触发方式，再提交一次「导出」。页面转入「下载清单记录」时，
   按本次套餐报表、营业日和申请时间定位任务。等该行生成完成后再触发下载并校验原件。
   已有进行中的导出或下载时继续观察。

"""

TAKEOUT_SECTION = f"""## 打开报表（browser-skill 特化）

按 {MANUAL} 第 4 节启动 `bsk` 会话并打开
`https://pos.meituan.com/web/operation/main#/`（复用本次 Agent Window 中的标签）。登录与验证码由员工
在页面完成，不迁移 Cookie。daemon 不可用时由 agent 自行拉起，不切换到其他浏览器通道。

1. 打开 **报表中心 → 平台外卖订单明细**，以标题及门店、订单来源、外卖订单号、收银订单号等列确认报表。导航不可用时，在同一会话尝试录制观察到的直达页 `https://pos.meituan.com/web/report/orderListWM#/rms-report/orderListWM`，随后核对标题。不要混用店内或全渠道订单明细。
2. 先按“长范围优先按月导出”规划当前段，再按“本次输入”设置日期口径、该段起止范围、门店、订单集合、状态及其他筛选。历史月份按当前和目标年月定位，不重放录制中的点击次数。菜单切换、重置及导航后重新读取最终筛选。
3. **每次修改搜索参数或订单集合标签后，都先点“查询”，等待刷新完成并核对，再点“导出”**。查询后又改任何参数，必须重新查询。记录实际生效条件和可见总条数（如提供）；一页行数不是总数。零结果如实报告，不创建假数据。

"""

WORKFLOW_BROWSER_REF = f"""# 浏览器选择与恢复（browser-skill 特化）

WorkBuddy 使用宿主 `browser-skill` 的 `bsk` CLI，完整指引见 {MANUAL}。

1. 使用 `bsk doctor` 确认 CLI、daemon 和扩展连接，就绪后在 Agent Window 核对美团登录态。
   daemon 离线时可通过宿主后台任务启动，登录过期时由员工处理。
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

本副本使用 **BrowserSkill**。下文及本 Skill 的 references 中，凡涉及浏览器选择、
登录态、下载等待、宿主工具或定时任务的段落，
若与本节冲突，一律以本节、{MANUAL} 和 `workbuddy/HOST_MAP.md` 为准；
业务筛选、原件校验、证据与清理门槛保持不变。

- 浏览器：使用 `bsk` CLI 和 Chrome 扩展的 Agent Window，每轮确认 daemon、扩展连接和美团登录态。
- 下载：按 {MANUAL} 第 6 节先选定触发方式。美团「自助营业取数」iframe 使用
  `evaluate --expect` 与 Chrome 临时文件落地。支持几何点击的直接下载可用
  `bsk download --out` 一步完成点击和捕获。每个动作只触发一次。
- 只用 CLI 真实存在的子命令（见手册第 3 节）；不要用 `bsk open` / `--url` / `--expression`。
- 定时与续轮：无 Goal 生命周期，用 `workbuddy/scripts/wb_state.py` 的本地 run 状态文件；
  时间表由员工确认后才通过宿主 `automation_update` 安装。定时触发时若 daemon/扩展不可用，
  来源阶段记为 blocked、整轮 partial。
- 邮件：宿主邮件身份与中央冻结的 `allowedSender` 不一致，且缺原生读回能力，按官方降级
  记为 blocked + 本地交付，见 `workbuddy/scripts/wb_mail.py`；不换发件人、不发信。
- 中央动作仍只通过原生 `mcp__smedc__*` 工具完成；不另写 HTTP、JSON-RPC 或私有客户端。
- **全新用户**：先读 `workbuddy/GETTING_STARTED.md`（含 `bsk` CLI、Chrome 扩展、
  配对与美团登录的完整步骤），并运行 `python3 workbuddy/scripts/preflight.py`
  探测当前环境还缺哪些依赖与配置；它只读、不安装，会给出逐项修复命令。
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
  企业智脑（SMEDC）在 WorkBuddy 的工作流入口。分别运行每日美团入库、评价处理和自然周经营周报，
  复用官方核心与业务技能。
---

<!-- WorkBuddy overlay (browser-skill profile). Generated by workbuddy/bsk/build.py. -->

# 企业智脑工作流（WorkBuddy · browser-skill profile）

1. 按 `workbuddy/GETTING_STARTED.md` 完成上手，并运行 `python3 workbuddy/scripts/preflight.py`。
2. 读取 `workbuddy/HOST_MAP.md`、`workbuddy/WORKFLOWS.md` 与
   `workbuddy/references/browser-skill.md`，确认所选工作流与浏览器步骤。
3. 中央配置、身份、指定安装、claim/check/record 全部通过原生 `mcp__smedc__*` 工具读取和提交；
   不自建 HTTP、JSON-RPC 或调度客户端。
4. 定时运行：宿主 `automation_update` 只创建 PAUSED 任务，确切时间表必须员工确认；
   未结束轮用 `workbuddy/scripts/wb_state.py` 的本地状态文件续接，不另开第二轮。
   每轮先确认 `bsk` daemon 与扩展连接；不可用时来源阶段如实记为 blocked、整轮 partial。
5. 在 `bsk` CLI 的 Agent Window 采集来源。每次按 `workbuddy/references/browser-skill.md` 第 6 节
   先选定触发方式再执行。美团「自助营业取数」iframe 使用 `evaluate --expect` 和 Chrome 临时文件
   校验落地，不借用员工标签页、不改扩展 Automation 设置。
6. 邮件阶段按官方降级：`workbuddy/scripts/wb_mail.py plan` 记录 blocked 并本地交付，不发信。
7. 安装本身不启用任务、不授予发布或发信权限；评价发布仍须中央现行持续授权内的门店与稿件批准。

正常完成只留简短结果；需要人工处理时指出精确缺项。
"""

# Shipped into every skill so the generated references work outside a checkout.
ADAPTER_FILES = {
    "README.md": WORKBUDDY / "README.md",
    "GETTING_STARTED.md": WORKBUDDY / "GETTING_STARTED.md",
    "HOST_MAP.md": WORKBUDDY / "HOST_MAP.md",
    "WORKFLOWS.md": WORKBUDDY / "WORKFLOWS.md",
    "INSTALL.md": WORKBUDDY / "INSTALL.md",
    "references/browser-skill.md": WORKBUDDY / "references/browser-skill.md",
    "scripts/meituan-iframe-export.js": WORKBUDDY / "scripts/meituan-iframe-export.js",
    "scripts/preflight.py": WORKBUDDY / "scripts/preflight.py",
    "scripts/wb_state.py": WORKBUDDY / "scripts/wb_state.py",
    "scripts/wb_schedule.py": WORKBUDDY / "scripts/wb_schedule.py",
    "scripts/wb_mail.py": WORKBUDDY / "scripts/wb_mail.py",
    "scripts/wb_browser.py": WORKBUDDY / "scripts/wb_browser.py",
}
SKIP_PARTS = {"__pycache__", ".DS_Store", ".pytest_cache"}

# Whole-sentence replacements that must run before the generic word fixes.
# They rewrite the download/save-panel advice for bsk's native `--out` capture.
REPLACEMENTS = (
    ("确认结果对应目标日期和方案，再点 `导出`。",
     "确认结果对应目标日期和方案，按下节的 iframe 方案执行一次 `导出`。"),
    ("确认页面结果是目标日期和方案，再点 `导出`。",
     "确认页面结果是目标日期和方案，按下节选定触发方式后执行一次 `导出`。"),
    ("结果与最后一次查询条件一致后，先按下节准备下载捕获，再点 **导出** 一次。",
     "核对最后一次查询条件，按下节选定触发方式并提交 **导出** 一次。"),
    ("按“浏览器选择”规则选定浏览器，用当前智能体的浏览器工具查找其中的 `美团管家` 标签；有则复用，没有则在同一浏览器打开",
     "用 `bsk` 在本轮 Agent Window 内打开"),
    ("用当前工具文档支持的浏览器能力处理弹出页；内置浏览器缺少所需能力时，按主技能说明原因后复用可用的登录会话，不迁移凭据。",
     "在同一 Agent Window 内处理弹出页和下载清单，保留已经确认的来源登录态。"),
    ("先准备下载捕获，再点该行 **下载**。", "按下节对该行 **下载** 控件执行一次。"),
    ("在对应行显示 `导出完成` 后点该行的 `下载`",
     "在对应行显示 `导出完成` 后按下节对该行的 `下载` 控件执行一次"),

    ("取得本次请求范围内的原始 `.xlsx`，完成本地保存与只读验证。使用 **Computer Use** 操作浏览器及必要的原生保存窗口；当前环境若有明确覆盖此报表的专用工具，优先使用其等价查询、导出和保存能力。读取当前工具文档后再调用，以下接口名只适用于提供相应能力的环境。",
     "取得本次请求范围内的原始 `.xlsx`，完成本地落地与只读验证。浏览器操作使用宿主 `browser-skill` 的 `bsk` CLI，下载落地见 `workbuddy/references/browser-skill.md` 第 6 节。"),
    ("取得指定日期口径、时间范围、门店及订单状态的原始 `.xlsx`，完成本地保存并验证。使用 Computer Use（浏览器及必要的原生窗口操作）完成美团界面流程；若当前环境有覆盖此报表的专用工具，优先使用等价的查询、导出和保存能力。",
     "取得指定日期口径、时间范围、门店及订单状态的原始 `.xlsx`，完成本地落地并验证。浏览器操作使用宿主 `browser-skill` 的 `bsk` CLI，下载落地见 `workbuddy/references/browser-skill.md` 第 6 节。"),
    ("需要浏览器读取/操作、公开信息检索及本地 XLSX 生成/检查能力。先读当前工具文档，使用运行环境实际支持的接口；Codex 的 `cua_repl`、`tab.playwright`、`iab` 只是示例，不假定其他智能体具备它们。",
     "需要浏览器读取/操作及本地 XLSX 生成/检查能力。在 WorkBuddy 中浏览器操作使用 `bsk` CLI，见 `workbuddy/references/browser-skill.md`；本地文件检查使用命令行与 Python 标准库。"),
    ("导出可能很快完成并直接打开系统保存对话框", "导出可能很快完成并直接触发下载"),
    ("若直接出现保存对话框，就选择目标目录，按实际日期命名，保留 `.xlsx` 后保存。",
     "若直接触发下载，等待本次文件并按浏览器手册第 6 节落地、验证，保留 `.xlsx`。"),
    ("5. 若直接出现保存对话框，进入下一步。", "5. 若直接触发下载，进入下一步。"),
    ("6. 在保存对话框选择目标目录，按实际日期命名并保留 `.xlsx` 后保存。",
     "6. 校验本次下载并落地到目标目录，按实际日期命名并保留 `.xlsx`。"),
    ("4. 等待生成并检查原生保存窗口。演示中的首批生成约需 40 秒；短暂没有窗口不等于失败。分段检查生成状态和保存窗口，不反复点击导出。",
     "4. 有界等待生成，用 `bsk snapshot` / `bsk observe` 分段检查导出状态。演示中的首批生成约需 40 秒；短暂没有下载结果不等于失败，不反复点击导出。"),
    ("按“下载捕获、系统保存框与恢复”先准备捕获，再点 **导出** 一次。",
     "按浏览器手册第 6 节选定触发方式后提交 **导出** 一次。"),
    ("6. 可能直接出现保存框或下载文件，也可能提示 **前往下载清单**。直接下载进入保存与验证；",
     "6. 可能直接触发下载，也可能提示 **前往下载清单**。直接下载等待本次文件并校验落地；"),
    ("**导出完成**后按“下载捕获、系统保存框与恢复”准备捕获，再点该行 **下载**。",
     "**导出完成**后按浏览器手册第 6 节对该行 **下载** 控件只执行一次。"),
    ("2. 直接出现保存框或下载事件时，进入“下载捕获与保存”。",
     "2. 直接触发下载时，等待本次文件并按浏览器手册第 6 节校验落地。"),
    ("确认该任务显示“下载成功”后点该行“下载”，捕获下载结果或系统保存窗口。下载事件超时不代表没有保存窗口：先检查原生保存框及实际文件，再决定恢复；不能因超时连续点击下载。",
     "确认该任务显示“下载成功”后，按浏览器手册第 6 节对该行“下载”控件只执行一次。超时先核对页面和实际文件；`effect_state: unknown` 时保留待续。"),
    ("排除 `.crdownload`、HTML 错误页或只有保存框却未保存的情况",
     "排除 `.crdownload`、HTML 错误页或只有临时文件却未落地的情况"),
    ("排除 `.crdownload`、HTML 错误页及只出现保存框的情况",
     "排除 `.crdownload`、HTML 错误页及只出现临时文件的情况"),
    ("下载事件返回和保存框单独都不能作为本地下载成功的依据。",
     "临时文件出现和导出任务状态都不能单独作为本地下载成功的依据。"),
    ("下载事件或保存框单独都不能作为本地下载成功依据。",
     "临时文件出现和导出任务状态都不能单独作为本地下载成功依据。"),
    ("在 Codex 内置浏览器中", "在 WorkBuddy 的 Agent Window 中"),
    ("Codex 内置浏览器", "Agent Window"),
    ("处理直接下载、异步下载清单与系统保存框", "处理直接下载、异步下载清单与下载落地"),
    ("处理异步下载清单及系统保存框", "处理异步下载清单与下载落地"),
    ("使用 **Computer Use** 操作浏览器及必要的原生保存窗口",
     "使用宿主 `browser-skill` 操作浏览器及下载落地"),
    ("先按当前工具文档注册下载等待，再点击",
     "按浏览器手册第 6 节选定触发方式并执行一次"),
    ("按当前工具文档先注册下载等待，再点击",
     "按浏览器手册第 6 节选定触发方式并执行一次"),
    ("先准备下载捕获，再点击",
     "按浏览器手册第 6 节选定触发方式并执行一次"),
    ("再点该行的 `下载` 并保存",
     "按浏览器手册第 6 节对该行的 `下载` 控件执行一次并校验文件"),
    ("再点该行 `下载` 并保存",
     "按浏览器手册第 6 节对该行 `下载` 控件执行一次并校验文件"),
    ("系统「保存」对话框", "下载临时文件"),
    ("系统保存对话框", "下载临时文件"),
    ("系统保存窗口", "下载临时文件"),
    ("原生保存窗口", "下载临时文件"),
    ("系统保存框", "下载临时文件"),
    ("保存对话框", "下载临时文件"),
    ("保存窗口", "下载临时文件"),
    ("保存框", "下载临时文件"),
    ("下载事件返回", "临时文件出现"),
    ("下载事件", "下载"),
    ("45 秒事件等待和 60 秒外层时限", "原宿主的历史等待时限"),
    ("45 秒下载等待与恢复规则", "原宿主的下载等待与恢复规则"),
    ("cua.createBrowserTab", "原宿主建标签接口（本宿主不适用）"),
    ('cua.getApp("Google Chrome")', "原宿主窗口工具（本宿主不适用）"),
    ("cua.getApp", "原宿主窗口工具（本宿主不适用）"),
    ("tab.playwright", "原宿主浏览器工具（本宿主不适用）"),
    ("cua_repl.js", "原宿主脚本环境（本宿主不适用）"),
    ("cua_repl", "原宿主浏览器工具（本宿主不适用）"),
    ("Computer Use", "原宿主 GUI 自动化（本宿主不适用）"),
    ("内置 Chromium 浏览器", "原宿主浏览器（本宿主不适用）"),
    ("内置浏览器", "原宿主浏览器（本宿主不适用）"),
    ("load_workspace_dependencies", "本地运行环境探测"),
    ("mcp__codex_app__automation_update", "宿主 automation_update"),
    ("mcp__codex_app__list_projects", "宿主工作目录列表"),
    ("mcp__codex_app__set_thread_archived", "聊天归档工具（本宿主不可用）"),
    ("mcp__codex_apps__gmail_send_email", "原生邮件工具（本宿主不可用）"),
    ("mcp__codex_apps__gmail_read_email_thread", "原生邮件读回工具（本宿主不可用）"),
    ("mcp__codex_apps__gmail_search_email_ids", "原生已发送查询（本宿主不可用）"),
    ("mcp__codex_apps__gmail_get_profile", "原生邮件身份工具（本宿主不可用）"),
    ("gmail_send_email", "原生邮件工具（本宿主不可用）"),
    ("gmail_read_email_thread", "原生邮件读回工具（本宿主不可用）"),
    ("gmail_search_email_ids", "原生已发送查询（本宿主不可用）"),
    ("gmail_get_profile", "原生邮件身份工具（本宿主不可用）"),
    ("read_email_thread", "原生邮件读回（本宿主不可用）"),
    ("read_attachment", "原生附件读取（本宿主不可用）"),
    ("send_email", "原生发信（本宿主不可用）"),
    ("functions.exec", "宿主命令执行"),
    ("get_goal", "Goal 读取（本宿主不可用）"),
    ("create_goal", "Goal 创建（本宿主不可用）"),
    ("update_goal", "Goal 更新（本宿主不可用）"),
    ("automation.toml", "宿主定时任务定义"),
    ("set_thread_archived", "聊天归档工具（本宿主不可用）"),
    ("tab.markHandoff()", "标签交接能力（本宿主不可用）"),
    ("artifact-tool", "本地工作簿依赖"),
    ("Gmail", "原生邮件"),
    ("Codex", "原宿主"),
    ("IAB", "原宿主浏览器（本宿主不适用）"),
)

SECTION_REPLACEMENTS = {
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
FULL_FILE_REPLACEMENTS = {
    "smedc-workflows/browser.md": WORKFLOW_BROWSER_REF,
    "smedc-workflows/gmail.md": HOST_REF_NOTE,
    "smedc-workflows/installation.md": HOST_REF_NOTE,
    "smedc-workflows/invocation.md": HOST_REF_NOTE,
    "smedc-workflows/runtime.md": HOST_REF_NOTE,
    "reply-meituan-reviews/browser-recovery.md": HOST_REF_NOTE,
    "reply-meituan-reviews/email-notifications.md": HOST_REF_NOTE,
}

def source_names() -> list[str]:
    return sorted(p.parent.name for p in SKILLS.glob("*/SKILL.md"))


def has_host_marker(text: str) -> bool:
    return any(marker in text for marker in HOST_MARKERS)


def has_replaced_section(text: str) -> bool:
    return any(f"## {heading}" in text for heading in SECTION_REPLACEMENTS)


def replace_sections(text: str) -> tuple[str, dict[str, str]]:
    """Replace whole level-1/2 sections, shielding inserted WorkBuddy text.

    Inserted sections are returned as placeholder tokens so that narrow wording
    replacements apply only to surviving upstream text, never to the new
    WorkBuddy chapters (which are already written in final form).
    """
    lines = text.splitlines(keepends=True)
    out: list[str] = []
    blocks: dict[str, str] = {}
    i = 0
    while i < len(lines):
        match = re.match(r"^#{1,2} (.+?)\s*$", lines[i].rstrip("\n"))
        replacement = SECTION_REPLACEMENTS.get(match.group(1)) if match else None
        if replacement is None:
            out.append(lines[i])
            i += 1
            continue
        token = f"\x00WBSEC{len(blocks)}\x00"
        blocks[token] = replacement
        out.append(token + "\n")
        i += 1
        while i < len(lines) and not re.match(r"^#{1,2} ", lines[i]):
            i += 1
    return "".join(out), blocks


def adapt_text(text: str, *, sections: bool = False) -> str:
    blocks: dict[str, str] = {}
    if sections:
        text, blocks = replace_sections(text)
    adapted = text
    for old, new in REPLACEMENTS:
        adapted = adapted.replace(old, new)
    # Standalone lowercase "iab" after the longer phrases are handled.
    adapted = re.sub(r"(?<![A-Za-z])iab(?![A-Za-z])",
                     "原宿主浏览器（本宿主不适用）", adapted)
    for token, block in blocks.items():
        adapted = adapted.replace(token, block)
    return adapted


def adapt_skill_md(name: str, source: str) -> str:
    adapted = adapt_text(source, sections=True)
    banner = BANNER.replace("<name>", name)
    match = re.match(r"(?s)(\A---\n.*?\n---\n)(.*)", adapted)
    if match:
        # YAML frontmatter must stay the very first line of the file.
        frontmatter = re.sub(r"(?<!（)\bSMEDC\b(?!）)", "企业智脑（SMEDC）", match.group(1))
        return frontmatter + "\n" + banner + HOST_NOTE + match.group(2)
    return banner + HOST_NOTE + adapted


def generate() -> dict[str, dict[str, str]]:
    result: dict[str, dict[str, str]] = {}
    for name in source_names():
        skill_dir = SKILLS / name
        files: dict[str, str] = {}
        skill_text = (skill_dir / "SKILL.md").read_text(encoding="utf-8")
        if name == "smedc-workflows":
            files["SKILL.md"] = WORKFLOWS_SKILL
        elif has_host_marker(skill_text) or has_replaced_section(skill_text):
            files["SKILL.md"] = adapt_skill_md(name, skill_text)

        ref_dir = skill_dir / "references"
        if ref_dir.is_dir():
            for ref in sorted(ref_dir.glob("*.md")):
                key = f"{name}/{ref.name}"
                if key in FULL_FILE_REPLACEMENTS:
                    files[f"references/{ref.name}"] = FULL_FILE_REPLACEMENTS[key]
                    continue
                text = ref.read_text(encoding="utf-8")
                if has_host_marker(text):
                    files[f"references/{ref.name}"] = REFERENCE_NOTE + adapt_text(text)
        if files:
            result[name] = {rel: text.rstrip() + "\n" for rel, text in files.items()}
    return result


def residual_tokens(overlays: dict[str, dict[str, str]]) -> list[str]:
    problems = []
    for name, files in overlays.items():
        for rel, text in files.items():
            for pattern in FORBIDDEN_PATTERNS:
                if re.search(pattern, text):
                    problems.append(f"{name}/{rel}: {pattern}")
    return problems


def committed_files() -> dict[tuple[str, str], str]:
    result: dict[tuple[str, str], str] = {}
    for path in OUT.rglob("*.md"):
        rel = path.relative_to(OUT)
        if len(rel.parts) >= 2:
            result[(rel.parts[0], "/".join(rel.parts[1:]))] = path.read_text(encoding="utf-8")
    return result


def cmd_build(_: argparse.Namespace) -> int:
    overlays = generate()
    problems = residual_tokens(overlays)
    if problems:
        print("generated overlays still contain host-specific tokens:\n"
              + "\n".join(problems), file=sys.stderr)
        return 1
    if OUT.exists():
        shutil.rmtree(OUT)
    OUT.mkdir(parents=True)
    for name, files in overlays.items():
        for rel, text in files.items():
            target = OUT / name / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(text, encoding="utf-8")
    total = sum(len(files) for files in overlays.values())
    print(f"generated {len(overlays)} skills / {total} overlay files: "
          f"{', '.join(sorted(overlays))}")
    return 0


def cmd_check(_: argparse.Namespace) -> int:
    overlays = generate()
    expected = {(name, rel): text
                for name, files in overlays.items() for rel, text in files.items()}
    committed = committed_files()
    problems = []
    for key in sorted(set(expected) | set(committed)):
        label = f"{key[0]}/{key[1]}"
        if key not in committed:
            problems.append(f"missing overlay: {label}")
        elif key not in expected:
            problems.append(f"stale overlay: {label}")
        elif expected[key] != committed[key]:
            problems.append(f"out of date overlay: {label}")
        else:
            for pattern in FORBIDDEN_PATTERNS:
                if re.search(pattern, committed[key]):
                    problems.append(f"host-specific token {pattern!r} remains in {label}")
    if problems:
        print("\n".join(problems), file=sys.stderr)
        return 1
    print(f"ok: {len(overlays)} skills / {len(expected)} overlay files match the Codex sources")
    return 0


class InstallFile(NamedTuple):
    contents: bytes
    mode: int = 0o644


def installation_files() -> dict[Path, InstallFile]:
    """Resolve the final bytes once for both install and verify."""
    files = {}
    overlays = generate()
    problems = residual_tokens(overlays)
    if problems:
        raise ValueError("generated overlays contain unsupported instructions:\n" + "\n".join(problems))

    for name, overlay in overlays.items():
        source = SKILLS / name
        skill_files = {
            path.relative_to(source): InstallFile(path.read_bytes(), stat.S_IMODE(path.stat().st_mode) & 0o777)
            for path in source.rglob("*")
            if path.is_file() and path.suffix != ".pyc"
            and not SKIP_PARTS.intersection(path.relative_to(source).parts)
        }
        skill_files.update({Path(rel): InstallFile(text.encode("utf-8")) for rel, text in overlay.items()})
        skill_files.update({
            Path("workbuddy") / rel: InstallFile(path.read_bytes()) for rel, path in ADAPTER_FILES.items()
        })
        receipt = {
            "skills": sorted(overlays),
            "files": {
                rel.as_posix(): hashlib.sha256(file.contents).hexdigest()
                for rel, file in sorted(skill_files.items())
            },
        }
        skill_files[Path("workbuddy/install-manifest.json")] = InstallFile(
            (json.dumps(receipt, indent=2, sort_keys=True) + "\n").encode("utf-8")
        )
        files.update({Path(name) / rel: data for rel, data in skill_files.items()})
    return files


def destination_root(raw: str) -> Path:
    supplied = Path(raw).expanduser().absolute()
    root = supplied.resolve()
    home = Path.home().resolve()
    protected = (ROOT, home / ".agents" / "skills", home / ".codex" / "skills")
    if (supplied.is_symlink() or root == home or root in home.parents
            or any(root.is_relative_to(path.resolve()) for path in protected)
            or any(root.parts[index:index + 2] in ((".agents", "skills"), (".codex", "skills"))
                   for index in range(len(root.parts) - 1))):
        raise ValueError(f"refusing to use a repository, home, or Codex path as a WorkBuddy root: {supplied}")
    return root


def validate_destination(root: Path, relative: Path) -> Path:
    path = root
    if path.resolve() != path or (path.exists() and not path.is_dir()):
        raise ValueError(f"expected a real directory: {path}")
    for part in relative.parts[:-1]:
        path = path / part
        if path.is_symlink() or (path.exists() and not path.is_dir()):
            raise ValueError(f"expected a real directory: {path}")
    target = root / relative
    if target.is_symlink() or (target.exists() and not target.is_file()):
        raise ValueError(f"expected a regular file: {target}")
    return target


def cmd_install(args: argparse.Namespace) -> int:
    root = destination_root(args.root)
    files = installation_files()
    for relative in files:
        validate_destination(root, relative)
    # Write the discovery entry point last so it never advertises an overlay
    # before the support files are in place.
    for relative in sorted(files, key=lambda path: path.name == "SKILL.md"):
        target = validate_destination(root, relative)
        target.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(dir=target.parent, delete=False) as pending:
            staged = Path(pending.name)
            try:
                pending.write(files[relative].contents)
                pending.close()
                staged.chmod(files[relative].mode)
                os.replace(staged, target)
            finally:
                staged.unlink(missing_ok=True)
    print(f"ok: {len({path.parts[0] for path in files})} WorkBuddy skills installed under {root}")
    return 0


def cmd_verify(args: argparse.Namespace) -> int:
    root = destination_root(args.root)
    problems = []
    files = installation_files()
    for relative, file in sorted(files.items()):
        try:
            target = validate_destination(root, relative)
            if not target.is_file():
                problems.append(f"missing: {relative}")
            elif target.read_bytes() != file.contents:
                problems.append(f"out of date or modified: {relative}")
            elif os.name != "nt" and (target.stat().st_mode & 0o111) != (file.mode & 0o111):
                problems.append(f"unexpected executable mode: {relative}")
        except (OSError, ValueError) as exc:
            problems.append(str(exc))
    if problems:
        print("\n".join(problems), file=sys.stderr)
        return 1
    print(f"ok: {len(files)} installed WorkBuddy files match the repository")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    for name, command in (("build", cmd_build), ("check", cmd_check),
                          ("install", cmd_install), ("verify", cmd_verify)):
        entry = sub.add_parser(name)
        if name in {"install", "verify"}:
            entry.add_argument("--root", default="~/.workbuddy/skills")
        entry.set_defaults(command_handler=command)
    args = parser.parse_args(argv)
    try:
        return args.command_handler(args)
    except (OSError, ValueError) as exc:
        print(exc, file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
