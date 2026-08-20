#!/usr/bin/env python3
"""Manage the local persistent browser session for the XHS fallback.

This helper never accepts or prints passwords, OTPs, cookies, or storage state.
The user completes login manually in the visible browser once; Playwright then
reuses the ignored local browser profile on later runs.
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.parse
from pathlib import Path
from typing import Any


SKILL_ROOT = Path(__file__).resolve().parents[1]
PROFILE_DIR = SKILL_ROOT / "data" / "browser-profile"
DEFAULT_QUERY = "广州天河区宠物友好酒店"
XHS_EXPLORE_URL = "https://www.xiaohongshu.com/explore"
LOGIN_BLOCK_MARKERS = (
    "登录后查看搜索结果",
    "登录后推荐更懂你的笔记",
)
SECURITY_BLOCK_MARKERS = (
    "安全限制",
    "Account exception",
    "账号异常",
    "请重试",
)


def search_url(query: str) -> str:
    encoded = urllib.parse.quote(query, safe="")
    return f"https://www.xiaohongshu.com/search_result?keyword={encoded}&type=51"


def load_playwright() -> Any:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:  # pragma: no cover - environment dependent
        raise RuntimeError(
            "Playwright is not installed. Install the optional dependency with "
            "the xhs-creator-os environment and run `playwright install chromium`."
        ) from exc
    return sync_playwright


def page_text(page: Any) -> str:
    try:
        return page.locator("body").inner_text(timeout=10_000)
    except Exception:
        return ""


def page_state(page: Any, query: str) -> dict[str, Any]:
    body = page_text(page)
    blocked_markers = [marker for marker in LOGIN_BLOCK_MARKERS if marker in body]
    security_markers = [marker for marker in SECURITY_BLOCK_MARKERS if marker in body or marker in page.url]
    note_link_count = page.locator('a[href*="/explore/"]').count()
    if security_markers:
        status = "security_blocked"
    elif blocked_markers:
        status = "login_blocked"
    elif note_link_count:
        status = "search_results_visible"
    else:
        status = "search_results_not_visible"
    return {
        "status": status,
        "url": page.url,
        "title": page.title(),
        "query": query,
        "blocked_markers": blocked_markers,
        "security_markers": security_markers,
        "note_link_count": note_link_count,
        "profile_dir": str(PROFILE_DIR),
    }


def home_state(page: Any) -> dict[str, Any]:
    body = page_text(page)
    login_markers = [marker for marker in LOGIN_BLOCK_MARKERS if marker in body]
    security_markers = [marker for marker in SECURITY_BLOCK_MARKERS if marker in body or marker in page.url]
    try:
        login_button_count = page.get_by_role("button", name="登录", exact=True).count()
    except Exception:
        login_button_count = -1
    if security_markers:
        status = "security_blocked"
    elif login_markers or login_button_count > 0:
        status = "login_required"
    else:
        status = "authenticated"
    return {
        "status": status,
        "url": page.url,
        "title": page.title(),
        "login_markers": login_markers,
        "login_button_count": login_button_count,
        "security_markers": security_markers,
        "profile_dir": str(PROFILE_DIR),
    }


def current_xhs_page(context: Any) -> Any:
    """Use the latest XHS page; login can open a new tab/window."""
    pages = [page for page in context.pages if "xiaohongshu.com" in page.url]
    if pages:
        return pages[-1]
    return context.pages[-1] if context.pages else context.new_page()


def launch_context(playwright: Any, *, headed: bool) -> Any:
    PROFILE_DIR.mkdir(parents=True, exist_ok=True)
    return playwright.chromium.launch_persistent_context(
        str(PROFILE_DIR),
        headless=not headed,
        channel="chrome",
        viewport={"width": 1440, "height": 1000},
    )


def run_login(query: str) -> int:
    sync_playwright = load_playwright()
    with sync_playwright() as playwright:
        context = launch_context(playwright, headed=True)
        try:
            page = current_xhs_page(context)
            page.goto(XHS_EXPLORE_URL, wait_until="commit", timeout=60_000)
            print("请在打开的浏览器窗口中手动完成小红书登录。")
            input("登录完成后回到终端按回车继续检查：")
            page = current_xhs_page(context)
            page.goto(XHS_EXPLORE_URL, wait_until="commit", timeout=60_000)
            page.wait_for_timeout(5_000)
            home = home_state(page)
            print(json.dumps({"home": home, "open_pages": len(context.pages)}, ensure_ascii=False, indent=2))
        finally:
            context.close()
    return 0


def run_status(query: str, *, headed: bool) -> int:
    sync_playwright = load_playwright()
    with sync_playwright() as playwright:
        context = launch_context(playwright, headed=headed)
        try:
            page = current_xhs_page(context)
            page.goto(XHS_EXPLORE_URL, wait_until="commit", timeout=60_000)
            page.wait_for_timeout(5_000)
            home = home_state(page)
            print(json.dumps({"home": home, "open_pages": len(context.pages)}, ensure_ascii=False, indent=2))
            return 0 if home["status"] == "authenticated" else 1
        finally:
            context.close()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    login = sub.add_parser("login", help="open a visible browser for one-time manual login")
    login.add_argument("--query", default=DEFAULT_QUERY)

    status = sub.add_parser("status", help="check the persisted login state without exposing secrets")
    status.add_argument("--query", default=DEFAULT_QUERY)
    status.add_argument(
        "--headless",
        action="store_true",
        help="run without a visible window; some local Chrome builds reject this with persistent profiles",
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    try:
        if args.command == "login":
            return run_login(args.query)
        return run_status(args.query, headed=not args.headless)
    except Exception as exc:
        print(json.dumps({"status": "error", "message": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
