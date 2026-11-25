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

## 3. Complete the `web-access` CDP pre-flight (employee, required)

"CDP pre-flight" means letting the host's `web-access` skill attach its CDP Proxy
(`localhost:3456`) to the employee's everyday Chrome/Edge so browser work can
reuse the existing login. Chrome >=144 disables remote debugging connections by
default, so this **requires manual action by the employee**. It is a native
requirement of `web-access` for any web task, not an extra component introduced
by this adapter.

1. Start Chrome (>=144) and **leave it running**. Chrome's docs explicitly note
   that this connection mode requires the user to start the browser.
2. In the address bar open `chrome://inspect/#remote-debugging` and follow the
   dialog to enable "Allow remote debugging for this browser instance"
   (「允许对此浏览器实例进行远程调试」).
3. Run `node <web-access skill>/scripts/check-deps.mjs`. If it returns `exit 2`
   (no browser preference set), **ask the employee to choose** and write
   `WEB_ACCESS_BROWSER=chrome` (or `edge`) into `<web-access skill>/config.env`.
   That file is a gitignored user preference — the agent must not set it
   unilaterally. For a single run, `--browser chrome` overrides without writing
   the config.
4. On connection Chrome shows a remote-debugging permission dialog; the employee
   clicks **Allow** (「允许」). Success looks like `proxy: ready (...)` from
   `check-deps.mjs` and a tab array from `curl -s http://localhost:3456/targets`.
   If `/json/version` returns 404 or the Proxy log shows `non-101`, permission
   was not granted — do not retry in a loop or bypass the prompt.
5. Keep Chrome running and do not stop the CDP Proxy (the `web-access` SKILL.md
   says restarting it requires re-authorising in the browser).

### This is NOT a one-time setting

| Item | One-time? | Why |
| --- | --- | --- |
| `WEB_ACCESS_BROWSER` in `config.env` | **Yes** (persistent file) | Only removes the `exit 2` preference prompt |
| `chrome://inspect` remote-debugging toggle | **No** (per browser session) | Chrome docs: 「您需要在每个新浏览器会话开始时允许远程调试」 |
| The "Allow" dialog on connect | **No, every connection request** | Chrome docs: `every time ... Chrome will show a dialog ... and ask for their permission` |
| Chrome running | **No, every run** | Quitting the browser kills the debug port |

Doing these steps today does **not** guarantee an automated download will work a
few days later. A Chrome restart, an ended debugging session or a Proxy
reconnect can bring the permission dialog back and require a human click. For an
unattended scheduled trigger the source stage must be recorded as `blocked` and
the run closed as `partial` — never replayed or fabricated. This is Chrome's
anti-abuse design (it prevents silent takeover of a signed-in browser), not a
defect of this adapter; do not disable the safety prompt or switch to a private
client. If the business truly needs unattended collection, this CDP path cannot
provide it: trigger runs while the employee is present, or use a source
integration that does not require interactive authorisation (a host/product
change outside this adapter).

Sources: [Chrome DevTools MCP blog](https://developer.chrome.com/blog/chrome-devtools-mcp-debug-your-browser-session),
[Chrome for Developers (zh-CN)](https://developer.chrome.google.cn/docs/extensions/ai/build-with-ai).

## 4. Verify

- Re-run `--check` and `install_overlays.py check`.
- Verify every relative reference inside each installed `SKILL.md` resolves —
  in particular `<installed skill>/workbuddy/references/web-access.md` and
  `<installed skill>/workbuddy/scripts/wb_state.py`.
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
- Browser work uses the host's own `web-access` skill. Complete the CDP
  pre-flight in §3 — note it is **not one-time** (permission dialog per
  connection / browser session). See `workbuddy/references/web-access.md` §1–2.
  The Meituan login is completed by the employee in the browser; the agent
  never handles credentials. **No third-party CLI or browser extension is needed.**
- For an unattended scheduled trigger, CDP authorisation cannot be assumed to
  persist: if it is absent, the source stage is recorded as `blocked` with the
  exact pending scope and the run closes as `partial`; it is never replayed.
  Do not present this host path as a fully unattended collector.
- Mail stages stay blocked until a host with the required native mail identity
  is available. Installing this adapter grants no send or publish permission.
