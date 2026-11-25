#!/usr/bin/env python3
"""Install the WorkBuddy overlay trees into a host discovery root.

The generated SKILL.md files refer to ``workbuddy/HOST_MAP.md``,
``workbuddy/WORKFLOWS.md``, ``workbuddy/references/web-access.md`` and the
``workbuddy/scripts/wb_*.py`` helpers by paths relative to **the installed
skill directory**. Those files live in this repository's ``workbuddy/`` tree, so
an install that only copies ``skills/<name>/`` plus the overlay leaves every
reference dangling. This installer copies the adapter runtime files alongside
each installed skill, making every overlay self-contained.

Nothing under the repository's ``skills/`` tree is written. The Codex discovery
root is never a valid target: pass a dedicated WorkBuddy root explicitly.

Usage::

    python3 workbuddy/scripts/install_overlays.py install --root ~/.workbuddy/skills
    python3 workbuddy/scripts/install_overlays.py check  --root ~/.workbuddy/skills

``install`` overlays files without deleting anything, so local customisations
survive; ``check`` reports leftovers and verifies the installed copies.
"""

from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SKILLS = ROOT / "skills"
GENERATED = ROOT / "workbuddy" / "overlays" / "generated"
ADAPTER = ROOT / "workbuddy"

# Files referenced by generated overlays. Kept as one source of truth in the
# repository; the installer distributes a copy into each installed skill.
ADAPTER_FILES = (
    "README.md",
    "GETTING_STARTED.md",
    "HOST_MAP.md",
    "INSTALL.md",
    "WORKFLOWS.md",
    "references/web-access.md",
    "scripts/preflight.py",
    "scripts/wb_state.py",
    "scripts/wb_schedule.py",
    "scripts/wb_mail.py",
    "scripts/wb_browser.py",
)

SKIP_PARTS = {"__pycache__", ".DS_Store"}
SKIP_SUFFIXES = {".pyc"}


def overlay_names() -> list[str]:
    return sorted(p.name for p in GENERATED.iterdir() if p.is_dir())


def copy_tree(src: Path, dst: Path) -> int:
    count = 0
    for path in src.rglob("*"):
        if not path.is_file():
            continue
        if any(part in SKIP_PARTS for part in path.parts) or path.suffix in SKIP_SUFFIXES:
            continue
        target = dst / path.relative_to(src)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, target)
        count += 1
    return count


def install_one(root: Path, name: str) -> int:
    dst = root / name
    dst.mkdir(parents=True, exist_ok=True)
    count = copy_tree(SKILLS / name, dst)
    count += copy_tree(GENERATED / name, dst)
    for rel in ADAPTER_FILES:
        target = dst / "workbuddy" / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ADAPTER / rel, target)
        count += 1
    return count


def cmd_install(args: argparse.Namespace) -> int:
    root = Path(args.root).expanduser().resolve()
    if root == Path.home() or root == Path.home() / ".agents" / "skills":
        raise SystemExit("refusing to install into a home or Codex discovery root")
    names = overlay_names()
    for name in names:
        count = install_one(root, name)
        print(f"installed {name}: {count} files")
    print(f"ok: {len(names)} skills installed under {root}")
    print("Run `check` to verify, then reload the host so it picks up the new copies.")
    return 0


def cmd_check(args: argparse.Namespace) -> int:
    root = Path(args.root).expanduser().resolve()
    problems: list[str] = []
    names = overlay_names()
    for name in names:
        dst = root / name
        if not dst.is_dir():
            problems.append(f"missing installed skill: {name}")
            continue
        expected = {str(p.relative_to(GENERATED / name))
                    for p in (GENERATED / name).rglob("*") if p.is_file()}
        expected |= {f"workbuddy/{rel}" for rel in ADAPTER_FILES}
        installed = {str(p.relative_to(dst)) for p in dst.rglob("*") if p.is_file()}
        for rel in sorted(expected - installed):
            problems.append(f"{name}: missing {rel}")
        skill_md = dst / "SKILL.md"
        if skill_md.is_file():
            text = skill_md.read_text(encoding="utf-8")
            if "WorkBuddy overlay" not in text:
                problems.append(f"{name}/SKILL.md: overlay marker missing")
            if "web-access" not in text:
                problems.append(f"{name}/SKILL.md: web-access path missing")
            for token in ("bsk", "waitForEvent", "ERR_BLOCKED_BY_CLIENT"):
                if token in text:
                    problems.append(f"{name}/SKILL.md: old-host token {token!r} remains")
        # Report files that were not shipped (possible local customisations).
        shipped = {str(p.relative_to(SKILLS / name))
                   for p in (SKILLS / name).rglob("*") if p.is_file()} | expected
        for rel in sorted(installed - shipped):
            if "__pycache__" not in rel and not rel.endswith(".pyc") and ".DS_Store" not in rel:
                print(f"note: {name} has extra local file {rel}")
    if problems:
        print("\n".join(problems), file=sys.stderr)
        return 1
    print(f"ok: {len(names)} installed skills match the repository overlays")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    for command, func in (("install", cmd_install), ("check", cmd_check)):
        p = sub.add_parser(command)
        p.add_argument("--root", default="~/.workbuddy/skills",
                       help="WorkBuddy skill discovery root (never a Codex root)")
        p.set_defaults(func=func)
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
