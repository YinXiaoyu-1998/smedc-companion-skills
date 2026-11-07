# Generated WorkBuddy overlays

`generated/<name>/` is a directory tree, not a single file. It replaces
`SKILL.md` and any adapted `references/*.md` of a **copied** skill inside the
WorkBuddy discovery root. Files that are not generated (`agents/`, `scripts/`,
`config/`, `assets/`, `tests/`, unadapted references) stay exactly as shipped.

The repository's `skills/` tree remains byte-for-byte unchanged, so the Codex
host is unaffected. Overlays are committed so a PR reviewer can see exactly
which wording is replaced.

## Commands

```bash
# regenerate after any upstream SKILL.md or references/ change
python3 workbuddy/overlays/build_overlays.py build

# prove committed overlays match the sources and contain no Codex-only tokens
python3 workbuddy/overlays/build_overlays.py --check
python3 workbuddy/overlays/build_overlays.py check   # equivalent subcommand
```

Both spellings call the same checker. `build` refuses to write if a generated
file still contains a host-specific token from `FORBIDDEN_PATTERNS`.

## Rules

- An overlay is generated for a skill whose `SKILL.md` **or** any
  `references/*.md` mentions a Codex-only host mechanism. Host-neutral skills
  need no overlay.
- Whole conflicting sentences are replaced before individual identifiers, so
  IAB-first / "do not use the local Chrome session" instructions cannot survive
  as inverted advice.
- Replacements are deterministic and limited to host interface wording; business
  logic, filters, evidence gates, publication rules and cleanup thresholds are
  never rewritten.
- `smedc-workflows` uses a dedicated overlay that points to `workbuddy/`, because
  its source document is a host-specific runbook in its entirety.
- Applying an overlay never grants permissions, never enables a schedule and
  never changes central configuration.
