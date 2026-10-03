# smedc-companion-skills

Companion Codex skills for SMEDC, the Small and Medium Enterprises Data Center.

This repository is organized as independently installable sibling skills under `skills/`. Each skill owns its own `SKILL.md`, metadata, scripts, config, tests, and development requirements. The repository root owns packaging documentation and cross-skill validation.

## Skills

- `skills/smedc-business-analysis/`: tenant-neutral operating diagnosis, weekly meeting, and monthly meeting reports from SMEDC structured business datasets.
- `skills/smedc-delivery-ledger/`: statutory receipt-aware delivery-ledger lookup, XLSX export with explicit text phone cells, optional CSV, per-store monthly maintenance, plus receipt-linked quarantine-certificate photo guidance.

## Installation

Install the prerequisite core skill first:

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

The business-analysis skill requires an authenticated `smedc-mcp` session using `smedc-mcp-launcher@0.6.0` and MCP entry `smedc`. If that prerequisite is missing, the skill must stop before report data access and ask for explicit authorization before installing it. It never installs another companion skill automatically.

The delivery-ledger skill uses the same authenticated `smedc-mcp` prerequisite for ledger queries, spreadsheet export and per-store monthly maintenance source data, and quarantine-certificate photo operations. It defaults to XLSX; CSV is available when explicitly requested. XLSX requires `openpyxl` from `skills/smedc-delivery-ledger/requirements.txt` in the Python environment running the exporter; the skill explains isolated setup when needed. It never installs another companion skill automatically.

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

Business-analysis and CSV runtime scripts use Python standard library; delivery-ledger XLSX export/tests also use `openpyxl` from that skill's `requirements.txt`. The business-analysis tests use PyYAML only to validate `agents/openai.yaml`; install development dependencies from the business-analysis subtree when needed:

```bash
python3 -m pip install -r skills/smedc-business-analysis/requirements-dev.txt -r skills/smedc-delivery-ledger/requirements.txt
```
