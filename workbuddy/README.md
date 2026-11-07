# WorkBuddy host adapter (additive)

This directory adds a WorkBuddy host path for the companion skills. **Nothing
under `skills/` is modified.** The Codex host keeps reading the exact same
files, prompts, scripts and tests as before; WorkBuddy installs a second copy
with generated SKILL.md overlays.

The adapter is tenant-neutral: it contains no enterprise names, store rosters,
source accounts, recipient addresses, publication whitelists or schedules.
Those values are read at run time from the authenticated central snapshot.

## What is preserved

- The full central coordination protocol (`mcp__smedc__*`): identity, frozen
  configuration, assignment, claim/check/record, action readback and
  provider receipts. The launcher binding and approved pin remain owned by the
  core skill; this adapter never installs or pins a launcher.
- The three workflow definitions, their stage order, evidence requirements,
  dedup identities and cleanup gates.
- The original business skills: browser exports, original-file validation,
  uploads, review workbook, publication gates and report generation.

## What is different (and why)

| Codex capability | WorkBuddy path |
| --- | --- |
| Persistent Goal (`get_goal`/`create_goal`/`update_goal`) | `scripts/wb_state.py` local run-state file with hash-chained atomic saves |
| `functions.exec` + JS `eval` with an injected `tools` object | Agent invokes native tools step by step; only the local state/index is scripted |
| Native Gmail namespace and `allowedSender` identity | **Not substitutable.** Mail stage is `blocked`; local delivery per `scripts/wb_mail.py` |
| `mcp__codex_app__automation_update` (projectId, notificationPolicy, model) | Host `automation_update` with name/prompt/schedule/status/cwds; `scripts/wb_schedule.py` renders specs only |
| IAB / in-app browser | `bsk` CLI + Chrome BrowserSkill extension, reusing the local Chrome login (`scripts/wb_browser.py`) |
| `load_workspace_dependencies`, `@oai/artifact-tool` | Local interpreter/package probes and the skill's own requirements |
| `set_thread_archived`, `tab.markHandoff()` | Not available; chat archiving is skipped and browser tabs are reopened per run |

See `HOST_MAP.md` for the full mapping and the list of hard limits.

## Files

- `INSTALL.md` — how to install the overlays without touching Codex.
- `HOST_MAP.md` — capability mapping and hard limits.
- `WORKFLOWS.md` — the three runbooks on this host.
- `scripts/wb_state.py` — local run state machine (pure standard library).
- `scripts/wb_browser.py` — bsk bridge (structured JSON, no credential handling).
- `scripts/wb_mail.py` — mail-stage degradation and local delivery. Never sends.
- `scripts/wb_schedule.py` — renders PAUSED automation specs; never creates a task.
- `overlays/build_overlays.py` — regenerates and checks the WorkBuddy SKILL.md overlays.
- `overlays/generated/` — committed overlay files for review.

## Non-goals

- No SMTP, no second mail server, no sender override.
- No HTTP/JSON-RPC/private MCP client: central actions go through native tools only.
- No automatic schedule creation. A schedule is installed only after the
  employee confirms an exact time, or is copied verbatim from a host readback
  during an approved migration.
- No changes to the service, central configuration, or the Codex automation files.
