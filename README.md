# SMEDC Companion Skills

Independently installable workflows for SMEDC (Small and Medium Enterprises Data Center).
Each `skills/<name>/` subtree owns its guidance, references, scripts, configuration and tests.
[中文说明](README.zh.md).

## Skills

| Skill | Purpose and prerequisites |
| --- | --- |
| [smedc-workflows](skills/smedc-workflows/SKILL.md) | Independently select daily ingestion, review operations or weekly reports; versioned Codex/Gmail adapters, readiness, bounded migration and recovery. Requires compatible released service/launcher; installation does not enable tasks. |
| [smedc-business-analysis](skills/smedc-business-analysis/SKILL.md) | Operating diagnosis, weekly and monthly HTML reports from authorized SMEDC data; requires the core Skill and an authenticated session. |
| [smedc-delivery-ledger](skills/smedc-delivery-ledger/SKILL.md) | Original receipt uploads, linked quarantine photos and service-generated daily PDF/ZIP delivery; requires the core Skill and enabled archive delivery. No local ledger generation. |
| [smedc-inspection](skills/smedc-inspection/SKILL.md) | Read and fill authorized store inspection sheets or prepare template drafts. Candidate source. Live use requires the four inspection tools, a compatible launcher and service, and current permissions. |
| [download-meituan-business-data](skills/download-meituan-business-data/SKILL.md) | Export original business XLSX files. |
| [download-meituan-dish-sales](skills/download-meituan-dish-sales/SKILL.md) | Export original dish-sales XLSX files. |
| [download-meituan-combo-sales](skills/download-meituan-combo-sales/SKILL.md) | Export and verify original single-day combo item sales XLSX files. |
| [download-meituan-delivery-ledger](skills/download-meituan-delivery-ledger/SKILL.md) | Export receipt ZIP batches and validate one original XLSX per receipt. |
| [meituan-order-details-download](skills/meituan-order-details-download/SKILL.md) | Export original in-store order XLSX files by date basis, store and order status; supports asynchronous downloads and time-range splitting. |
| [meituan-takeout-order-details-download](skills/meituan-takeout-order-details-download/SKILL.md) | Export original platform takeout order XLSX files by date basis, store and order filters; supports direct and asynchronous downloads. |
| [reply-meituan-reviews](skills/reply-meituan-reviews/SKILL.md) | Collect reviews into a nine-column workbook, preserve existing replies, draft unanswered written reviews and publish only explicitly approved drafts. Requires this repository's customized reply writer. |
| [review-responder](skills/review-responder/SKILL.md) | Customized Chinese restaurant-owner reply writing; original attribution is retained in the Skill. |

Meituan-only workflows require browser capabilities and a user-completed Meituan login, not an
SMEDC account. SMEDC structured-data uploads additionally require an explicit upload request, the
core Skill and an authenticated admin. Inspection photo uploads require current store fill
permission. Browser selection, export handling and reply approval rules live in the linked Skills,
not in a second copy here.

Ask your agent to “Upgrade SMEDC” to refresh all official companion Skills already installed on this computer.

## Shared workflows and enterprise settings

Distributed skills carry no tenant names, store rosters, source accounts, recipient addresses,
publication whitelists or tenant schedules. Standalone skills use the current request and observed
source scope; `smedc-workflows` supplies confirmed enterprise settings to the selected skills.
Fresh schedules require user confirmation; migration preserves actual host readback without a
package-wide default. macOS Codex, Gmail, Asia/Shanghai and Meituan report formats are supported
product capabilities. The Chinese restaurant voice is a reusable default; brand facts, tone and
publication authorization come from the caller. Synthetic identities and historical schedules in
tests are regression fixtures, never installation inputs.

## Version Ownership

The [official core Skill](https://github.com/YinXiaoyu-1998/smedc-mcp-skill/blob/main/skills/smedc-mcp/SKILL.md)
owns the approved exact launcher installation pin and update/login procedure. Companions use that
pin with MCP entry `smedc`; they do not select npm `latest`, override it from service metadata, or
maintain independent installation versions. Package publication, service rollout and tenant
configuration are separate checks.

Skill revisions are identified by the source Git commit and subtree, not the launcher version.
Updating this repository does not update the core Skill, launcher or installed local copies.
Missing prerequisites stop data access; install or upgrade only within the user's authorized scope.

## Installation And Updates

Use `~/.agents/skills` (Windows: `%USERPROFILE%\.agents\skills`). The following are **first-install
examples only**; run only the commands for requested skills. All target skill directories must be
absent. Use fresh checkout paths if the temporary directories already exist.

For SMEDC access, install only the core subtree:

```bash
mkdir -p ~/.agents/skills
git clone https://github.com/YinXiaoyu-1998/smedc-mcp-skill.git /tmp/smedc-mcp-skill
cp -R /tmp/smedc-mcp-skill/skills/smedc-mcp ~/.agents/skills/smedc-mcp
```

Clone the companion repository once, then copy only requested subtrees:

```bash
git clone https://github.com/YinXiaoyu-1998/smedc-companion-skills.git /tmp/smedc-companion-skills
cp -R /tmp/smedc-companion-skills/skills/smedc-workflows ~/.agents/skills/smedc-workflows
cp -R /tmp/smedc-companion-skills/skills/smedc-business-analysis ~/.agents/skills/smedc-business-analysis
cp -R /tmp/smedc-companion-skills/skills/smedc-delivery-ledger ~/.agents/skills/smedc-delivery-ledger
cp -R /tmp/smedc-companion-skills/skills/smedc-inspection ~/.agents/skills/smedc-inspection
cp -R /tmp/smedc-companion-skills/skills/download-meituan-business-data ~/.agents/skills/download-meituan-business-data
cp -R /tmp/smedc-companion-skills/skills/download-meituan-dish-sales ~/.agents/skills/download-meituan-dish-sales
cp -R /tmp/smedc-companion-skills/skills/download-meituan-delivery-ledger ~/.agents/skills/download-meituan-delivery-ledger
cp -R /tmp/smedc-companion-skills/skills/meituan-order-details-download ~/.agents/skills/meituan-order-details-download
cp -R /tmp/smedc-companion-skills/skills/meituan-takeout-order-details-download ~/.agents/skills/meituan-takeout-order-details-download
cp -R /tmp/smedc-companion-skills/skills/review-responder ~/.agents/skills/review-responder
cp -R /tmp/smedc-companion-skills/skills/reply-meituan-reviews ~/.agents/skills/reply-meituan-reviews
```

For an existing installation, fetch the default branch and record its commit; compare the complete
requested subtree with the installed copy and preserve local customizations. Stage and validate the
replacement, keep recovery copies outside all Skill discovery roots, then replace the complete
subtree. Do not overlay it, leave obsolete files, or create backup Skills inside the discovery root.
Verify file contents and the host's loaded copy before removing recovery copies and reporting
success. Report pending host reloads. Install no unrequested companions or dependencies silently.
The core Skill has its own [replacement procedure](https://github.com/YinXiaoyu-1998/smedc-mcp-skill/blob/main/skills/smedc-mcp/references/update-skill.md).

### Refresh installed companions during a general upgrade

1. Fetch the default branch of [the official companion repository](https://github.com/YinXiaoyu-1998/smedc-companion-skills) into a temporary checkout and record its exact commit. Use this revision for all companion copies and any existing scheduled workflows in the same upgrade.
2. Inventory the current user's effective companion copies in the hosts' actual discovery roots. Match each installed Skill ID and complete subtree to the official checkout and verify its provenance using its installed source record or a known official revision. Exclude source checkouts, backups, uninstalled Skills and unrelated Skills. Report ambiguous origins or conflicting local changes and continue with the verified copies. Refresh host-managed copies through their supported update mechanism. Resolve path aliases to avoid updating a physical directory twice.
3. Finish or reconcile any active work that needs the old files. Update verified scheduled tasks and their selected dependencies through the [task upgrade procedure](skills/smedc-workflows/references/installation.md#升级本机定时任务). Refresh the remaining installed companions per target discovery root with the official checkout's `python3 skills/smedc-workflows/scripts/workflow.py refresh-installed --input <request.json>`. Use the platform's equivalent Python 3.11+ invocation if needed. If Python is unavailable, apply the same verified whole-directory replacement and readback through the host's supported Skill update mechanism.
4. Supply `sourceRevision` (the recorded Git SHA), `sourceSkillsRoot` (the checkout's absolute `skills/` directory), `destinationRoot` (the absolute physical discovery root), `installedSkillIds` (the verified names already present there) and a private absolute `recoveryRoot` outside all discovery roots. For WorkBuddy, prepare the effective source trees by applying the matching [generated overlays](workbuddy/INSTALL.md) in a temporary staging directory from the same revision, then use that directory as `sourceSkillsRoot`. Keep executing the helper from the official checkout.
5. Run with `planOnly: true` to obtain `toReplace` and `currentSkillHashes`. Compare each changed installed tree with its known official source to preserve local customizations. For verified copies covered by the upgrade request, supply their observed hashes in `expectedInstalledHashes` and run without `planOnly`. The command rejects missing targets and verifies complete replacements. It does not write task installation locks. If a multi-Skill refresh stops partway, rerun the preview to reconcile the actual installed trees and retained recovery copies before retrying.
6. Verify the installed bytes and loaded path for each updated or already-current copy in its host. Record revision, loaded paths, and any blocked or pending reload. Keep recovery copies outside discovery until reload succeeds.

## Development

```bash
python3 -m pip install -r skills/smedc-business-analysis/requirements-dev.txt -r skills/reply-meituan-reviews/requirements-dev.txt -r skills/smedc-workflows/requirements-dev.txt
python3 scripts/validate_all_skills.py
```

Focused checks:

```bash
python3 -m unittest discover -s skills/smedc-business-analysis/tests -v
python3 -m unittest discover -s skills/smedc-delivery-ledger/tests -v
```

Delivery-ledger tests use the Python standard library; business-analysis metadata tests also use
PyYAML. Runtime instructions and data-cleanup requirements belong to each Skill. Keep temporary
reports, downloaded data and execution transcripts outside this repository.

## WorkBuddy host support (additive)

A second host path is available in [`workbuddy/`](workbuddy/README.md). It installs generated
SKILL.md overlays into the WorkBuddy discovery root; every file under `skills/` stays byte-for-byte
unchanged, so the Codex prompts, scripts, tests and installation path are unaffected. The adapter
is tenant-neutral and carries no enterprise names, store rosters, source accounts, recipient
addresses or schedules.

Two mutually exclusive browser profiles are available: `web-access` (CDP Proxy, no extra
components) and `browser-skill` (`bsk` CLI + Chrome extension, recommended for unattended
runs). **New users start at [`workbuddy/GETTING_STARTED.md`](workbuddy/GETTING_STARTED.md)**
and run the read-only `python3 workbuddy/scripts/preflight.py`, which reports exactly which
dependencies and configuration are still missing — `bsk` CLI, Chrome extension pairing,
daemon, Node.js, Chrome remote debugging, installed overlays — with a fix command for each.
The browser-skill profile needs a one-time install of the `bsk` CLI and Chrome extension plus
`bsk daemon pair`; the web-access profile needs Chrome's per-connection remote-debugging
approval. Both are host prerequisites, documented step by step in the getting-started guide.

Supported on WorkBuddy: the native `mcp__smedc__*` workflow tools, browser source reads,
validated landing of the resulting download file, hash-chained local run-state continuation,
and PAUSED schedule specifications. Authoritative playbooks:
`workbuddy/references/web-access.md` and `workbuddy/bsk/references/browser-skill.md`.
Installation never activates a schedule and never grants send, upload or publish permission.

Hard limits: WorkBuddy has no native Gmail namespace matching the central `allowedSender`, no
Goal lifecycle, no JS environment with injected host tools, and no native download-event API or
window-level Save-panel control. Mail stages are therefore recorded as blocked with local delivery
(weekly reports keep the final HTML; review drafts stay in the workbook); run continuity uses a
local state file instead of a Goal; central claim/check/record calls are issued step by step by
the agent. The CDP pre-flight is **not one-time**: Chrome asks for permission on every
debugging session / new browser session and must stay running, so an unattended scheduled
download cannot be relied on — see `workbuddy/INSTALL.md` §3. When authorisation is absent,
the source stage is blocked and the run closes as partial. See
`workbuddy/HOST_MAP.md` for the full mapping. These stages must be reported as partial or
degraded, never as a successful send.
