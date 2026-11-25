# Capability mapping and hard limits

This is the auditable mapping behind the adapter. "Equivalent" means the same
business result through a different host mechanism; "degraded" means the result
is weaker and must be recorded as such; "not substitutable" means no honest
WorkBuddy equivalent exists and the stage must be reported as blocked.

## Host-native prerequisites (not limitations)

Browser work on this host goes through the **host's own `web-access` skill**
(CDP Proxy at `localhost:3456`, attached to the employee's everyday Chrome/Edge).
Its pre-flight configuration — `scripts/check-deps.mjs`, Node.js 22+, the browser
remote-debugging authorization, the `--browser` preference and the connection
approval — is required by that skill itself for *any* WorkBuddy web task. It is
not an extra step introduced by this adapter. See `workbuddy/references/web-access.md` §1–2
and `INSTALL.md` §3 for the exact employee steps.

**But this pre-flight is not one-time.** Only `WEB_ACCESS_BROWSER` in `config.env`
persists. Chrome >=144 asks for permission *every time* a remote debugging
session is requested, and its own docs require allowing it again at the start of
every new browser session; Chrome must also stay running. Doing the setup today
does not guarantee an automated download days later. Chrome's anti-abuse design,
not an adapter defect — see the [Chrome DevTools MCP blog](https://developer.chrome.com/blog/chrome-devtools-mcp-debug-your-browser-session)
and [Chrome for Developers (zh-CN)](https://developer.chrome.google.cn/docs/extensions/ai/build-with-ai).
Consequence: an unattended scheduled trigger cannot be relied on for source
collection; when authorisation is absent, record the stage `blocked` and close
`partial`. Do not disable the safety prompt, retry in a loop, or switch to a
private client.

Conversely, this adapter installs **no non-native browser component**: no `bsk`
CLI, no Chrome BrowserSkill extension, no second browser channel. Earlier
adapter revisions bound the browser path to `bsk`; that path has been removed
because it required the employee to install and configure extra software that
WorkBuddy does not ship.

## Fully equivalent

| Capability | WorkBuddy mechanism |
| --- | --- |
| Central workflow tools | Native `mcp__smedc__*` tools: `query_enterprise_workflows` (list and detail), `get_workflow_status`, `manage_workflow_installation`, `manage_workflow_run`, `prepare_enterprise_workflow_change`, `save_enterprise_workflow`, `record_workflow_action` |
| Official binding | `entryName=smedc`, namespace `mcp__smedc__`, service origin owned by the core skill |
| Authenticated session | Core skill login; the launcher's secure store keeps the durable session |
| Local file writes, hashing, atomic replace | Standard-library scripts in `scripts/` invoked through Bash |
| Date/window computation (Beijing time, prior business day, natural week) | `TZ=Asia/Shanghai date` and Python `datetime` / `zoneinfo` |
| Original-file integrity checks | `zipfile`, `openpyxl`, `file` through Bash; see `web-access.md` §5 |
| DOM reads, iframe traversal, mouse-event clicks | CDP Proxy `/eval` and `/clickAt`; see `web-access.md` §3–4 |

## Equivalent with adaptation

| Codex mechanism | WorkBuddy mechanism | Residual difference |
| --- | --- | --- |
| IAB / in-app browser | `web-access` CDP Proxy attached to the employee's everyday browser, reusing its login | Chrome must be running and the employee must approve the remote-debugging prompt; approval is per connection / browser session, not one-time (above) |
| Download capture + native Save panel | Trigger the export inside the correct iframe with a full mouse-event sequence, then validate and rename the `.com.google.Chrome.*` temp file locally (`web-access.md` §5) | No download event API and no GUI Save panel; completion is proven by the validated local file, not by an event or a dialog |
| Native local cron + `automation.toml` readback | Host `automation_update` (`create`/`view`/`update`) with `cwds` | No projectId, model or reasoningEffort fields; no native TOML readback |
| Shell command execution (`exec_command`) | Local `Bash`/`subprocess` calls from the adapter scripts | Only the tool-object injection is impossible; see hard limit 3 |
| `load_workspace_dependencies` | Explicit local interpreter/package checks | Host-provided bundled library paths are unavailable |
| `@oai/artifact-tool` | The skill's own requirements and workbook builder | Must be installed in a dedicated venv, never globally |
| `tab.markHandoff()` | Reopen the verified entry in a new CDP tab | Tabs do not survive a conversation turn |
| `set_thread_archived` | Skipped | Chat archiving is optional and has no host equivalent |

### Local state integrity

`wb_state.py` writes `state.json` atomically (fsync + replace) and appends one
line per revision to `state.journal`. Each journal line records `revision`,
`stateHash` and `prevHash`; `load()` verifies the self-hash, the journal chain
and that the journal head still matches `state.json`. This makes "hash-chained"
literal: a rolled-back state file is rejected even though its own hash is valid.
It detects tampering and rollback, but it is still a local index, not a central
receipt.

## Not substitutable (hard limits)

1. **Native Gmail namespace plus `allowedSender` identity.** WorkBuddy does have
   an Agent Mail connector, but its sender alias is not the frozen central
   `allowedSender`, and the central `email` intent identity check would reject
   it. Byte-level `provider_readback` (`read_email_thread` / `in:sent`
   reconciliation, `read_attachment`) also has no equivalent. **Mail stages are
   blocked.** Weekly reports are delivered locally (the execution definition
   explicitly allows this), and review drafts remain in the frozen workbook.
   No SMTP, no sender override, no fabricated readback.
2. **Goal lifecycle.** `get_goal` / `create_goal` / `update_goal` do not exist.
   The upstream invocation guide says to record the execution mode as
   `unavailable` and not to create another scheduler. `wb_state.py` preserves
   run continuity locally, but this is a documented degradation, not a Goal.
3. **JS `tools` injection for `native-adapters.js`.** That adapter expects an
   evaluation environment where the host's tool objects are callable.
   WorkBuddy has no such environment, and the workflow forbids replacing it with
   a private HTTP/JSON-RPC client. Central actions are therefore performed by
   the agent step by step; `wb_state.py` records the verified results and intent
   identities.
4. **Native download-event API and window-level Save panel automation.** The CDP
   Proxy exposes `/eval`, `/click`, `/clickAt` and `/screenshot`, but no
   `waitForEvent("download")` and no OS Save-panel control. The generated
   overlays therefore replace those chapters entirely rather than mapping their
   identifiers; see `web-access.md` §5 for the supported path.

## Consequences that must be reported

- A completed run with a blocked mail stage is `partial`, never `succeeded`.
- A source stage whose CDP session is unavailable at trigger time is `blocked`
  with the exact pending scope; it is never silently replayed or backfilled.
- A run whose lease renewal could not be kept at the original cadence keeps
  the true outcome and the exact pending scope; it is not silently replayed.
- Installation never activates a tenant, never grants upload/publish/send
  rights and never changes the central configuration.
