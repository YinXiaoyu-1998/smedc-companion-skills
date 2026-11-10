# Capability mapping and hard limits

This is the auditable mapping behind the adapter. "Equivalent" means the same
business result through a different host mechanism; "degraded" means the result
is weaker and must be recorded as such; "not substitutable" means no honest
WorkBuddy equivalent exists and the stage must be reported as blocked.

## Fully equivalent

| Capability | WorkBuddy mechanism |
| --- | --- |
| Central workflow tools | Native `mcp__smedc__*` tools: `query_enterprise_workflows` (list and detail), `get_workflow_status`, `manage_workflow_installation`, `manage_workflow_run`, `prepare_enterprise_workflow_change`, `save_enterprise_workflow`, `record_workflow_action` |
| Official binding | `entryName=smedc`, namespace `mcp__smedc__`, service origin owned by the core skill |
| Authenticated session | Core skill login; the launcher's secure store keeps the durable session |
| Local file writes, hashing, atomic replace | Standard-library scripts in `scripts/` |
| Local download capture | `bsk download` through `wb_browser.py` |
| Python/Node runtime dependencies | Local interpreter and package probes instead of a host dependency loader |

## Equivalent with adaptation

| Codex mechanism | WorkBuddy mechanism | Residual difference |
| --- | --- | --- |
| IAB / in-app browser | `bsk` + Chrome BrowserSkill Agent Window reusing the local profile | Interactions require `cooperate sync --policy target`; default `strict` rejects click/evaluate |
| Native local cron + `automation.toml` readback | Host `automation_update` (`create`/`view`/`update`) with `cwds` | No projectId, model or reasoningEffort fields; no native TOML readback |
| Shell command execution (`exec_command`) | Local `Bash`/`subprocess` calls from the adapter scripts | Only the tool-object injection is impossible; see hard limit 3 |
| `load_workspace_dependencies` | Explicit local interpreter/package checks | Host-provided bundled library paths are unavailable |
| `@oai/artifact-tool` | The skill's own requirements and workbook builder | Must be installed in a dedicated venv, never globally |
| `tab.markHandoff()` | Reopen the verified entry in a new bsk session | Tabs do not survive a conversation turn |
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

1. **Native Gmail namespace plus `allowedSender` identity.** The distributed
   mail contract requires the host's native Gmail tools and an identity that
   matches the frozen central `allowedSender` exactly. WorkBuddy exposes a
   different Agent Mail alias; the central `email` intent identity check would
   reject it. `read_email_thread` / `in:sent` reconciliation and
   `read_attachment` byte-level `provider_readback` also have no equivalent.
   **Mail stages are blocked.** Weekly reports are delivered locally (the
   execution definition explicitly allows this), and review drafts remain in
   the frozen workbook. No SMTP, no sender override, no fabricated readback.
2. **Goal lifecycle.** `get_goal` / `create_goal` / `update_goal` do not exist.
   The upstream invocation guide says to record the execution mode as
   `unavailable` and not to create another scheduler. `wb_state.py` preserves
   run continuity locally, but this is a documented degradation, not a Goal.
3. **JS `tools` injection for the native adapter.** `native-adapters.js`
   expects an evaluation environment where the host's tool objects are
   callable. WorkBuddy has no such environment, and the workflow forbids
   replacing it with a private HTTP/JSON-RPC client. Central actions are
   therefore performed by the agent step by step; `wb_state.py` records the
   verified results and intent identities.

## Consequences that must be reported

- A completed run with a blocked mail stage is `partial`, never `succeeded`.
- A run whose lease renewal could not be kept at the original cadence keeps
  the true outcome and the exact pending scope; it is not silently replayed.
- Installation never activates a tenant, never grants upload/publish/send
  rights and never changes the central configuration.
