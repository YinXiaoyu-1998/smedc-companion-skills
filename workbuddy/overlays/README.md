# Generated WorkBuddy SKILL.md overlays

`generated/<name>/SKILL.md` replaces only the `SKILL.md` of a **copied** skill
inside the WorkBuddy discovery root. Every other file in that skill subtree
(`agents/`, `references/`, `scripts/`, `config/`, `tests/`) is used unchanged.

The repository's `skills/<name>/SKILL.md` remains byte-for-byte unchanged, so
the Codex host is unaffected. Overlays are committed so a PR reviewer can see
exactly which wording is replaced.

## Commands

```bash
# regenerate after any upstream SKILL.md change
python3 workbuddy/overlays/build_overlays.py build

# prove committed overlays match the current sources (run in CI/review)
python3 workbuddy/overlays/build_overlays.py --check
```

Note: `--check` is a global flag placed before the subcommand in the examples
above only for readability; the CLI accepts `check` as a subcommand too:

```bash
python3 workbuddy/overlays/build_overlays.py check
```

## Rules

- An overlay is generated only for a skill whose source mentions a Codex-only
  host mechanism. Host-neutral skills need no overlay.
- Replacements are deterministic and limited to host interface wording; business
  logic, filters, evidence gates, publication rules and cleanup thresholds are
  never rewritten.
- `smedc-workflows` uses a dedicated overlay that points to `workbuddy/`,
  because its source document is a host-specific runbook in its entirety.
- Applying an overlay never grants permissions, never enables a schedule and
  never changes central configuration.
