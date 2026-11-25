#!/usr/bin/env python3
"""Check local WorkBuddy prerequisites from a checkout or an installed skill."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
from pathlib import Path

SCRIPT = Path(__file__).resolve()
PACKAGE = SCRIPT.parents[2]
CHECKOUT = PACKAGE if (PACKAGE / "workbuddy/bsk/build.py").is_file() else None
DEFAULT_ROOT = Path.home() / ".workbuddy" / "skills" if CHECKOUT else PACKAGE.parent
MANIFEST = "workbuddy/install-manifest.json"
INSTALL_GUIDE = "https://github.com/Tencent/BrowserSkill/blob/main/AGENT_INSTALL.md"
CORE_GUIDE = "https://github.com/YinXiaoyu-1998/smedc-mcp-skill/blob/main/skills/smedc-mcp/SKILL.md"


def run(command: list[str]) -> subprocess.CompletedProcess[str]:
    env = os.environ | {"BSK_AUTO_START": "0", "BSK_AUTO_UPDATE": "0"}
    try:
        return subprocess.run(command, capture_output=True, text=True, timeout=15, env=env)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return subprocess.CompletedProcess(command, 1, "", str(exc))


def json_output(process: subprocess.CompletedProcess[str]):
    try:
        return json.loads(process.stdout)
    except ValueError:
        return None


def read_manifest(skill: Path) -> dict:
    receipt = json.loads((skill / MANIFEST).read_text(encoding="utf-8"))
    if not isinstance(receipt, dict):
        raise ValueError("invalid install manifest")
    names = receipt.get("skills")
    files = receipt.get("files")
    if (not isinstance(names, list) or not names
            or not all(isinstance(name, str) and re.fullmatch(r"[a-z0-9-]+", name) for name in names)
            or not isinstance(files, dict) or "SKILL.md" not in files):
        raise ValueError("invalid install manifest")
    return receipt


def installed_problems(root: Path, names: list[str]) -> list[str]:
    issues = []
    for name in names:
        skill = root / name
        try:
            if skill.is_symlink() or (skill / "workbuddy").is_symlink() or (skill / MANIFEST).is_symlink():
                raise ValueError("linked skill or manifest")
            receipt = read_manifest(skill)
            if receipt["skills"] != names:
                raise ValueError("install manifest disagrees on the skill list")
            for rel, digest in receipt["files"].items():
                relative = Path(rel)
                if relative.is_absolute() or ".." in relative.parts:
                    raise ValueError("invalid manifest path")
                target = skill / relative
                if not target.is_file() or target.resolve() != target or (
                    hashlib.sha256(target.read_bytes()).hexdigest() != digest
                ):
                    issues.append(f"{name}/{rel}")
        except (OSError, ValueError) as exc:
            issues.append(f"{name}/{MANIFEST}: {exc}")
    return issues


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", default=str(DEFAULT_ROOT), help="WorkBuddy skill discovery root")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    root = Path(args.root).expanduser().resolve()
    results = []

    def add(item: str, status: str, detail: str, fix: str = "") -> None:
        results.append({"item": item, "status": status, "detail": detail, "fix": fix})

    mode = "checkout" if CHECKOUT else "installed"
    install = f"python3 workbuddy/bsk/build.py install --root {shlex.quote(str(root))}"
    if CHECKOUT:
        builder = CHECKOUT / "workbuddy/bsk/build.py"
        generation = run([sys.executable, "-B", str(builder), "check"])
        add("仓库中的生成文件", "OK" if generation.returncode == 0 else "MISSING",
            generation.stdout.strip() or generation.stderr.strip(),
            "从正确版本的源码仓库运行 python3 workbuddy/bsk/build.py build")
        names = sorted(path.parent.name for path in (builder.parent / "generated").glob("*/SKILL.md"))
    else:
        try:
            names = read_manifest(root / PACKAGE.name)["skills"]
        except (OSError, ValueError):
            names = []

    add("WorkBuddy 发现根", "OK" if root.is_dir() else "MISSING", str(root),
        f"从源码仓库运行 {install}")
    issues = installed_problems(root, names)
    installed = bool(names) and not issues
    detail = f"{len(names)} 个 Skill 的安装文件通过校验" if installed else (
        f"缺失或内容不符，共 {len(issues)} 项，例如 " + "，".join(issues[:3])
        if issues else "缺少安装清单"
    )
    add("WorkBuddy 配套 Skills", "OK" if installed else "MISSING", detail,
        f"从源码仓库重新运行 {install}")

    for name, title, fix in (
        ("smedc-mcp", "SMEDC 核心 Skill", f"按上手指南安装核心 Skill，配置 MCP 并登录。{CORE_GUIDE}"),
        ("browser-skill", "WorkBuddy BrowserSkill", f"按官方指引安装或启用 WorkBuddy 的 Skill。{INSTALL_GUIDE}"),
    ):
        path = root / name / "SKILL.md"
        add(title, "OK" if path.is_file() else "MISSING", str(path), fix)

    node = run(["node", "--version"])
    version = re.fullmatch(r"v(\d+)\.\d+\.\d+(?:[-+].*)?", node.stdout.strip())
    node_ready = node.returncode == 0 and version is not None and int(version[1]) >= 22
    npm = shutil.which("npm")
    add("SMEDC launcher 所需的 Node.js 22+ 和 npm", "OK" if node_ready and npm else "MISSING",
        f"{node.stdout.strip() or 'Node.js 未检测到'}，npm {'已找到' if npm else '未找到'}",
        "按核心 Skill 的安装指引准备 Node.js 和 npm，再从 WorkBuddy 的终端验证")

    bsk = shutil.which("bsk")
    if not bsk:
        candidate = Path.home() / ".local" / "bin" / ("bsk.exe" if os.name == "nt" else "bsk")
        if candidate.is_file() and os.access(candidate, os.X_OK):
            bsk = str(candidate)
    cli = run([bsk, "--version"]) if bsk else None
    add("bsk CLI", "OK" if cli and cli.returncode == 0 else "MISSING",
        cli.stdout.strip() if cli and cli.returncode == 0 else "未找到可运行的 bsk",
        f"安装 CLI，再在 WorkBuddy 的命令调用中验证 PATH 或使用完整路径。{INSTALL_GUIDE}")

    if cli and cli.returncode == 0:
        status = run([bsk, "status", "--json"])
        raw = json_output(status)
        active = status.returncode == 0 and isinstance(raw, dict) and bool(raw.get("pid"))
        add("bsk daemon", "OK" if active else "MISSING", "已运行" if active else "状态未确认",
            "先排除权限错误及启动中的后台任务，再按上手指南启动 daemon 并另开一次调用复查")
        if active:
            browsers = raw.get("browsers")
            chrome = [
                browser for browser in browsers
                if isinstance(browser, dict)
                and "chrome" in str(browser.get("browser_name", "")).casefold()
                and not browser.get("unresponsive")
            ] if isinstance(browsers, list) else []
            add("Chrome 扩展连接", "OK" if chrome else "MISSING",
                f"{len(chrome)} 个 Chrome 实例已连接" if chrome else "未检测到可响应的 Chrome 连接",
                f"启动 Chrome，安装并启用本地连接。{INSTALL_GUIDE}#4-connect-the-browser-extension")
            if raw.get("version_skew_browsers"):
                add("CLI / 扩展版本", "WARN", "检测到版本差异", "按腾讯指引核对版本及发布说明")

    # BrowserSkill's doctor may synchronize installed harness skills.
    add("bsk doctor", "WARN", "由员工按上手指南运行诊断并检查退出码和 FAIL 项",
        "BSK_AUTO_START=0 bsk doctor。该命令可能同步宿主 Skill，因此由上手步骤单独执行。")

    add("WorkBuddy 会话验证", "WARN", "需在新会话验证 Skill 可发现、SMEDC 已登录且美团报表可见",
        "执行上手指南的 WorkBuddy 会话验证和首次下载")

    pending = [item for item in results if item["status"] == "MISSING"]
    if args.json:
        print(json.dumps({"mode": mode, "root": str(root), "results": results, "missing": len(pending)},
                         ensure_ascii=False, indent=2))
    else:
        print(f"=== SMEDC · WorkBuddy 本地环境自检（{mode}）===")
        for item in results:
            mark = "MISS" if item["status"] == "MISSING" else item["status"]
            print(f"[{mark}] {item['item']}：{item['detail']}")
            if item["status"] != "OK" and item["fix"]:
                print(f"  → {item['fix']}")
        print(f"=== 还需要做（{len(pending)} 项）===" if pending else "=== 本地检查通过 ===")
    return 1 if pending else 0


if __name__ == "__main__":
    raise SystemExit(main())
