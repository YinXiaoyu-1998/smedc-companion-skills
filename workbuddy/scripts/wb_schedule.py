#!/usr/bin/env python3
"""WorkBuddy schedule specification generator.

Codex installs one native local-cron task per workflow through
``mcp__codex_app__automation_update`` with a projectId, notificationPolicy,
model and reasoningEffort. WorkBuddy exposes ``automation_update`` with a
smaller field set (name/prompt/schedule/status/cwds) and a ``view`` readback.

This module only RENDERS the specification. It never creates a task and
never writes a host automation file. A schedule is installed only after the
employee confirms an exact time; for a migration the RRULE must be read back
from the existing host and preserved verbatim.
"""

from __future__ import annotations

import argparse
import json
import sys

WORKFLOWS = (
    "meituan-daily-ingestion",
    "meituan-review-operations",
    "weekly-business-report",
)

HOST_LIMITATIONS = [
    "no Goal lifecycle; continuation uses workbuddy/scripts/wb_state.py",
    "no projectId; cwds carries the dedicated workspace",
    "no notificationPolicy field; failed-run-only is expressed inside the prompt",
    "no model/reasoningEffort fields; the host's current model is used",
    "no set_thread_archived equivalent; chat archiving is skipped",
]


def prompt_for(workflow: str, workspace: str) -> str:
    return (
        "按 workbuddy/WORKFLOWS.md 的定时运行入口，续接并完成本轮 SMEDC 工作流。\n"
        f"workflowType={workflow}\n"
        f"workspaceRoot={workspace}\n"
        "runRoot=<workspaceRoot>/runs/<central-runId>，wb_state.py 的 --root 使用此目录。\n"
        "先用 workbuddy/scripts/wb_state.py resume 读取未结束轮，同一 runId 续轮；"
        "只有中央状态确认无未完成轮时才 wb_state.py init 新轮。\n"
        "每轮从中央读取当前身份、配置、指定安装与权限；"
        "中央 claim/check/record 等动作只通过原生 mcp__smedc__* 工具完成，"
        "不自行写 HTTP、JSON-RPC 或私有调度客户端。\n"
        "运行前确认本轮宿主会话确实暴露了 mcp__smedc__* 工具；拿不到则如实报阻塞，不空跑。\n"
        "浏览器来源读取用 workbuddy/scripts/wb_browser.py（bsk + 本机 Chrome 登录态），"
        "交互前必须先 sync --policy target。\n"
        "邮件阶段按官方降级处理：wb_mail.py plan 记录 blocked 并本地交付，不换发件人。\n"
        "仅在失败或需要人工处理时给出简短结果；完成后 wb_state.py close 并读回。\n"
        "不得安装/更新 skill、不得扩大门店或收件人范围、不得重放 unknown 动作。"
    )


def spec_for(workflow: str, workspace: str) -> dict:
    return {
        "workflowType": workflow,
        "status": "PAUSED",
        "scheduleType": "recurring",
        "rrule": None,
        "rruleSource": "explicit employee confirmation, or verbatim host readback on migration",
        "cwds": [workspace],
        "name": f"SMEDC {workflow}",
        "prompt": prompt_for(workflow, workspace),
        "requiresUserConfirmation": True,
        "requiredTools": ["mcp__smedc__*"],
        "toolBinding": (
            "Host-provided. Verify the automation runtime exposes the smedc MCP "
            "tools before creating the task. connectorIds is only needed when the "
            "host requires an explicit connector binding; a custom MCP server entry "
            "may be inherited from the session."
        ),
        "notificationPolicyNote": (
            "informational only, not a host field; failed-run-only is expressed in the prompt"
        ),
        "hostLimitations": HOST_LIMITATIONS,
    }


def cmd_specs(args: argparse.Namespace) -> int:
    print(json.dumps({
        "ok": True,
        "created": False,
        "note": "Specifications only. Never create a guessed schedule.",
        "workflows": [spec_for(w, args.workspace) for w in WORKFLOWS],
    }, ensure_ascii=False, indent=2))
    return 0


def cmd_prompt(args: argparse.Namespace) -> int:
    if args.workflow not in WORKFLOWS:
        raise ValueError(f"unknown workflow: {args.workflow}")
    print(prompt_for(args.workflow, args.workspace))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", required=True)
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("specs")
    p.set_defaults(func=cmd_specs)
    p = sub.add_parser("prompt")
    p.add_argument("--workflow", required=True)
    p.set_defaults(func=cmd_prompt)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except ValueError as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
