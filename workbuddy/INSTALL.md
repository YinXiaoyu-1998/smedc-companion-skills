# Installing the WorkBuddy host path

The Codex installation is authoritative and remains untouched. WorkBuddy uses
a separate discovery root (`~/.workbuddy/skills` on macOS/Linux). Never apply an
overlay inside the Codex discovery root, and never write a backup skill inside
any discovery root.

## 1. Verify the source

Resolve the default branch and record its commit SHA. All subtrees used in one
installation must come from that single commit. Verify the source subtrees are
byte-for-byte identical to the repository.

## 2. Copy complete subtrees

For each requested skill, copy the **complete** source subtree into the
WorkBuddy discovery root. Do not overlay-copy: extra or stale files must not
remain. Preserve `SKILL.md`, `agents/`, `references/`, `scripts/`, `config/`,
`assets/` and `tests/` as shipped.

## 3. Apply the generated overlay trees

For every name that has an overlay, copy the **whole**
`workbuddy/overlays/generated/<name>/` tree over the copied skill subtree.
This replaces `SKILL.md` and every adapted `references/*.md` in one step;
unadapted files stay as shipped. Skills without an overlay are already host
neutral and are used as-is.

```bash
python3 workbuddy/overlays/build_overlays.py --check
cp -R workbuddy/overlays/generated/<name>/. \
   ~/.workbuddy/skills/<name>/
```

`--check` proves the committed overlays match the current Codex sources and
contain no host-specific tokens. If it fails, regenerate with `build`, review
the diff, then install. Verify that `~/.workbuddy/skills/<name>/references/`
contains the adapted files before starting a run.

## 4. Verify

- Re-run `--check`.
- Verify every relative reference inside each installed `SKILL.md` resolves.
- Confirm the host reloads the WorkBuddy copy and that no Codex copy shadows it.
- Keep recovery copies outside all discovery roots; remove them only after the
  host reload is confirmed.

## 5. Schedule (optional, separate step)

`python3 workbuddy/scripts/wb_schedule.py --workspace <dedicated-abs-path> specs`
renders three PAUSED specifications. It does not create tasks. An exact RRULE
requires explicit employee confirmation; on a migration, read the existing
host's schedule back and preserve the RRULE verbatim. Do not write
`automation.toml` from this adapter.

## 6. Prerequisites

- The core skill owns launcher installation, login and the approved pin.
- Browser work needs the `bsk` CLI plus the Chrome BrowserSkill extension and
  an employee-completed Meituan login. `wb_browser.py doctor` checks the
  daemon and browser connection; it does not test credentials.
- Mail stages stay blocked until a host with the required native mail identity
  is available. Installing this adapter grants no send or publish permission.
