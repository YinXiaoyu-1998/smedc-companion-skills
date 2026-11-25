# Installing the WorkBuddy host path

The Codex installation is authoritative and remains untouched. WorkBuddy uses
a separate discovery root (`~/.workbuddy/skills` on macOS/Linux). Never apply an
overlay inside the Codex discovery root, and never write a backup skill inside
any discovery root.

## 1. Verify the source

Resolve the default branch and record its commit SHA. All subtrees used in one
installation must come from that single commit. Verify the source subtrees are
byte-for-byte identical to the repository.

## 2. Install with the installer (required)

The generated SKILL.md files refer to `workbuddy/HOST_MAP.md`,
`workbuddy/WORKFLOWS.md`, `workbuddy/references/web-access.md` and the
`workbuddy/scripts/wb_*.py` helpers by paths **relative to the installed skill
directory**. Those files live in this repository's `workbuddy/` tree; copying
only `skills/<name>/` plus the overlay leaves every one of those references
dangling, and the workflow breaks at its first step. Use the installer, which
distributes the adapter runtime files into each installed skill so each copy is
self-contained:

```bash
python3 workbuddy/overlays/build_overlays.py --check
python3 workbuddy/scripts/install_overlays.py install --root ~/.workbuddy/skills
python3 workbuddy/scripts/install_overlays.py check   --root ~/.workbuddy/skills
```

The installer does, in order, for every `workbuddy/overlays/generated/<name>/`:

1. copies the **complete** `skills/<name>/` subtree (preserving `agents/`,
   `references/`, `scripts/`, `config/`, `assets/`, `tests/` as shipped);
2. overlays the whole generated tree, replacing `SKILL.md` and every adapted
   `references/*.md` in one step;
3. copies the `workbuddy/` runtime files listed in the installer into
   `<installed skill>/workbuddy/`, so `workbuddy/...` references resolve.

`--check` proves the committed overlays match the current Codex sources and
contain no host-specific tokens. If it fails, regenerate with `build`, review
the diff, then install. `install_overlays.py` overwrites files but never deletes
them, so local customisations survive; `check` reports any extra local files,
missing overlay/adapter files and old-host tokens (`bsk`, `waitForEvent`,
`ERR_BLOCKED_BY_CLIENT`).

Do **not** hand-copy only `generated/<name>/.` with `cp -R`: that was the
earlier, broken procedure. Skills without an overlay are already host-neutral
and are used as-is.

## 3. Verify

- Re-run `--check` and `install_overlays.py check`.
- Verify every relative reference inside each installed `SKILL.md` resolves —
  in particular `<installed skill>/workbuddy/references/web-access.md` and
  `<installed skill>/workbuddy/scripts/wb_state.py`.
- Confirm the host reloads the WorkBuddy copy and that no Codex copy shadows it.
- Keep recovery copies outside all discovery roots; remove them only after the
  host reload is confirmed.

## 4. Schedule (optional, separate step)

`python3 workbuddy/scripts/wb_schedule.py --workspace <dedicated-abs-path> specs`
renders three PAUSED specifications. It does not create tasks. An exact RRULE
requires explicit employee confirmation; on a migration, read the existing
host's schedule back and preserve the RRULE verbatim. Do not write
`automation.toml` from this adapter.

## 5. Prerequisites

- The core skill owns launcher installation, login and the approved pin.
- Browser work uses the host's own `web-access` skill. Its native pre-flight
  (`scripts/check-deps.mjs`, Node.js 22+, browser remote-debugging
  authorization and connection approval) is required by that skill for any
  WorkBuddy web task; follow its SKILL.md. See `workbuddy/references/web-access.md` §1–2.
  The Meituan login is completed by the employee in the browser; the agent
  never handles credentials. **No third-party CLI or browser extension is needed.**
- At a scheduled trigger the browser must be online with the authorization
  still valid. If it is not, the source stage is recorded as `blocked` with the
  exact pending scope and the run closes as `partial`; it is never replayed.
- Mail stages stay blocked until a host with the required native mail identity
  is available. Installing this adapter grants no send or publish permission.
