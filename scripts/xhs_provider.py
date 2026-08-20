#!/usr/bin/env python3
"""Route Creator OS public XHS reads to Apify or the local Media adapter.

``auto`` means Apify when a usable key is configured; otherwise the local
MediaCrawler adapter. It never silently falls through from a configured-but-
failed Apify request to a browser session, because that would change both the
data source and the user-visible risk profile without consent.
"""

from __future__ import annotations

import argparse
import contextlib
import fcntl
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import xhs_api
from store import DEFAULT_DB, connect, import_research


SKILL_ROOT = Path(__file__).resolve().parents[1]
WORKSPACE_ROOT = SKILL_ROOT.parent
DEFAULT_MEDIA_ROOT = WORKSPACE_ROOT / "MediaCrawler"
CONTENT_TYPES = ("image", "video", "all")
SOURCES = ("auto", "apify", "media")
MEDIA_BROWSER_MODES = ("background", "visible")


class ProviderRouterError(RuntimeError):
    pass


def media_root() -> Path:
    configured = os.environ.get("MEDIA_CRAWLER_ROOT", "").strip() or xhs_api.local_env_secret("MEDIA_CRAWLER_ROOT")
    return Path(configured).expanduser() if configured else DEFAULT_MEDIA_ROOT


def media_python(root: Path) -> Path:
    return root / ".venv" / "bin" / "python"


def media_adapter_present(root: Path) -> bool:
    """Require the local adapter contract, not merely an arbitrary upstream clone."""
    return all(
        (root / relative).is_file()
        for relative in (
            "media_platform/xhs/creator_os_output.py",
            "media_platform/xhs/site.py",
        )
    )


def media_installed(root: Path | None = None) -> bool:
    root = root or media_root()
    return (root / "main.py").is_file() and media_python(root).is_file() and media_adapter_present(root)


def resolve_source(requested: str) -> str:
    if requested not in SOURCES:
        raise ProviderRouterError(f"unsupported source: {requested}")
    if requested == "apify":
        if not xhs_api.apify_token():
            raise ProviderRouterError("Apify 未配置；请先配置 API Key，或显式使用 --source media")
        return "apify"
    if requested == "media":
        if not media_installed():
            raise ProviderRouterError("本机 MediaCrawler 未安装或 Python 环境不可用")
        return "media"
    if xhs_api.apify_token():
        return "apify"
    if media_installed():
        return "media"
    raise ProviderRouterError("未配置 Apify，且本机 MediaCrawler 不可用")


def load_records(path: Path) -> list[dict[str, Any]]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ProviderRouterError(f"无法读取抓取输出：{exc}") from exc
    if not isinstance(payload, list):
        raise ProviderRouterError("抓取输出不是标准 JSON 数组")
    return [item for item in payload if isinstance(item, dict)]


def manifest_path(output: Path) -> Path:
    return output.with_name(f"{output.stem}.manifest{output.suffix or '.json'}")


def write_records(records: list[dict[str, Any]], output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(records, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def write_manifest(output: Path, metadata: dict[str, Any]) -> None:
    path = manifest_path(output)
    path.write_text(json.dumps(metadata, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def import_research_records(records: list[dict[str, Any]]) -> None:
    with connect(DEFAULT_DB) as conn:
        for record in records:
            import_research(
                conn,
                record,
                str(record.get("source") or "unknown"),
                str(record.get("query") or "") or None,
                None,
            )
        conn.commit()


@contextlib.contextmanager
def media_session_lock(root: Path):
    """Prevent overlapping runs from opening the same persistent browser profile."""
    lock_path = root / "browser_data" / ".creator-os-session.lock"
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open("a+") as lock_file:
        try:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise ProviderRouterError("本机 MediaCrawler 正在运行；请等待当前抓取或登录完成，不要重复启动") from exc
        try:
            yield
        finally:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)


def run_media(command: list[str], *, root: Path, extra_env: dict[str, str] | None = None, timeout: int = 300) -> None:
    env = os.environ.copy()
    if extra_env:
        env.update(extra_env)
    with media_session_lock(root):
        result = subprocess.run(
            [str(media_python(root)), "main.py", *command],
            cwd=root,
            text=True,
            capture_output=True,
            timeout=timeout,
            check=False,
            env=env,
        )
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "MediaCrawler failed").strip().replace("\n", " ")[:600]
        raise ProviderRouterError(f"MediaCrawler 请求失败：{detail}")


def media_browser_args(args: argparse.Namespace) -> list[str]:
    return ["--headless", "yes" if args.media_browser == "background" else "no"]


def apify_args(args: argparse.Namespace) -> argparse.Namespace:
    return argparse.Namespace(
        keyword=args.keyword,
        sort_type={"general": "general", "popular": "like_count_descending", "latest": "time_descending"}[args.sort_type],
        note_type={"all": 0, "video": 1, "image": 2}[args.content_type],
        days=args.days,
        limit=args.limit,
        timeout=args.timeout,
        poll_attempts=args.poll_attempts,
        poll_interval=args.poll_interval,
        source="apify",
    )


def search_apify(args: argparse.Namespace) -> dict[str, Any]:
    records = xhs_api.apify_search(apify_args(args))
    write_records(records, args.output)
    import_research_records(records)
    metadata = {
        "provider": "apify",
        "data_source": "Apify → SocialDataX",
        "operation": "research",
        "query": args.keyword,
        "sort_type": args.sort_type,
        "note_type": args.content_type,
        "publish_days": args.days,
        "requested_limit": args.limit,
        "returned_count": len(records),
    }
    write_manifest(args.output, metadata)
    return {"provider": "apify", "stage": "final", "output": str(args.output), "records": len(records)}


def search_media(args: argparse.Namespace) -> dict[str, Any]:
    root = media_root()
    candidates = args.output.with_name(f"{args.output.stem}.candidates{args.output.suffix or '.json'}")
    command = [
        "--platform", "xhs",
        "--type", "search",
        "--keywords", args.keyword,
        "--sort_type", {"general": "general", "popular": "popularity_descending", "latest": "time_descending"}[args.sort_type],
        "--note_type", args.content_type,
        "--crawler_max_notes_count", str(args.limit),
        "--research_screening", "yes",
        "--research_candidate_count", str(max(30, args.limit)),
        "--fetch_details", "no",
        "--get_comment", "no",
        "--creator_os_output", str(candidates),
        *media_browser_args(args),
    ]
    run_media(command, root=root)
    candidate_records = load_records(candidates)
    try:
        metadata = json.loads(manifest_path(candidates).read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        metadata = {}
    metadata.update(
        {
            "provider": "media",
            "data_source": "本机 MediaCrawler",
            "operation": "research_candidates",
            "query": args.keyword,
            "sort_type": args.sort_type,
            "note_type": args.content_type,
            "publish_days": args.days,
            "requested_limit": args.limit,
            "candidate_count": len(candidate_records),
            "next_step": "Agent 动态筛选候选、读取选中详情，再生成正式 research.json",
        }
    )
    write_manifest(candidates, metadata)
    return {
        "provider": "media",
        "stage": "candidates",
        "candidates": str(candidates),
        "records": len(candidate_records),
        "next_step": metadata["next_step"],
    }


def detail_apify(args: argparse.Namespace) -> dict[str, Any]:
    records = xhs_api.apify_detail(
        argparse.Namespace(url=args.url, refresh=args.refresh, timeout=args.timeout, poll_attempts=args.poll_attempts, poll_interval=args.poll_interval)
    )
    write_records(records, args.output)
    write_manifest(
        args.output,
        {"provider": "apify", "data_source": "Apify → SocialDataX", "operation": "detail", "returned_count": len(records)},
    )
    return {"provider": "apify", "stage": "detail", "output": str(args.output), "records": len(records)}


def detail_media(args: argparse.Namespace) -> dict[str, Any]:
    root = media_root()
    note_url = args.url
    if xhs_api.is_xhslink_url(note_url):
        note_url = xhs_api.resolve_xhslink_url(note_url, timeout=min(args.timeout, 30))
    run_media(
        [
            "--platform", "xhs",
            "--type", "detail",
            "--specified_id", note_url,
            "--get_comment", "no",
            "--creator_os_output", str(args.output),
            *media_browser_args(args),
        ],
        root=root,
    )
    records = load_records(args.output)
    if not records:
        raise ProviderRouterError("MediaCrawler 未返回该笔记详情")
    xhs_api.write_note_detail_cache(records, args.url, note_url)
    try:
        metadata = json.loads(manifest_path(args.output).read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        metadata = {}
    metadata.update({"provider": "media", "data_source": "本机 MediaCrawler", "operation": "detail", "returned_count": len(records)})
    write_manifest(args.output, metadata)
    return {"provider": "media", "stage": "detail", "output": str(args.output), "records": len(records)}


def details_apify(args: argparse.Namespace) -> dict[str, Any]:
    records: list[dict[str, Any]] = []
    seen: set[str] = set()
    for url in args.urls:
        detail_args = argparse.Namespace(
            url=url,
            refresh=args.refresh,
            timeout=args.timeout,
            poll_attempts=args.poll_attempts,
            poll_interval=args.poll_interval,
        )
        for record in xhs_api.apify_detail(detail_args):
            key = str(record.get("note_id") or record.get("url") or "")
            if key and key not in seen:
                records.append(record)
                seen.add(key)
    write_records(records, args.output)
    write_manifest(
        args.output,
        {"provider": "apify", "data_source": "Apify → SocialDataX", "operation": "details", "returned_count": len(records)},
    )
    return {"provider": "apify", "stage": "details", "output": str(args.output), "records": len(records)}


def details_media(args: argparse.Namespace) -> dict[str, Any]:
    root = media_root()
    urls = [
        xhs_api.resolve_xhslink_url(url, timeout=min(args.timeout, 30)) if xhs_api.is_xhslink_url(url) else url
        for url in args.urls
    ]
    run_media(
        [
            "--platform", "xhs",
            "--type", "detail",
            "--specified_id", ",".join(urls),
            "--get_comment", "no",
            "--creator_os_output", str(args.output),
            *media_browser_args(args),
        ],
        root=root,
    )
    records = load_records(args.output)
    if not records:
        raise ProviderRouterError("MediaCrawler 未返回所选笔记详情")
    xhs_api.write_note_detail_cache(records, *args.urls, *urls)
    try:
        metadata = json.loads(manifest_path(args.output).read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        metadata = {}
    metadata.update({"provider": "media", "data_source": "本机 MediaCrawler", "operation": "details", "returned_count": len(records)})
    write_manifest(args.output, metadata)
    return {"provider": "media", "stage": "details", "output": str(args.output), "records": len(records)}


def creator_media(args: argparse.Namespace) -> dict[str, Any]:
    root = media_root()
    run_media(
        [
            "--platform", "xhs",
            "--type", "creator_top",
            "--creator_id", args.creator_url,
            "--crawler_max_notes_count", str(args.scan_limit),
            "--creator_top_limit", str(args.top),
            "--get_comment", "no",
            "--creator_os_output", str(args.output),
            *media_browser_args(args),
        ],
        root=root,
        timeout=max(300, args.scan_limit * 4),
    )
    records = load_records(args.output)
    if not records:
        raise ProviderRouterError("MediaCrawler 未返回该作者的笔记")
    import_research_records(records)
    try:
        metadata = json.loads(manifest_path(args.output).read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        metadata = {}
    metadata.update({
        "provider": "media",
        "data_source": "本机 MediaCrawler",
        "operation": "creator_top",
        "requested_top": args.top,
        "scan_limit": args.scan_limit,
        "returned_count": len(records),
    })
    write_manifest(args.output, metadata)
    return {"provider": "media", "stage": "creator_top", "output": str(args.output), "records": len(records)}


def media_auth(args: argparse.Namespace) -> dict[str, Any]:
    root = media_root()
    qr_output = args.qr_output.expanduser().resolve()
    qr_output.parent.mkdir(parents=True, exist_ok=True)
    run_media(
        ["--platform", "xhs", "--type", "session", *media_browser_args(args)],
        root=root,
        extra_env={"CREATOR_OS_QR_OUTPUT_PATH": str(qr_output)},
        timeout=args.timeout,
    )
    return {
        "provider": "media",
        "authenticated": True,
        "browser": args.media_browser,
        "qrcode_generated": qr_output.is_file(),
        "qrcode": str(qr_output) if qr_output.is_file() else None,
    }


def status() -> dict[str, Any]:
    root = media_root()
    apify_configured = bool(xhs_api.apify_token())
    media_available = media_installed(root)
    selected = "apify" if apify_configured else "media" if media_available else None
    return {
        "selected_source": selected,
        "apify": {"configured": apify_configured, "actor": xhs_api.apify_actor_id()},
        "media": {
            "installed": media_available,
            "adapter_present": media_adapter_present(root),
            "root": str(root),
            "login_check": "performed only when MediaCrawler starts; no cookie values are read or displayed",
        },
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("status", help="show selected provider without displaying secrets")

    search = sub.add_parser("search", help="route keyword research")
    search.add_argument("keyword")
    search.add_argument("--source", choices=SOURCES, default="auto")
    search.add_argument("--limit", type=int, default=15)
    search.add_argument("--sort-type", choices=("general", "popular", "latest"), default="general")
    search.add_argument("--content-type", choices=CONTENT_TYPES, default="image")
    search.add_argument("--days", type=int, default=3650)
    search.add_argument("--timeout", type=int, default=180)
    search.add_argument("--poll-attempts", type=int, default=60)
    search.add_argument("--poll-interval", type=float, default=2.0)
    search.add_argument("--media-browser", choices=MEDIA_BROWSER_MODES, default="background")
    search.add_argument("--output", type=Path, required=True)

    detail = sub.add_parser("detail", help="route one public note detail request")
    detail.add_argument("url")
    detail.add_argument("--source", choices=SOURCES, default="auto")
    detail.add_argument("--refresh", action="store_true")
    detail.add_argument("--timeout", type=int, default=180)
    detail.add_argument("--poll-attempts", type=int, default=60)
    detail.add_argument("--poll-interval", type=float, default=2.0)
    detail.add_argument("--media-browser", choices=MEDIA_BROWSER_MODES, default="background")
    detail.add_argument("--output", type=Path, required=True)

    details = sub.add_parser("details", help="route a selected batch of public note detail requests")
    details.add_argument("urls", nargs="+")
    details.add_argument("--source", choices=SOURCES, default="auto")
    details.add_argument("--refresh", action="store_true")
    details.add_argument("--timeout", type=int, default=180)
    details.add_argument("--poll-attempts", type=int, default=60)
    details.add_argument("--poll-interval", type=float, default=2.0)
    details.add_argument("--media-browser", choices=MEDIA_BROWSER_MODES, default="background")
    details.add_argument("--output", type=Path, required=True)

    creator = sub.add_parser("creator", help="read one public author feed through local MediaCrawler")
    creator.add_argument("creator_url")
    creator.add_argument("--top", type=int, default=5)
    creator.add_argument("--scan-limit", type=int, default=120)
    creator.add_argument("--media-browser", choices=MEDIA_BROWSER_MODES, default="background")
    creator.add_argument("--output", type=Path, required=True)

    auth = sub.add_parser("media-auth", help="verify the dedicated MediaCrawler login session")
    auth.add_argument("--media-browser", choices=MEDIA_BROWSER_MODES, default="background")
    auth.add_argument("--qr-output", type=Path, required=True)
    auth.add_argument("--timeout", type=int, default=150)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    try:
        if args.command == "status":
            print(json.dumps(status(), ensure_ascii=False, indent=2))
            return 0
        if args.command == "media-auth":
            print(json.dumps(media_auth(args), ensure_ascii=False))
            return 0
        # The Media adapter runs in its own repository. Resolve once at the
        # Creator OS boundary so a user-supplied relative run path cannot be
        # interpreted relative to the adapter's working directory.
        args.output = args.output.expanduser().resolve()
        if args.command == "creator":
            print(json.dumps(creator_media(args), ensure_ascii=False))
            return 0
        if args.command == "detail" and not args.refresh:
            cached = xhs_api.read_note_detail_cache(args.url)
            if cached is not None:
                write_records(cached, args.output)
                write_manifest(args.output, {"provider": "cache", "operation": "detail", "cache": "hit", "returned_count": len(cached)})
                print(json.dumps({"provider": "cache", "stage": "detail", "output": str(args.output), "records": len(cached)}, ensure_ascii=False))
                return 0
        source = resolve_source(args.source)
        result = (
            search_apify(args) if args.command == "search" and source == "apify"
            else search_media(args) if args.command == "search"
            else details_apify(args) if args.command == "details" and source == "apify"
            else details_media(args) if args.command == "details"
            else detail_apify(args) if source == "apify"
            else detail_media(args)
        )
        print(json.dumps(result, ensure_ascii=False))
        return 0
    except (ProviderRouterError, xhs_api.ProviderError, OSError, subprocess.SubprocessError) as exc:
        print(json.dumps({"status": "error", "message": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
