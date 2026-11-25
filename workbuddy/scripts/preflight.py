#!/usr/bin/env python3
"""Read-only environment probe for a brand-new WorkBuddy + SMEDC user.

Tells the employee exactly what is already present and what still needs to be
installed/configured, for the selected browser profile. It never installs,
writes, starts a daemon, logs in, or changes any configuration.

    python3 workbuddy/scripts/preflight.py
    python3 workbuddy/scripts/preflight.py --profile browser-skill
    python3 workbuddy/scripts/preflight.py --json

Exit codes: 0 = everything required is present, 1 = something is missing,
2 = probe could not run (bad arguments / missing repository).
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import shutil
import subprocess
import sys
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
DEFAULT_ROOT = Path.home() / ".workbuddy" / "skills"
WEB_ACCESS_SKILL = Path.home() / ".workbuddy" / "skills" / "web-access"

# Relative to each installed skill's workbuddy/ directory.
PROFILE_MANUALS = {
    "browser-skill": "references/browser-skill.md",
    "web-access": "references/web-access.md",
}
REQUIRED_ADAPTER = (
    "HOST_MAP.md", "WORKFLOWS.md", "INSTALL.md", "GETTING_STARTED.md",
    "scripts/wb_state.py", "scripts/wb_schedule.py", "scripts/wb_mail.py",
)
OVERLAY_NAMES = (
    "download-meituan-business-data", "download-meituan-combo-sales",
    "download-meituan-delivery-ledger", "download-meituan-dish-sales",
    "meituan-order-details-download", "meituan-takeout-order-details-download",
    "reply-meituan-reviews", "smedc-workflows",
)

results: list[dict] = []


def add(item: str, ok: bool | None, detail: str, fix: str = "") -> None:
    status = "OK" if ok is True else ("WARN" if ok is None else "MISSING")
    results.append({"item": item, "status": status, "detail": detail,
                    "fix": fix if ok is not True else ""})


def run(cmd: list[str], timeout: int = 12, env_extra: dict | None = None):
    env = os.environ.copy()
    if env_extra:
        env.update(env_extra)
    try:
        p = subprocess.run(cmd, capture_output=True, text=True,
                           timeout=timeout, env=env)
        return p.returncode, (p.stdout or "").strip(), (p.stderr or "").strip()
    except (OSError, subprocess.TimeoutExpired) as exc:
        return 1, "", str(exc)


def bsk_path() -> str | None:
    return shutil.which("bsk") or (
        str(Path.home() / ".local/bin/bsk")
        if (Path.home() / ".local/bin/bsk").is_file() else None)


def detect_profile(root: Path) -> str | None:
    skill = root / "smedc-workflows" / "SKILL.md"
    if not skill.is_file():
        return None
    text = skill.read_text(encoding="utf-8", errors="ignore")
    if "browser-skill profile" in text:
        return "browser-skill"
    if "web-access" in text and "宿主适配" in text:
        return "web-access"
    return None


def probe_repo() -> None:
    add("源码仓库 skills/ 子树", (REPO / "skills").is_dir(),
        str(REPO / "skills"),
        "先克隆本仓库：git clone https://github.com/YinXiaoyu-1998/smedc-companion-skills.git")
    for rel in ("workbuddy/overlays/generated",
                "workbuddy/bsk/generated",
                "workbuddy/GETTING_STARTED.md",
                "workbuddy/scripts/install_overlays.py",
                "workbuddy/bsk/build.py"):
        add(f"仓库文件 {rel}", (REPO / rel).exists(), str(REPO / rel),
            "重新拉取仓库默认分支，确保所有 workbuddy/ 文件齐全")


def probe_install(root: Path, profile: str) -> None:
    add("WorkBuddy 发现根", root.is_dir(), str(root),
        "mkdir -p ~/.workbuddy/skills")
    missing = [n for n in OVERLAY_NAMES if not (root / n / "SKILL.md").is_file()]
    add("8 个配套 skill 已安装", not missing,
        "齐全" if not missing else "缺少: " + ", ".join(missing),
        "python3 workbuddy/scripts/install_overlays.py install --root ~/.workbuddy/skills"
        if profile == "web-access" else
        "python3 workbuddy/bsk/build.py install --root ~/.workbuddy/skills")
    manual = PROFILE_MANUALS[profile]
    bad = []
    for n in OVERLAY_NAMES:
        base = root / n
        for rel in (*REQUIRED_ADAPTER, manual):
            if not (base / "workbuddy" / rel).is_file():
                bad.append(f"{n}/{rel}")
    add("每个 skill 自带适配层与手册", not bad,
        "齐全" if not bad else f"缺少 {len(bad)} 项，例如 {bad[:3]}",
        "重新运行对应 profile 的安装器（安装器会补齐 workbuddy/ 运行期文件）")


def probe_overlay_sync() -> None:
    for label, cmd in (("web-access overlay 一致性",
                        [sys.executable, str(REPO / "workbuddy/overlays/build_overlays.py"), "--check"]),
                       ("browser-skill overlay 一致性",
                        [sys.executable, str(REPO / "workbuddy/bsk/build.py"), "check"])):
        rc, out, err = run(cmd, timeout=30)
        add(label, rc == 0, (out or err).splitlines()[-1] if (out or err) else "无输出",
            "运行 python3 workbuddy/overlays/build_overlays.py build / "
            "python3 workbuddy/bsk/build.py build 重新生成")


def probe_node() -> None:
    rc, out, err = run(["node", "--version"])
    version = out or err
    major = int(version.lstrip("v").split(".")[0]) if version.lstrip("v")[:1].isdigit() else 0
    add("Node.js >= 22（web-access 需要）", major >= 22,
        version or "未安装", "安装 Node.js 22+（https://nodejs.org）" if major < 22 else "")


def probe_bsk_cli() -> tuple[str | None, dict]:
    exe = bsk_path()
    add("bsk CLI 已安装", exe is not None, exe or "未在 PATH 或 ~/.local/bin 找到",
        "按官方指引安装：https://github.com/Tencent/BrowserSkill/blob/main/AGENT_INSTALL.md")
    if not exe:
        return None, {}
    rc, out, _ = run([exe, "--version"])
    add("bsk CLI 可运行", rc == 0, out or f"exit={rc}", "重新执行官方安装器并确认 PATH")
    env = {"BSK_AUTO_START": "0"}
    rc, out, _ = run([exe, "status", "--json"], env_extra=env)
    status = {}
    try:
        status = json.loads(out)
    except (ValueError, TypeError):
        pass
    daemon_ok = rc == 0 and bool(status.get("pid"))
    add("bsk daemon 正在运行", daemon_ok,
        f"pid={status.get('pid')} uptime={status.get('uptime_secs')}s" if daemon_ok
        else "未运行（agent 每轮可自动拉起）",
        "" if daemon_ok else
        "用宿主后台任务运行: BSK_AUTO_START=0 bsk daemon start --foreground "
        "（另一次调用里复查 status --json）")
    browsers = status.get("browsers") or []
    add("Chrome 扩展已连接", bool(browsers),
        ", ".join(f"{b.get('browser_name')} {b.get('instance_id')}" for b in browsers)
        or "未连接",
        "" if browsers else
        "按官方扩展安装与配对步骤操作："
        "https://github.com/Tencent/BrowserSkill/blob/main/AGENT_INSTALL.md#4-connect-the-browser-extension"
        "；必要时 bsk daemon pair 并把 private link 粘进扩展连接设置")
    skew = status.get("version_skew_browsers") or []
    # doctor reports "still usable" for skew: advisory, not a blocker.
    add("CLI / 扩展版本一致", True if not skew else None,
        "一致" if not skew else f"{len(skew)} 个浏览器有 version skew（doctor 标 still usable）",
        "bsk update 后重启 daemon（非阻塞，建议消除）" if skew else "")
    rc, out, err = run([exe, "doctor"], env_extra=env, timeout=20)
    fails = [l.strip() for l in (out + "\n" + err).splitlines()
             if l.strip().startswith("FAIL")]
    add("bsk doctor 无 FAIL 项", not fails,
        "；".join(fails[:3]) if fails else "全部通过",
        "按 bsk doctor 输出的 hint 逐项修复" if fails else "")
    return exe, status


def probe_web_access() -> None:
    skill_ok = (WEB_ACCESS_SKILL / "SKILL.md").is_file()
    add("宿主 web-access skill 已安装", skill_ok, str(WEB_ACCESS_SKILL),
        "在 WorkBuddy 中启用/安装 web-access skill")
    cfg = WEB_ACCESS_SKILL / "config.env"
    configured = False
    if cfg.is_file():
        for line in cfg.read_text(encoding="utf-8", errors="ignore").splitlines():
            line = line.strip()
            if line.startswith("WEB_ACCESS_BROWSER=") and line.split("=", 1)[1].strip():
                configured = True
    add("WEB_ACCESS_BROWSER 偏好已设置", configured,
        "已设置" if configured else "未设置（每次 check-deps 返回 exit 2）",
        "" if configured else
        "由员工确认浏览器后把 WEB_ACCESS_BROWSER=chrome（或 edge）写入 config.env；"
        "也可每次用 --browser chrome 临时覆盖")
    if platform.system() == "Darwin":
        chrome = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
        rc, out, _ = run([chrome, "--version"])
        ver = out.split()[-1] if out else ""
        major = int(ver.split(".")[0]) if ver.split(".")[0].isdigit() else 0
        add("Chrome >= 144（CDP 新流程）", major >= 144, ver or "未检测到",
            "升级 Chrome 到 144+" if major < 144 else "")
    try:
        with urllib.request.urlopen("http://127.0.0.1:9222/json/version", timeout=3) as r:
            code = r.status
    except Exception:
        code = 0
    add("Chrome 远程调试已授权", code == 200,
        f"HTTP {code}" if code else "端口不可达",
        "" if code == 200 else
        "Chrome 地址栏打开 chrome://inspect/#remote-debugging 启用"
        "「允许对此浏览器实例进行远程调试」，并在连接弹窗点「允许」；"
        "注意这不是一次性设置（每次连接/新会话都要确认）")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--profile", choices=("auto", "web-access", "browser-skill"),
                    default="auto")
    ap.add_argument("--root", default=str(DEFAULT_ROOT))
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)
    root = Path(args.root).expanduser().resolve()
    detected = detect_profile(root)
    profile = detected if args.profile == "auto" else args.profile
    if profile is None:
        profile = "browser-skill"   # recommended default for unattended runs

    probe_repo()
    probe_install(root, profile)
    probe_overlay_sync()
    probe_node()
    if profile == "browser-skill":
        probe_bsk_cli()
        add("web-access 专属前置", None,
            "本 profile 不需要（两套互斥，勿同时配置）")
    else:
        probe_web_access()
        add("browser-skill CLI / 扩展", None,
            "本 profile 不需要（两套互斥，勿同时配置）")

    pending = [r for r in results if r["status"] == "MISSING"]
    warns = [r for r in results if r["status"] == "WARN"]

    if args.json:
        print(json.dumps({"profile": profile, "detectedProfile": detected,
                          "root": str(root), "results": results,
                          "missing": len(pending), "warnings": len(warns)},
                         ensure_ascii=False, indent=2))
        return 1 if pending else 0

    suffix = "" if detected == profile else f"（已安装副本检测到 {detected or '未安装'}）"
    print(f"=== SMEDC · WorkBuddy 环境自检（profile: {profile}{suffix}）===")
    print(f"发现根: {root}\n")
    for r in results:
        mark = {"OK": "[  OK  ]", "WARN": "[ WARN ]", "MISSING": "[ MISS ]"}[r["status"]]
        print(f"{mark} {r['item']}: {r['detail']}")
    print()
    if pending:
        print(f"=== 还需要做（{len(pending)} 项，按下列顺序）===")
        for i, r in enumerate(pending, 1):
            print(f"{i}. {r['item']}\n   → {r['fix']}")
    else:
        print("=== 环境已就绪 ===")
    if warns:
        print(f"\n（{len(warns)} 条提示：多为非阻塞说明，见上方 WARN 行）")
    print("\n完整指引: workbuddy/GETTING_STARTED.md")
    return 1 if pending else 0


if __name__ == "__main__":
    raise SystemExit(main())
