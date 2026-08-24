#!/usr/bin/env python3
"""Install or inspect the optional local MediaCrawler adapter for Creator OS.

The script intentionally never reads API keys or browser cookies.  ``--install``
is explicit because it downloads third-party code and Python/browser
dependencies. A successful install still requires the user to complete one
Xiaohongshu/Rednote QR login in the local window opened by ``xhs_provider.py media-auth``.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any


SKILL_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MEDIA_ROOT = SKILL_ROOT / "third_party" / "mediacrawler" / "runtime"
UPSTREAM_REPOSITORY = "https://github.com/NanmiCoder/MediaCrawler.git"
UPSTREAM_BASE_COMMIT = "d6f7c5bb906b6dac40ddf343ef9e26438a3de092"
ADAPTER_PATCH = SKILL_ROOT / "third_party" / "mediacrawler" / "creator-os-adapter.patch"
QR_WINDOW_PATCH = SKILL_ROOT / "third_party" / "mediacrawler" / "creator-os-qr-window.patch"
LOGIN_STABILITY_PATCH = SKILL_ROOT / "third_party" / "mediacrawler" / "creator-os-login-stability.patch"
BACKGROUND_MODE_PATCH = SKILL_ROOT / "third_party" / "mediacrawler" / "creator-os-background-mode.patch"
BROWSER_SESSION_FALLBACK_PATCH = SKILL_ROOT / "third_party" / "mediacrawler" / "creator-os-browser-session-fallback.patch"
OFFSCREEN_BACKGROUND_PATCH = SKILL_ROOT / "third_party" / "mediacrawler" / "creator-os-offscreen-background.patch"
NONINTERACTIVE_LOGIN_PATCH = SKILL_ROOT / "third_party" / "mediacrawler" / "creator-os-noninteractive-login.patch"
INTERACTIVE_AUTH_PATCH = SKILL_ROOT / "third_party" / "mediacrawler" / "creator-os-interactive-auth.patch"
LOGIN_UI_GUARD_PATCH = SKILL_ROOT / "third_party" / "mediacrawler" / "creator-os-login-ui-guard.patch"
SHARED_SESSION_PATCH = SKILL_ROOT / "third_party" / "mediacrawler" / "creator-os-shared-session.patch"
DEDICATED_SESSION_PATCH = SKILL_ROOT / "third_party" / "mediacrawler" / "creator-os-dedicated-session.patch"
SITE_PROFILE_PATCH = SKILL_ROOT / "third_party" / "mediacrawler" / "creator-os-site-profile.patch"
CDP_FAIL_CLOSED_PATCH = SKILL_ROOT / "third_party" / "mediacrawler" / "creator-os-cdp-fail-closed.patch"
CORE_ADAPTER_FILES = (
    "media_platform/xhs/creator_os_output.py",
    "media_platform/xhs/site.py",
)
REQUIRED_ADAPTER_FILES = (*CORE_ADAPTER_FILES, "tools/creator_os_qr_window.py")


class SetupError(RuntimeError):
    pass


def configured_media_root(value: str | None) -> Path:
    raw = (value or os.environ.get("MEDIA_CRAWLER_ROOT", "")).strip()
    return (Path(raw).expanduser() if raw else DEFAULT_MEDIA_ROOT).resolve()


def media_python(root: Path) -> Path:
    return root / ".venv" / "bin" / "python"


def chromium_ready(root: Path) -> bool:
    """Check the Playwright-managed Chromium binary without launching it."""
    python = media_python(root)
    if not python.is_file():
        return False
    script = (
        "from pathlib import Path; "
        "from playwright.sync_api import sync_playwright; "
        "p=sync_playwright().start(); "
        "print(Path(p.chromium.executable_path).is_file()); "
        "p.stop()"
    )
    try:
        result = subprocess.run(
            [str(python), "-c", script], text=True, capture_output=True, check=False, timeout=20
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return result.returncode == 0 and result.stdout.strip() == "True"


def runtime_ready(root: Path) -> bool:
    return (root / "main.py").is_file() and media_python(root).is_file() and adapter_ready(root) and chromium_ready(root)


def adapter_ready(root: Path) -> bool:
    return (
        all((root / relative).is_file() for relative in REQUIRED_ADAPTER_FILES)
        and login_stability_ready(root)
        and background_mode_ready(root)
        and browser_session_fallback_ready(root)
        and offscreen_background_ready(root)
        and noninteractive_login_ready(root)
        and interactive_auth_ready(root)
        and login_ui_guard_ready(root)
        and shared_session_ready(root)
        and dedicated_session_ready(root)
        and site_profile_ready(root)
        and cdp_fail_closed_ready(root)
    )


def core_adapter_ready(root: Path) -> bool:
    return all((root / relative).is_file() for relative in CORE_ADAPTER_FILES)


def shared_session_ready(root: Path) -> bool:
    """Recognize the dedicated-CDP attachment contract without reading session data."""
    try:
        config_text = (root / "config" / "base_config.py").read_text(encoding="utf-8")
        cdp_text = (root / "tools" / "cdp_browser.py").read_text(encoding="utf-8")
        login_text = (root / "media_platform" / "xhs" / "login.py").read_text(encoding="utf-8")
    except OSError:
        return False
    return (
        "CREATOR_OS_CDP_CONNECT_EXISTING" in config_text
        and "Released Creator OS shared browser connection" in cdp_text
        and "QR completion and cookie change" not in login_text
    )


def dedicated_session_ready(root: Path) -> bool:
    """Confirm the no-tab-growth and isolated-profile contract is installed."""
    try:
        config_text = (root / "config" / "base_config.py").read_text(encoding="utf-8")
        cdp_text = (root / "tools" / "cdp_browser.py").read_text(encoding="utf-8")
        core_text = (root / "media_platform" / "xhs" / "core.py").read_text(encoding="utf-8")
    except OSError:
        return False
    return (
        "CREATOR_OS_SHARED_BROWSER" in config_text
        and "if config.CREATOR_OS_SHARED_BROWSER:" in cdp_text
        and "def _creator_os_work_page" in core_text
        and "CREATOR_OS_PROFILE_DIR" in core_text
    )


def site_profile_ready(root: Path) -> bool:
    """Visible auth should not show a QR again when the dedicated page is logged in."""
    try:
        core_text = (root / "media_platform" / "xhs" / "core.py").read_text(encoding="utf-8")
    except OSError:
        return False
    return "interactive_auth and not page_session_confirmed" in core_text


def cdp_fail_closed_ready(root: Path) -> bool:
    """Require shared sessions to use the complete CDP URL and never fall back."""
    try:
        cdp_text = (root / "tools" / "cdp_browser.py").read_text(encoding="utf-8")
        core_text = (root / "media_platform" / "xhs" / "core.py").read_text(encoding="utf-8")
    except OSError:
        return False
    return (
        "Connecting to Creator OS shared browser via CDP" in cdp_text
        and "standard-browser fallback is disabled" in core_text
    )


def login_ui_guard_ready(root: Path) -> bool:
    try:
        core_text = (root / "media_platform" / "xhs" / "core.py").read_text(encoding="utf-8")
        login_text = (root / "media_platform" / "xhs" / "login.py").read_text(encoding="utf-8")
    except OSError:
        return False
    return "data-logged='1'" in core_text and "data-logged='1'" in login_text


def login_stability_ready(root: Path) -> bool:
    """Recognize the Creator OS login guard without reading any session data."""
    try:
        client_text = (root / "media_platform" / "xhs" / "client.py").read_text(encoding="utf-8")
        core_text = (root / "media_platform" / "xhs" / "core.py").read_text(encoding="utf-8")
    except OSError:
        return False
    return "class LoginProbe" in client_text and "def _persistent_profile_dir" in core_text


def background_mode_ready(root: Path) -> bool:
    try:
        core_text = (root / "media_platform" / "xhs" / "core.py").read_text(encoding="utf-8")
    except OSError:
        return False
    return "CREATOR_OS_BACKGROUND_MODE" in core_text and "CREATOR_OS_BROWSER_EXECUTABLE" in core_text


def browser_session_fallback_ready(root: Path) -> bool:
    try:
        core_text = (root / "media_platform" / "xhs" / "core.py").read_text(encoding="utf-8")
    except OSError:
        return False
    return "def _browser_session_confirmed" in core_text


def offscreen_background_ready(root: Path) -> bool:
    try:
        core_text = (root / "media_platform" / "xhs" / "core.py").read_text(encoding="utf-8")
        launcher_text = (root / "tools" / "browser_launcher.py").read_text(encoding="utf-8")
    except OSError:
        return False
    return "Creator OS off-screen background" in core_text and "creator_os_offscreen" in launcher_text


def noninteractive_login_ready(root: Path) -> bool:
    try:
        core_text = (root / "media_platform" / "xhs" / "core.py").read_text(encoding="utf-8")
    except OSError:
        return False
    return "后台调研不会自动弹出二维码" in core_text and "continuing without QR" in core_text


def interactive_auth_ready(root: Path) -> bool:
    try:
        core_text = (root / "media_platform" / "xhs" / "core.py").read_text(encoding="utf-8")
        login_text = (root / "media_platform" / "xhs" / "login.py").read_text(encoding="utf-8")
    except OSError:
        return False
    return "CREATOR_OS_INTERACTIVE_AUTH" in core_text and "login_confirmed" in login_text


def run(command: list[str], *, cwd: Path | None = None) -> None:
    result = subprocess.run(command, cwd=cwd, text=True, check=False)
    if result.returncode:
        joined = " ".join(command[:3])
        raise SetupError(f"命令执行失败：{joined}")


def git_head(root: Path) -> str:
    if not root.is_dir():
        return ""
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=root, text=True, capture_output=True, check=False
    )
    return result.stdout.strip() if result.returncode == 0 else ""


def check(root: Path) -> dict[str, Any]:
    bootstrap_python = compatible_python()
    node_ready = shutil.which("node") is not None
    return {
        "skill_root": str(SKILL_ROOT),
        "media_root": str(root),
        "python": {
            "host_version": sys.version.split()[0],
            "bootstrap": bootstrap_python or "",
            "supported": bool(bootstrap_python),
            "note": "首次安装使用 Python 3.11 或 3.12；已有运行环境保持不变",
        },
        "git": {"installed": shutil.which("git") is not None},
        "node": {"installed": node_ready, "note": "MediaCrawler 的 XHS 运行环境建议 Node.js 16+"},
        "media": {
            "source_present": (root / "main.py").is_file(),
            "environment_present": media_python(root).is_file(),
            "browser_present": chromium_ready(root),
            "creator_os_adapter_present": adapter_ready(root),
            "git_head": git_head(root),
        },
        "next_action": (
            "运行 setup_mediacrawler.py --install；完成后由 Codex 先执行后台 media-auth，"
            "如未确认登录再执行 media-auth --media-browser visible。"
            if not runtime_ready(root)
            else "Media 已就绪；先运行 xhs_provider.py media-auth --media-browser background 检查登录态。"
        ),
    }


def compatible_python() -> str | None:
    """Return a compatible installed interpreter without changing the system."""
    for name in ("python3.12", "python3.11"):
        candidate = shutil.which(name)
        if candidate:
            return candidate
    if sys.version_info[:2] in {(3, 11), (3, 12)}:
        return sys.executable
    return None


def ensure_python() -> str:
    """Return an interpreter compatible with the pinned upstream requirements.

    MediaCrawler's pinned dependencies are validated on Python 3.11/3.12.
    Prefer an explicitly installed compatible interpreter instead of creating a
    new environment from a newer system Python that may lack compatible wheels.
    """
    if not shutil.which("git"):
        raise SetupError("未找到 git；请先安装 Git 后重试。")
    candidate = compatible_python()
    if candidate:
        return candidate
    raise SetupError(
        "MediaCrawler 首次安装需要 Python 3.11 或 3.12；当前未找到兼容解释器。"
        "请安装 Python 3.12 后重试。"
    )


def clone_if_missing(root: Path) -> None:
    if root.exists():
        if not (root / "main.py").is_file():
            raise SetupError(f"MediaCrawler 路径已存在但不是有效目录：{root}")
        return
    root.parent.mkdir(parents=True, exist_ok=True)
    run(["git", "clone", UPSTREAM_REPOSITORY, str(root)])
    run(["git", "checkout", UPSTREAM_BASE_COMMIT], cwd=root)


def apply_adapter(root: Path) -> None:
    if not core_adapter_ready(root):
        if git_head(root) != UPSTREAM_BASE_COMMIT:
            raise SetupError(
                "当前 MediaCrawler 版本与首测适配补丁不匹配。请使用初始化脚本新建目录，"
                "或将 MEDIA_CRAWLER_ROOT 指向一个干净的兼容副本。"
            )
        if not ADAPTER_PATCH.is_file():
            raise SetupError("缺少 MediaCrawler 核心适配补丁；请重新下载完整 Creator OS 仓库。")
        run(["git", "apply", "--check", str(ADAPTER_PATCH)], cwd=root)
        run(["git", "apply", str(ADAPTER_PATCH)], cwd=root)
    if not (root / "tools/creator_os_qr_window.py").is_file():
        if not QR_WINDOW_PATCH.is_file():
            raise SetupError("缺少 MediaCrawler 登录窗口适配补丁；请重新下载完整 Creator OS 仓库。")
        run(["git", "apply", "--check", str(QR_WINDOW_PATCH)], cwd=root)
        run(["git", "apply", str(QR_WINDOW_PATCH)], cwd=root)
    if not login_stability_ready(root):
        if not LOGIN_STABILITY_PATCH.is_file():
            raise SetupError("缺少 MediaCrawler 登录稳定性补丁；请重新下载完整 Creator OS 仓库。")
        run(["git", "apply", "--check", "--recount", str(LOGIN_STABILITY_PATCH)], cwd=root)
        run(["git", "apply", "--recount", str(LOGIN_STABILITY_PATCH)], cwd=root)
    if not background_mode_ready(root):
        if not BACKGROUND_MODE_PATCH.is_file():
            raise SetupError("缺少 MediaCrawler 后台运行补丁；请重新下载完整 Creator OS 仓库。")
        run(["git", "apply", "--check", "--recount", str(BACKGROUND_MODE_PATCH)], cwd=root)
        run(["git", "apply", "--recount", str(BACKGROUND_MODE_PATCH)], cwd=root)
    if not browser_session_fallback_ready(root):
        if not BROWSER_SESSION_FALLBACK_PATCH.is_file():
            raise SetupError("缺少 MediaCrawler 会话确认补丁；请重新下载完整 Creator OS 仓库。")
        run(["git", "apply", "--check", "--recount", str(BROWSER_SESSION_FALLBACK_PATCH)], cwd=root)
        run(["git", "apply", "--recount", str(BROWSER_SESSION_FALLBACK_PATCH)], cwd=root)
    if not offscreen_background_ready(root):
        if not OFFSCREEN_BACKGROUND_PATCH.is_file():
            raise SetupError("缺少 MediaCrawler 离屏后台补丁；请重新下载完整 Creator OS 仓库。")
        run(["git", "apply", "--check", "--recount", str(OFFSCREEN_BACKGROUND_PATCH)], cwd=root)
        run(["git", "apply", "--recount", str(OFFSCREEN_BACKGROUND_PATCH)], cwd=root)
    if not noninteractive_login_ready(root):
        if not NONINTERACTIVE_LOGIN_PATCH.is_file():
            raise SetupError("缺少 MediaCrawler 后台登录策略补丁；请重新下载完整 Creator OS 仓库。")
        run(["git", "apply", "--check", "--recount", str(NONINTERACTIVE_LOGIN_PATCH)], cwd=root)
        run(["git", "apply", "--recount", str(NONINTERACTIVE_LOGIN_PATCH)], cwd=root)
    if not interactive_auth_ready(root):
        if not INTERACTIVE_AUTH_PATCH.is_file():
            raise SetupError("缺少 MediaCrawler 可见登录补丁；请重新下载完整 Creator OS 仓库。")
        run(["git", "apply", "--check", "--recount", str(INTERACTIVE_AUTH_PATCH)], cwd=root)
        run(["git", "apply", "--recount", str(INTERACTIVE_AUTH_PATCH)], cwd=root)
    if not login_ui_guard_ready(root):
        if not LOGIN_UI_GUARD_PATCH.is_file():
            raise SetupError("缺少 MediaCrawler 登录 UI 判定补丁；请重新下载完整 Creator OS 仓库。")
        run(["git", "apply", "--check", "--recount", str(LOGIN_UI_GUARD_PATCH)], cwd=root)
        run(["git", "apply", "--recount", str(LOGIN_UI_GUARD_PATCH)], cwd=root)
    if not shared_session_ready(root):
        if not SHARED_SESSION_PATCH.is_file():
            raise SetupError("缺少 MediaCrawler 专用会话补丁；请重新下载完整 Creator OS 仓库。")
        run(["git", "apply", "--check", "--recount", str(SHARED_SESSION_PATCH)], cwd=root)
        run(["git", "apply", "--recount", str(SHARED_SESSION_PATCH)], cwd=root)
    if not dedicated_session_ready(root):
        if not DEDICATED_SESSION_PATCH.is_file():
            raise SetupError("缺少 MediaCrawler 独立后台会话补丁；请重新下载完整 Creator OS 仓库。")
        run(["git", "apply", "--check", "--recount", str(DEDICATED_SESSION_PATCH)], cwd=root)
        run(["git", "apply", "--recount", str(DEDICATED_SESSION_PATCH)], cwd=root)
    if not site_profile_ready(root):
        if not SITE_PROFILE_PATCH.is_file():
            raise SetupError("缺少 Media 站点 Profile 隔离补丁；请重新下载完整 Creator OS 仓库。")
        run(["git", "apply", "--check", "--recount", str(SITE_PROFILE_PATCH)], cwd=root)
        run(["git", "apply", "--recount", str(SITE_PROFILE_PATCH)], cwd=root)
    if not cdp_fail_closed_ready(root):
        if not CDP_FAIL_CLOSED_PATCH.is_file():
            raise SetupError("缺少 Media 专用 CDP 稳定性补丁；请重新下载完整 Creator OS 仓库。")
        run(["git", "apply", "--check", "--recount", str(CDP_FAIL_CLOSED_PATCH)], cwd=root)
        run(["git", "apply", "--recount", str(CDP_FAIL_CLOSED_PATCH)], cwd=root)


def install_environment(root: Path, bootstrap_python: str) -> None:
    executable = media_python(root)
    if not executable.is_file():
        run([bootstrap_python, "-m", "venv", ".venv"], cwd=root)
    pip_check = subprocess.run(
        [str(executable), "-m", "pip", "--version"], text=True, capture_output=True, check=False
    )
    if pip_check.returncode:
        run([str(executable), "-m", "ensurepip", "--upgrade"], cwd=root)
    requirements = root / "requirements.txt"
    if not requirements.is_file():
        raise SetupError("MediaCrawler 缺少 requirements.txt，无法安装 Python 依赖")
    run([str(executable), "-m", "pip", "install", "-r", "requirements.txt"], cwd=root)
    run([str(executable), "-m", "playwright", "install", "chromium"], cwd=root)
    if not chromium_ready(root):
        raise SetupError("Playwright Chromium 安装后仍不可用；请检查网络或浏览器缓存目录权限。")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="只输出当前配置状态，不下载或修改文件")
    parser.add_argument("--install", action="store_true", help="下载上游 MediaCrawler、应用适配补丁并安装本机依赖")
    parser.add_argument("--media-root", help="可选：MediaCrawler 目录；默认 third_party/mediacrawler/runtime")
    args = parser.parse_args()
    root = configured_media_root(args.media_root)

    try:
        if args.check or not args.install:
            print(json.dumps(check(root), ensure_ascii=False, indent=2))
            return 0

        bootstrap_python = ensure_python()
        clone_if_missing(root)
        apply_adapter(root)
        install_environment(root, bootstrap_python)
        print(json.dumps(check(root), ensure_ascii=False, indent=2))
        print("\n下一步：先运行 python3 scripts/xhs_provider.py media-auth --media-browser background；"
              "如未确认登录，再运行同一命令并加 --media-browser visible。")
        return 0
    except SetupError as exc:
        print(json.dumps({"status": "error", "message": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
