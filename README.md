# SMEDC Companion Skills

Independently installable workflows for SMEDC (Small and Medium Enterprises Data Center).
Each `skills/<name>/` subtree owns its guidance, references, scripts, configuration and tests.
[中文说明](README.zh.md).

## Skills

| Skill | Purpose and prerequisites |
| --- | --- |
| [smedc-business-analysis](skills/smedc-business-analysis/SKILL.md) | Operating diagnosis, weekly and monthly HTML reports from authorized SMEDC data; requires the core Skill and an authenticated session. |
| [smedc-delivery-ledger](skills/smedc-delivery-ledger/SKILL.md) | Original receipt uploads, linked quarantine photos and service-generated daily PDF/ZIP delivery; requires the core Skill and enabled archive delivery. No local ledger generation. |
| [download-meituan-business-data](skills/download-meituan-business-data/SKILL.md) | Export original business XLSX files. |
| [download-meituan-dish-sales](skills/download-meituan-dish-sales/SKILL.md) | Export original dish-sales XLSX files. |
| [download-meituan-delivery-ledger](skills/download-meituan-delivery-ledger/SKILL.md) | Export receipt ZIP batches and validate one original XLSX per receipt. |
| [meituan-order-details-download](skills/meituan-order-details-download/SKILL.md) | Export original in-store order XLSX files by date basis, store and order status; supports asynchronous downloads and time-range splitting. |
| [meituan-takeout-order-details-download](skills/meituan-takeout-order-details-download/SKILL.md) | Export original platform takeout order XLSX files by date basis, store and order filters; supports direct and asynchronous downloads. |
| [reply-meituan-reviews](skills/reply-meituan-reviews/SKILL.md) | Collect reviews into a nine-column workbook, preserve existing replies, draft unanswered written reviews and publish only explicitly approved drafts. Requires this repository's customized reply writer. |
| [review-responder](skills/review-responder/SKILL.md) | Customized Chinese restaurant-owner reply writing; original attribution is retained in the Skill. |

Meituan-only workflows require browser capabilities and a user-completed Meituan login, not an
SMEDC account. SMEDC uploads additionally require an explicit upload request, the core Skill and
an authenticated admin. Browser selection, export handling and reply approval rules live in the
linked Skills, not in a second copy here.

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
cp -R /tmp/smedc-companion-skills/skills/smedc-business-analysis ~/.agents/skills/smedc-business-analysis
cp -R /tmp/smedc-companion-skills/skills/smedc-delivery-ledger ~/.agents/skills/smedc-delivery-ledger
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

## Development

```bash
python3 -m pip install -r skills/smedc-business-analysis/requirements-dev.txt
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
