# smedc-companion-skills

Companion agent skills for SMEDC, the Small and Medium Enterprises Data Center.

This repository is organized as independently installable sibling skills under `skills/`. Each skill owns its own `SKILL.md`, metadata, scripts, config, tests, and development requirements. The repository root owns packaging documentation and cross-skill validation.

## Skills

- `skills/smedc-business-analysis/`: tenant-neutral operating diagnosis, weekly meeting, and monthly meeting reports from SMEDC structured business datasets.
- `skills/smedc-delivery-ledger/`: original receipt upload, receipt-linked photo operations, and automatic daily PDF update/readiness/ZIP download coordination after archive rollout. Local XLSX/CSV exports and monthly maintenance have been removed.
- `skills/download-meituan-dish-sales/`: download original Meituan dish-sales XLSX reports for a business-date range; optionally upload to SMEDC `dishes` when requested.
- `skills/download-meituan-business-data/`: download original Meituan business XLSX reports for a business-date range; optionally upload to SMEDC `business` when requested.
- `skills/download-meituan-delivery-ledger/`: export received store receipts by receipt date, download ZIP batches page by page, and validate one original XLSX per receipt for optional SMEDC `delivery_ledger` upload.
- `skills/reply-meituan-reviews/`: read unanswered Meituan and Dianping reviews, skip reviews without written content, draft a five-column XLSX for approval, then publish only the approved version and scope.
- `skills/review-responder/`: the user's customized Chinese restaurant-owner reply writer and required drafting dependency for `reply-meituan-reviews`; retains the original skill attribution.

## Installation

For SMEDC access, install the prerequisite core skill first. Meituan-only downloads and review replies require browser capabilities and a Meituan login; they do not require an SMEDC account:

```bash
mkdir -p ~/.agents/skills
git clone https://github.com/YinXiaoyu-1998/smedc-mcp-skill.git /tmp/smedc-mcp-skill
cp -R /tmp/smedc-mcp-skill/skills/smedc-mcp ~/.agents/skills/smedc-mcp
```

Install the business-analysis skill by copying only its subtree:

```bash
mkdir -p ~/.agents/skills
git clone https://github.com/YinXiaoyu-1998/smedc-companion-skills.git /tmp/smedc-companion-skills
cp -R /tmp/smedc-companion-skills/skills/smedc-business-analysis ~/.agents/skills/smedc-business-analysis
```

Install the delivery-ledger skill the same way, copying only its subtree:

```bash
mkdir -p ~/.agents/skills
git clone https://github.com/YinXiaoyu-1998/smedc-companion-skills.git /tmp/smedc-companion-skills
cp -R /tmp/smedc-companion-skills/skills/smedc-delivery-ledger ~/.agents/skills/smedc-delivery-ledger
```

The business-analysis skill requires an authenticated `smedc-mcp` session using `smedc-mcp-launcher@0.11.0` and MCP entry `smedc`. If that prerequisite is missing, the skill must stop before report data access and ask for explicit authorization before installing it. It never installs another companion skill automatically.

The delivery-ledger skill uses the same authenticated core prerequisite for original uploads and photo operations. Its PDF workflow uses the published and independently verified `smedc-mcp-launcher@0.11.0` core pin and also requires service archive delivery enabled. It polls actual import application, explains that PDFs update automatically and availability is confirmed by their status, then checks coverage before preparing existing PDFs and requesting a fresh ZIP link. Employee agents cannot trigger PDF generation through MCP or HTTP. Retired local `export_ledger.py`, `export_ledger_csv.py`, and monthly maintenance are removed; no local PDF/XLSX/CSV generation or `openpyxl` dependency remains. If archive delivery is not enabled, report it as unavailable and wait for the service rollout. It never installs another companion automatically.

To install the three Meituan download skills, reuse the companion repository checkout above (or clone it first), then copy their subtrees:

```bash
cp -R /tmp/smedc-companion-skills/skills/download-meituan-dish-sales ~/.agents/skills/download-meituan-dish-sales
cp -R /tmp/smedc-companion-skills/skills/download-meituan-business-data ~/.agents/skills/download-meituan-business-data
cp -R /tmp/smedc-companion-skills/skills/download-meituan-delivery-ledger ~/.agents/skills/download-meituan-delivery-ledger
```

These are first-install examples. If a destination already exists, compare versions and preserve local changes before updating; do not blindly copy into an existing skill directory.

Install the review workflow and its required customized writer from the same checkout, copying each skill subtree:

```bash
cp -R /tmp/smedc-companion-skills/skills/review-responder ~/.agents/skills/review-responder
cp -R /tmp/smedc-companion-skills/skills/reply-meituan-reviews ~/.agents/skills/reply-meituan-reviews
```

It requires this repository's customized `review-responder`, public-information search, and local XLSX authoring/checking capabilities in addition to browser access. Missing dependencies stop collection and drafting; no writer is installed, replaced, or substituted silently. By default it covers both channels and records customer name, original review, draft reply, total/subscores, and review date. Publication requires approval of a specific workbook version and rows. No SMEDC upload or live posting happens during draft creation. Its built-in-browser-first login flow checks the actual default local browser's existing session before asking the user to log in; it does not transfer credentials or assume Chrome is the default. The writer drafts text only; the Meituan workflow owns spreadsheet review and approved publication, and overrides the writer's generic star-only reply guidance by skipping reviews without written content.

In Codex, the three download skills prefer the built-in Chromium browser (`iab`), including login, export, and download. They use a local browser only when the user selects it or a required capability/session is unavailable in the built-in browser, and explain the reason before switching. A local Chrome login alone is not a reason to switch for those download skills.

The download skills default to the current user's `~/Downloads` (fallback `~/Desktop`) and generic `meituan_...` filenames. They preserve original exports and share the Chrome download-event/native Save handling for `ERR_BLOCKED_BY_CLIENT`. Download capture defaults to one continuous 45-second wait inside a 60-second tool call, with at most one checked retry per file/batch. Dish-sales and business downloads were verified in local Chrome; a 92-receipt batch was also downloaded and validated in the built-in browser with the longer wait. These observations do not guarantee all exports finish within 45 seconds. SMEDC uploads require a user request, the core `smedc-mcp` skill, and an authenticated admin. Meituan credentials are entered by the user in the browser. The workflows are agent-neutral; the browser API examples target environments exposing `cua_repl` / `tab.playwright` / `cua.getApp`. Other agents need equivalent browser, download, and local-file capabilities, with download behavior verified in their own environment. No browser automation runtime is bundled here.

## Development

Run all repository checks:

```bash
python3 scripts/validate_all_skills.py
```

Run individual skill checks directly:

```bash
python3 -m unittest discover -s skills/smedc-business-analysis/tests -v
python3 /Users/xiaoyuyin/.codex/skills/.system/skill-creator/scripts/quick_validate.py skills/smedc-business-analysis
python3 -m unittest discover -s skills/smedc-delivery-ledger/tests -v
python3 /Users/xiaoyuyin/.codex/skills/.system/skill-creator/scripts/quick_validate.py skills/smedc-delivery-ledger
```

Delivery-ledger contract tests use Python standard library. Business-analysis tests use PyYAML only to validate `agents/openai.yaml`; install their development dependencies when needed:

```bash
python3 -m pip install -r skills/smedc-business-analysis/requirements-dev.txt
```
