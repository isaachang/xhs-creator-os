#!/usr/bin/env python3
"""Manage the one local Chromium session owned by Creator OS MediaCrawler.

The service owns a separate, Git-ignored Profile and listens only on loopback.
It never reads, exports, or prints Cookie values.  Worker commands attach over
CDP and therefore do not launch a new Chrome window for every request.
"""

from __future__ import annotations

import argparse
import json
import os
import signal
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path


SKILL_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MEDIA_ROOT = SKILL_ROOT / "third_party" / "mediacrawler" / "runtime"
DEFAULT_PORT = 9233
BOOTSTRAP_PROFILE = "creator-os-bootstrap-profile"
LEGACY_PROFILE = "creator-os-chromium-profile"
PROFILE_PREFIX = "creator-os-"
PROFILE_SUFFIX = "-profile"
SITES = ("xiaohongshu", "rednote")


class SessionError(RuntimeError):
    pass


def media_root(value: str | None) -> Path:
    return Path(value).expanduser() if value else DEFAULT_MEDIA_ROOT


def chromium_path(root: Path) -> Path:
    """Use Playwright's isolated Chromium, never the user's Google Chrome by default."""
    configured = os.environ.get("CREATOR_OS_BROWSER_EXECUTABLE", "").strip()
    if configured:
        candidate = Path(configured).expanduser()
        if candidate.is_file():
            return candidate
        raise SessionError("CREATOR_OS_BROWSER_EXECUTABLE 指向的浏览器不存在。")

    python = root / ".venv" / "bin" / "python"
    result = subprocess.run(
        [
            str(python),
            "-c",
            "from playwright.sync_api import sync_playwright; p=sync_playwright().start(); print(p.chromium.executable_path); p.stop()",
        ],
        text=True,
        capture_output=True,
        check=False,
        timeout=20,
    )
    candidate = Path(result.stdout.strip())
    if result.returncode == 0 and candidate.is_file():
        return candidate
    raise SessionError("未找到 MediaCrawler 专属 Chromium；请先运行 setup_mediacrawler.py --install。")


def valid_profile_name(profile: str) -> bool:
    """Limit profile selection to Creator-OS-owned directories.

    The session service receives the profile name from the provider router. It
    must never attach to an arbitrary Chrome user-data directory supplied on a
    command line.
    """
    return (
        profile == BOOTSTRAP_PROFILE
        or profile == LEGACY_PROFILE
        or (
            profile.startswith(PROFILE_PREFIX)
            and profile.endswith(PROFILE_SUFFIX)
            and "/" not in profile
            and "\\" not in profile
            and ".." not in profile
        )
    )


def profile_path(root: Path, profile: str = BOOTSTRAP_PROFILE) -> Path:
    if not valid_profile_name(profile):
        raise SessionError("Media 专用 Profile 名称无效。")
    return root / "browser_data" / profile


def legacy_profile_path(root: Path) -> Path:
    """The pre-session-service Chrome profile, used only for safe one-time migration."""
    return root / "browser_data" / "cdp_xhs_user_data_dir"


def endpoint(port: int) -> str:
    return f"http://127.0.0.1:{port}/json/version"


def running(port: int) -> bool:
    try:
        with urllib.request.urlopen(endpoint(port), timeout=1.5) as response:
            return response.status == 200
    except (OSError, urllib.error.URLError):
        return False


def page_count(port: int) -> int | None:
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/json/list", timeout=1.5) as response:
            payload = json.loads(response.read().decode("utf-8"))
        # CDP also reports service workers and other non-tab targets.  Count
        # only actual browser pages so the status reflects visible tabs.
        return sum(1 for target in payload if isinstance(target, dict) and target.get("type") == "page") if isinstance(payload, list) else None
    except (OSError, UnicodeError, ValueError, urllib.error.URLError):
        return None


def normalize_pages(root: Path, port: int) -> dict[str, object]:
    """Keep one blank work page in the Creator-OS-owned browser only.

    This runs outside a crawler worker because login helpers can create tabs in
    a different browser context.  It reports counts only; URLs and cookies
    never leave the dedicated browser process.
    """
    python = root / ".venv" / "bin" / "python"
    script = """
import json
from playwright.sync_api import sync_playwright

p = sync_playwright().start()
try:
    browser = p.chromium.connect_over_cdp('http://127.0.0.1:%s')
    pages = [page for context in browser.contexts for page in context.pages if not page.is_closed()]
    if not pages:
        context = browser.contexts[0] if browser.contexts else browser.new_context()
        work_page = context.new_page()
    else:
        work_page = next((page for page in pages if page.url == 'about:blank'), pages[0])
        for page in pages:
            if page is not work_page:
                try:
                    page.close()
                except Exception:
                    pass
    try:
        work_page.goto('about:blank', wait_until='commit', timeout=5000)
    except Exception:
        pass
    remaining = sum(1 for context in browser.contexts for page in context.pages if not page.is_closed())
    print(json.dumps({'normalized': True, 'page_count': remaining}))
finally:
    p.stop()
""" % port
    try:
        result = subprocess.run(
            [str(python), "-c", script], text=True, capture_output=True, check=False, timeout=20
        )
        if result.returncode == 0:
            payload = json.loads(result.stdout.strip())
            if isinstance(payload, dict):
                return payload
    except (OSError, subprocess.TimeoutExpired, UnicodeError, ValueError, json.JSONDecodeError):
        pass
    return {"normalized": False, "page_count": page_count(port)}


def app_bundle(browser: Path) -> Path | None:
    for parent in browser.parents:
        if parent.suffix == ".app":
            return parent
    return None


def runtime_environment(root: Path) -> dict[str, str]:
    """Prepare a dedicated crash-dump path without changing the user keychain.

    Chromium encrypts Profile cookies through macOS keychain services.  Keep
    the caller's HOME unchanged so the existing dedicated login Profile remains
    readable; only the command-line crash dump directory is isolated.
    """
    runtime_home = root / "browser_data" / "creator-os-runtime-home"
    crash_dumps_dir = runtime_home / "crash-dumps"
    crash_dumps_dir.mkdir(parents=True, exist_ok=True)
    return os.environ.copy()


def launch_dedicated_browser(root: Path, browser: Path, args: list[str], log_file: object) -> None:
    """Start an isolated browser without making it the foreground application.

    On macOS, ``open -gj`` performs normal application registration while
    keeping the app hidden.  Starting an app bundle's executable directly and
    hiding it later is what previously caused intermittent AppKit crashes.
    """
    app = app_bundle(browser)
    env = runtime_environment(root)
    if sys.platform == "darwin" and app:
        command = ["/usr/bin/open", "-g", "-j", str(app), "--args", *args[1:]]
    else:
        command = args
    subprocess.Popen(
        command,
        stdin=subprocess.DEVNULL,
        stdout=log_file,
        stderr=log_file,
        start_new_session=True,
        env=env,
    )


def matching_browser_commands(root: Path, port: int) -> dict[int, str]:
    """Find only the main browser process owned by Creator OS on this port.

    macOS's ``ps`` can render non-ASCII directory names using an escaped form,
    so matching the absolute profile path is not reliable here.  The two
    profile basenames below are Creator-OS-specific, and excluding Chromium
    child processes keeps stop/restart scoped to the single browser root.
    """
    try:
        result = subprocess.run(["/bin/ps", "-axo", "pid=,command="], text=True, capture_output=True, check=False)
    except OSError:
        return {}
    port_arg = f"--remote-debugging-port={port}"
    commands: dict[int, str] = {}
    for line in result.stdout.splitlines():
        if (
            port_arg not in line
            or "--type=" in line
            or "browser_data" not in line
            or ("creator-os-" not in line and legacy_profile_path(root).name not in line)
        ):
            continue
        try:
            pid, command = line.strip().split(maxsplit=1)
            commands[int(pid)] = command
        except (IndexError, ValueError):
            continue
    return commands


def matching_browser_pids(root: Path, port: int) -> list[int]:
    return list(matching_browser_commands(root, port))


def stop(root: Path, port: int) -> dict[str, object]:
    pids = matching_browser_pids(root, port)
    for pid in pids:
        try:
            os.kill(pid, signal.SIGTERM)
        except ProcessLookupError:
            continue
    for _ in range(20):
        if not running(port):
            break
        time.sleep(0.25)
    return {"running": running(port), "stopped": not running(port), "pids": pids, "port": port}


def promote_profile(root: Path, port: int, profile_name: str, site: str) -> dict[str, object]:
    """Turn a verified bootstrap/legacy profile into a site-specific profile.

    Promotion never copies or exports cookies. It first stops only the
    Creator-OS-owned browser, then renames the whole local profile directory.
    Existing site profiles are never overwritten.
    """
    if site not in SITES:
        raise SessionError("Media 站点必须是 xiaohongshu 或 rednote。")
    source = profile_path(root, profile_name)
    target_name = f"creator-os-{site}-profile"
    target = profile_path(root, target_name)
    if source == target:
        return {"promoted": False, "profile": target_name, "site": site, "reason": "already_site_specific"}
    if not source.is_dir():
        raise SessionError("待迁移的 Media 专用 Profile 不存在。")
    if target.exists():
        raise SessionError(
            f"已存在 {site} 专用 Profile，当前临时登录态不会覆盖它。"
            f"请运行 media-auth --media-browser visible --site {site}，在该站点 Profile 内完成验证。"
        )
    stop(root, port)
    if running(port):
        raise SessionError("Media 专用浏览器尚未退出，未迁移 Profile。")
    source.rename(target)
    return {"promoted": True, "profile": target_name, "site": site}


def start(root: Path, port: int, profile_name: str = BOOTSTRAP_PROFILE) -> dict[str, object]:
    profile = profile_path(root, profile_name)
    if running(port):
        owned_pids = matching_browser_pids(root, port)
        if not owned_pids:
            raise SessionError(f"本机端口 {port} 已被其他浏览器占用；不会接管它。")
        commands = matching_browser_commands(root, port)
        if any(profile.name not in line for line in commands.values()):
            stop(root, port)
        else:
            normalized = normalize_pages(root, port)
            return {
                "running": True,
                "started": False,
                "port": port,
                "profile": profile.name,
                **normalized,
            }

    browser = chromium_path(root)
    profile.mkdir(parents=True, exist_ok=True)
    args = [
        str(browser),
        f"--remote-debugging-address=127.0.0.1",
        f"--remote-debugging-port={port}",
        f"--user-data-dir={profile}",
        "--no-first-run",
        "--no-default-browser-check",
        "--disable-background-timer-throttling",
        "--disable-backgrounding-occluded-windows",
        "--disable-renderer-backgrounding",
        "--disable-blink-features=AutomationControlled",
        "--exclude-switches=enable-automation",
        "--disable-infobars",
        f"--crash-dumps-dir={root / 'browser_data' / 'creator-os-runtime-home' / 'crash-dumps'}",
        "--window-position=-32000,-32000",
        "--window-size=1,1",
        "--force-device-scale-factor=1",
    ]
    with (root / "browser_data" / "creator-os-media-session.log").open("ab") as log_file:
        launch_dedicated_browser(root, browser, args, log_file)
    for _ in range(30):
        if running(port):
            normalized = normalize_pages(root, port)
            return {
                "running": True,
                "started": True,
                "port": port,
                "profile": profile.name,
                "pids": matching_browser_pids(root, port),
                **normalized,
                "launch_mode": "macos_hidden_app" if sys.platform == "darwin" and app_bundle(browser) else "direct_process",
            }
        time.sleep(0.5)
    raise SessionError("专用 Media 浏览器未能启动；请检查 browser_data/creator-os-media-session.log。")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("ensure", "status", "stop", "restart", "promote"))
    parser.add_argument("--media-root")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--profile", default=BOOTSTRAP_PROFILE, help="Creator OS-owned profile name")
    parser.add_argument("--site", choices=SITES, help="site used only when promoting a verified profile")
    args = parser.parse_args()
    root = media_root(args.media_root)
    try:
        if args.command == "ensure":
            result = start(root, args.port, args.profile)
        elif args.command == "stop":
            result = stop(root, args.port)
        elif args.command == "restart":
            stop(root, args.port)
            result = start(root, args.port, args.profile)
        elif args.command == "promote":
            if not args.site:
                raise SessionError("迁移 Profile 时必须指定 --site。")
            result = promote_profile(root, args.port, args.profile, args.site)
        else:
            result = {
                "running": running(args.port),
                "port": args.port,
                "profile": profile_path(root, args.profile).name,
                "page_count": page_count(args.port),
            }
        print(json.dumps(result, ensure_ascii=False))
        return 0
    except SessionError as exc:
        print(json.dumps({"status": "error", "message": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
