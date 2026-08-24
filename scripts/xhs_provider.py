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
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import xhs_api
import research_cache
from store import DEFAULT_DB, connect, import_research


SKILL_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MEDIA_ROOT = SKILL_ROOT / "third_party" / "mediacrawler" / "runtime"
MEDIA_SESSION_SCRIPT = SKILL_ROOT / "scripts" / "media_session.py"
MEDIA_SESSION_PORT = 9233
CONTENT_TYPES = ("image", "video", "all")
SOURCES = ("auto", "apify", "media")
MEDIA_BROWSER_MODES = ("background", "visible")
MEDIA_SITES = ("xiaohongshu", "rednote")
MEDIA_SITE_MODE_CHOICES = ("auto", *MEDIA_SITES)
MEDIA_AUTH_STATE_NAME = "creator-os-media-auth.json"
MEDIA_BOOTSTRAP_PROFILE = "creator-os-bootstrap-profile"
MEDIA_LEGACY_PROFILE = "creator-os-chromium-profile"
RESEARCH_RUNS_ROOT = SKILL_ROOT / "runs"
MEDIA_RESEARCH_CACHE_MAX_AGE = timedelta(days=7)


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


def media_auth_state_path(root: Path) -> Path:
    return root / "browser_data" / MEDIA_AUTH_STATE_NAME


def load_media_auth_state(root: Path) -> dict[str, Any]:
    """Read only Creator-OS metadata; this file never contains cookies."""
    try:
        value = json.loads(media_auth_state_path(root).read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return {"version": 1, "active_site": None, "sites": {}}
    if not isinstance(value, dict):
        return {"version": 1, "active_site": None, "sites": {}}
    sites = value.get("sites")
    if not isinstance(sites, dict):
        sites = {}
    valid_sites = {
        site: entry
        for site, entry in sites.items()
        if site in MEDIA_SITES and isinstance(entry, dict) and isinstance(entry.get("profile"), str)
    }
    active_site = value.get("active_site") if value.get("active_site") in valid_sites else None
    return {"version": 1, "active_site": active_site, "sites": valid_sites}


def write_media_auth_state(root: Path, state: dict[str, Any]) -> None:
    """Atomically persist non-secret login-validation metadata."""
    path = media_auth_state_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "version": 1,
        "active_site": state.get("active_site") if state.get("active_site") in MEDIA_SITES else None,
        "sites": state.get("sites") if isinstance(state.get("sites"), dict) else {},
    }
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def profile_name_for_site(site: str) -> str:
    if site not in MEDIA_SITES:
        raise ProviderRouterError("Media 站点必须是 xiaohongshu 或 rednote。")
    return f"creator-os-{site}-profile"


def profile_path(root: Path, profile_name: str) -> Path:
    return root / "browser_data" / profile_name


def site_from_url(value: str) -> str | None:
    host = (urlparse(value).hostname or "").lower()
    if host == "rednote.com" or host.endswith(".rednote.com"):
        return "rednote"
    if host == "xiaohongshu.com" or host.endswith(".xiaohongshu.com"):
        return "xiaohongshu"
    return None


def profile_site_marker(root: Path, profile_name: str) -> str | None:
    try:
        value = json.loads((profile_path(root, profile_name) / "creator_os_site.json").read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return None
    site = value.get("site") if isinstance(value, dict) else None
    return site if site in MEDIA_SITES else None


def media_profile_for(
    root: Path,
    *,
    requested_site: str | None = None,
    allow_unverified: bool = False,
) -> tuple[str, str | None]:
    """Resolve an isolated profile without ever mixing domestic and Rednote state."""
    state = load_media_auth_state(root)
    site = requested_site or state.get("active_site")
    if site:
        entry = state["sites"].get(site)
        expected_profile = profile_name_for_site(site)
        if (
            entry
            and entry.get("profile") == expected_profile
            and profile_path(root, expected_profile).is_dir()
            and (allow_unverified or entry.get("validation") == "search_smoke_success")
        ):
            return expected_profile, site
        candidate = profile_name_for_site(site)
        if allow_unverified and profile_path(root, candidate).is_dir():
            return candidate, site
        if not allow_unverified:
            raise ProviderRouterError(
                f"Media 的 {site} 专用会话尚未通过真实搜索验证；"
                "请先主动运行一次 media-auth --media-browser visible。"
            )

    # Preserve existing local users' state for one revalidation; do not move,
    # delete, or read session values until a visible login has succeeded.
    if allow_unverified and profile_path(root, MEDIA_LEGACY_PROFILE).is_dir():
        return MEDIA_LEGACY_PROFILE, profile_site_marker(root, MEDIA_LEGACY_PROFILE)
    if not allow_unverified:
        raise ProviderRouterError(
            "Media 尚未完成一次可用验证。请先主动运行 media-auth --media-browser visible 并完成扫码；"
            "系统会在扫码后执行一次低频搜索验证。"
        )
    return MEDIA_BOOTSTRAP_PROFILE, None


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
    payload = dict(metadata)
    if not payload.get("captured_at"):
        payload["captured_at"] = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _cache_text(value: Any) -> str:
    return " ".join(str(value or "").strip().casefold().split())


def _cache_days(value: Any) -> int:
    try:
        return int(value) if value not in (None, "") else 3650
    except (TypeError, ValueError):
        return 3650


def _cache_time(value: Any, fallback: Path) -> datetime:
    if isinstance(value, str) and value.strip():
        try:
            parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            return parsed.astimezone(timezone.utc)
        except ValueError:
            pass
    return datetime.fromtimestamp(fallback.stat().st_mtime, tz=timezone.utc)


def _read_json_object(path: Path) -> dict[str, Any] | None:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) else None


def _media_cache_allowed(source: str) -> bool:
    """Do not let a local Media cache override an explicit Apify request."""
    return source == "media" or (source == "auto" and not xhs_api.apify_token())


def find_cached_media_research(args: argparse.Namespace, *, runs_root: Path = RESEARCH_RUNS_ROOT) -> dict[str, Any] | None:
    """Return one exact, fresh final Media Research result without launching Media."""
    if not _media_cache_allowed(args.source) or getattr(args, "refresh", False) or not runs_root.is_dir():
        return None
    now = datetime.now(timezone.utc)
    matches: list[tuple[datetime, Path, list[dict[str, Any]], dict[str, Any]]] = []
    for final_manifest in runs_root.rglob("*.manifest.json"):
        if final_manifest.name.endswith(".candidates.manifest.json"):
            continue
        final_meta = _read_json_object(final_manifest)
        if not final_meta or final_meta.get("provider") != "media" or final_meta.get("operation") != "research":
            continue
        output_stem = final_manifest.name.removesuffix(".manifest.json")
        output = final_manifest.with_name(f"{output_stem}.json")
        candidate_manifest = output.with_name(f"{output_stem}.candidates.manifest.json")
        candidate_meta = _read_json_object(candidate_manifest) or {}
        metadata = dict(candidate_meta)
        metadata.update({key: value for key, value in final_meta.items() if value not in (None, "")})
        if _cache_text(metadata.get("query")) != _cache_text(args.keyword):
            continue
        if _cache_text(metadata.get("sort_type") or "general") != _cache_text(args.sort_type):
            continue
        if _cache_text(metadata.get("note_type") or "image") != _cache_text(args.content_type):
            continue
        if _cache_days(metadata.get("publish_days")) != _cache_days(args.days):
            continue
        try:
            records = load_records(output)
        except ProviderRouterError:
            continue
        if len(records) < args.limit:
            continue
        captured_at = _cache_time(metadata.get("captured_at"), output)
        if now - captured_at > MEDIA_RESEARCH_CACHE_MAX_AGE:
            continue
        matches.append((captured_at, output, records, metadata))
    if not matches:
        return None
    captured_at, output, records, metadata = max(matches, key=lambda item: item[0])
    return {
        "records": records[: args.limit],
        "captured_at": captured_at.isoformat().replace("+00:00", "Z"),
        "origin": output,
        "candidate_count": metadata.get("candidate_count"),
    }


def find_cached_media_creator(args: argparse.Namespace, *, runs_root: Path = RESEARCH_RUNS_ROOT) -> dict[str, Any] | None:
    """Return one exact, fresh creator Top-N cache hit without launching Media."""
    if getattr(args, "refresh", False) or not runs_root.is_dir():
        return None
    target = _cache_text(args.creator_url)
    now = datetime.now(timezone.utc)
    matches: list[tuple[datetime, Path, list[dict[str, Any]], dict[str, Any]]] = []
    for manifest in runs_root.rglob("*.manifest.json"):
        meta = _read_json_object(manifest)
        if not meta or meta.get("provider") != "media" or meta.get("operation") != "creator_top":
            continue
        if _cache_text(meta.get("creator_url")) != target:
            continue
        if int(meta.get("requested_top") or 0) < args.top or int(meta.get("scan_limit") or 0) < args.scan_limit:
            continue
        output = manifest.with_name(manifest.name.removesuffix(".manifest.json") + ".json")
        try:
            records = load_records(output)
        except ProviderRouterError:
            continue
        if len(records) < args.top:
            continue
        captured_at = _cache_time(meta.get("captured_at"), output)
        if now - captured_at > MEDIA_RESEARCH_CACHE_MAX_AGE:
            continue
        matches.append((captured_at, output, records, meta))
    if not matches:
        return None
    captured_at, output, records, meta = max(matches, key=lambda item: item[0])
    return {
        "records": records[: args.top],
        "captured_at": captured_at.isoformat().replace("+00:00", "Z"),
        "origin": output,
        "scan_limit": meta.get("scan_limit"),
    }


def write_cached_result(output: Path, cached: dict[str, Any], *, operation: str) -> dict[str, Any]:
    records = list(cached["records"])
    write_records(records, output)
    write_manifest(
        output,
        {
            "provider": "cache",
            "data_source": "本地 Media Research 缓存",
            "operation": operation,
            "cache": "hit",
            "origin_captured_at": cached["captured_at"],
            "returned_count": len(records),
        },
    )
    return {"provider": "cache", "stage": "final", "output": str(output), "records": len(records), "cache": "hit"}


def cached_detail_records(urls: list[str]) -> tuple[list[dict[str, Any]], list[str]]:
    """Split a requested detail batch into exact local hits and missing URLs."""
    cached_records: list[dict[str, Any]] = []
    missing: list[str] = []
    seen_records: set[str] = set()
    for url in urls:
        cached = xhs_api.read_note_detail_cache(url)
        if cached is None:
            missing.append(url)
            continue
        requested_keys = xhs_api.note_cache_keys(url)
        matching = [
            record
            for record in cached
            if (
                (record.get("note_id") and f"note-{record['note_id']}" in requested_keys)
                or (
                    record.get("url")
                    and bool(xhs_api.note_cache_keys(str(record["url"])) & requested_keys)
                )
            )
        ]
        if not matching:
            # Earlier batch-mode versions could write a whole response list
            # under every requested URL. Never reuse those mismatched entries.
            missing.append(url)
            continue
        for record in matching:
            key = str(record.get("note_id") or record.get("url") or json.dumps(record, ensure_ascii=False, sort_keys=True))
            if key not in seen_records:
                cached_records.append(record)
                seen_records.add(key)
    return cached_records, missing


def merge_detail_records(*groups: list[dict[str, Any]]) -> list[dict[str, Any]]:
    merged: list[dict[str, Any]] = []
    seen: set[str] = set()
    for records in groups:
        for record in records:
            key = str(record.get("note_id") or record.get("url") or json.dumps(record, ensure_ascii=False, sort_keys=True))
            if key not in seen:
                merged.append(record)
                seen.add(key)
    return merged


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


def ensure_media_session(root: Path, profile_name: str) -> None:
    """Start or reuse the one dedicated Media CDP browser on loopback."""
    result = subprocess.run(
        [
            sys.executable,
            str(MEDIA_SESSION_SCRIPT),
            "ensure",
            "--media-root",
            str(root),
            "--port",
            str(MEDIA_SESSION_PORT),
            "--profile",
            profile_name,
        ],
        text=True,
        capture_output=True,
        check=False,
        timeout=25,
    )
    if result.returncode:
        detail = (result.stderr or result.stdout or "Media session failed").strip().replace("\n", " ")[:400]
        raise ProviderRouterError(f"Media 专用浏览器会话不可用：{detail}")


def media_runtime_log_path(root: Path) -> Path:
    """Return the ignored, sanitized runtime-event log for MediaCrawler."""
    return root / "browser_data" / "creator-os-runtime.jsonl"


def _media_argument(command: list[str], name: str) -> str | None:
    try:
        return command[command.index(name) + 1]
    except (ValueError, IndexError):
        return None


def write_media_runtime_event(
    root: Path,
    command: list[str],
    result: subprocess.CompletedProcess[str],
    *,
    profile_name: str,
    site: str | None,
) -> None:
    """Persist diagnostic signals only; never copy upstream stdout or secrets."""
    combined = f"{result.stdout or ''}\n{result.stderr or ''}"
    event = {
        "captured_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "operation": _media_argument(command, "--type") or "unknown",
        "headless": _media_argument(command, "--headless") or "unknown",
        "returncode": result.returncode,
        "profile": profile_name,
        "site": site or "unknown",
        "signals": {
            "cdp_port_unavailable": "Cannot find available port" in combined,
            "cdp_fallback": "falling back to standard mode" in combined,
            "background_offscreen_mode": "Creator OS off-screen background" in combined,
            "qr_opened": "waiting for scan code login" in combined,
            "login_authenticated": "state=authenticated" in combined,
            "login_unauthenticated": "state=unauthenticated" in combined,
            "login_unknown": "state=unknown" in combined,
            "browser_session_confirmed": "confirmed dedicated browser session" in combined,
            "rednote": "rednote.com" in combined,
            "search_permission_denied": "当前登录的账号没有权限访问" in combined,
        },
    }
    path = media_runtime_log_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(event, ensure_ascii=False) + "\n")


def run_media(
    command: list[str],
    *,
    root: Path,
    extra_env: dict[str, str] | None = None,
    timeout: int = 300,
    profile_name: str | None = None,
    site: str | None = None,
) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    profile_name = profile_name or media_profile_for(root, requested_site=site)[0]
    matplotlib_cache = root / "browser_data" / ".creator-os-mplconfig"
    matplotlib_cache.mkdir(parents=True, exist_ok=True)
    env.setdefault("MPLCONFIGDIR", str(matplotlib_cache))
    if extra_env:
        env.update(extra_env)
    # Workers always attach to the dedicated long-running browser.  The
    # command's headless argument cannot open another Chrome in this mode.
    env["CREATOR_OS_CDP_CONNECT_EXISTING"] = "1"
    env["CREATOR_OS_SHARED_BROWSER"] = "1"
    env["CREATOR_OS_CDP_PORT"] = str(MEDIA_SESSION_PORT)
    env["CREATOR_OS_PROFILE_DIR"] = str(profile_path(root, profile_name))
    if _media_argument(command, "--headless") == "yes":
        env["CREATOR_OS_BACKGROUND_MODE"] = "1"
    with media_session_lock(root):
        ensure_media_session(root, profile_name)
        result = subprocess.run(
            [str(media_python(root)), "main.py", *command],
            cwd=root,
            text=True,
            capture_output=True,
            timeout=timeout,
            check=False,
            env=env,
        )
    write_media_runtime_event(root, command, result, profile_name=profile_name, site=site)
    if result.returncode != 0:
        combined = f"{result.stderr or ''}\n{result.stdout or ''}"
        if "当前登录的账号没有权限访问" in combined:
            raise ProviderRouterError(
                "MediaCrawler 搜索接口被平台拒绝；这可能是未验证登录态，也可能是账号/站点权限或风控限制。"
                "后台任务不会自动弹二维码。请主动完成一次可见登录及搜索验证；"
                "若验证后仍被拒绝，说明当前站点会话不可用于搜索，请改用 Apify。"
            )
        detail = (result.stderr or result.stdout or "MediaCrawler failed").strip().replace("\n", " ")[:600]
        raise ProviderRouterError(f"MediaCrawler 请求失败：{detail}")
    return result


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
    profile_name, site = media_profile_for(root)
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
    run_media(command, root=root, profile_name=profile_name, site=site)
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
    profile_name, site = media_profile_for(root, requested_site=site_from_url(note_url))
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
        profile_name=profile_name,
        site=site,
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
    sites = {site_from_url(url) for url in urls}
    sites.discard(None)
    if len(sites) > 1:
        raise ProviderRouterError("一次 Media 详情读取不能混用小红书与 Rednote 链接；请按站点分别读取。")
    requested_site = next(iter(sites), None)
    profile_name, site = media_profile_for(root, requested_site=requested_site)
    # The upstream comma-separated detail route can return unrelated records
    # for a batch. Keep the same long-lived browser session but read one URL at
    # a time, then deduplicate at the Creator OS boundary. This is slower but
    # gives Research/Compare an auditable one-request-to-one-note contract.
    records: list[dict[str, Any]] = []
    seen: set[str] = set()
    temporary_outputs: list[Path] = []
    try:
        for index, url in enumerate(urls):
            temporary_output = args.output.with_name(
                f".{args.output.stem}.media-detail-{index}{args.output.suffix or '.json'}"
            )
            temporary_outputs.extend([temporary_output, manifest_path(temporary_output)])
            run_media(
                [
                    "--platform", "xhs",
                    "--type", "detail",
                    "--specified_id", url,
                    "--get_comment", "no",
                    "--creator_os_output", str(temporary_output),
                    *media_browser_args(args),
                ],
                root=root,
                profile_name=profile_name,
                site=site,
            )
            for record in load_records(temporary_output):
                key = str(record.get("note_id") or record.get("url") or "")
                if key and key not in seen:
                    records.append(record)
                    seen.add(key)
    finally:
        for temporary_output in temporary_outputs:
            temporary_output.unlink(missing_ok=True)
    write_records(records, args.output)
    if not records:
        raise ProviderRouterError("MediaCrawler 未返回所选笔记详情")
    # Persist each detail only under its own stable aliases. Do not associate a
    # batched response with every requested URL: that would poison later cache
    # reads if one upstream response contains unrelated records.
    for record in records:
        record_urls = [str(record.get("url") or "")]
        note_id = str(record.get("note_id") or "")
        if note_id:
            record_urls.append(f"https://www.xiaohongshu.com/explore/{note_id}")
        for requested, resolved in zip(args.urls, urls):
            requested_keys = xhs_api.note_cache_keys(resolved)
            if (note_id and f"note-{note_id}" in requested_keys) or (
                record.get("url") and bool(xhs_api.note_cache_keys(str(record["url"])) & requested_keys)
            ):
                record_urls.extend([requested, resolved])
        xhs_api.write_note_detail_cache([record], *[item for item in record_urls if item])
    try:
        metadata = json.loads(manifest_path(args.output).read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        metadata = {}
    metadata.update({"provider": "media", "data_source": "本机 MediaCrawler", "operation": "details", "returned_count": len(records)})
    write_manifest(args.output, metadata)
    return {"provider": "media", "stage": "details", "output": str(args.output), "records": len(records)}


def creator_media(args: argparse.Namespace) -> dict[str, Any]:
    root = media_root()
    profile_name, site = media_profile_for(root, requested_site=site_from_url(args.creator_url))
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
        profile_name=profile_name,
        site=site,
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
        "creator_url": args.creator_url,
        "requested_top": args.top,
        "scan_limit": args.scan_limit,
        "returned_count": len(records),
    })
    write_manifest(args.output, metadata)
    return {"provider": "media", "stage": "creator_top", "output": str(args.output), "records": len(records)}


def promote_media_profile(root: Path, profile_name: str, site: str) -> dict[str, Any]:
    result = subprocess.run(
        [
            sys.executable,
            str(MEDIA_SESSION_SCRIPT),
            "promote",
            "--media-root",
            str(root),
            "--port",
            str(MEDIA_SESSION_PORT),
            "--profile",
            profile_name,
            "--site",
            site,
        ],
        text=True,
        capture_output=True,
        check=False,
        timeout=30,
    )
    if result.returncode:
        detail = (result.stderr or result.stdout or "Media profile promotion failed").strip().replace("\n", " ")[:400]
        raise ProviderRouterError(f"Media 专用 Profile 迁移失败：{detail}")
    try:
        payload = json.loads(result.stdout)
    except (TypeError, json.JSONDecodeError) as exc:
        raise ProviderRouterError("Media 专用 Profile 迁移返回格式无效。") from exc
    if not isinstance(payload, dict) or not isinstance(payload.get("profile"), str):
        raise ProviderRouterError("Media 专用 Profile 迁移未返回目标 Profile。")
    return payload


def minimize_media_testing_windows() -> bool:
    """Minimize only the Creator OS Chrome Testing app after a successful QR login.

    The long-lived browser process must stay alive to preserve the isolated
    Profile. On macOS, minimizing its windows keeps the session running while
    returning focus to the user's work. The guard avoids launching Chrome
    Testing merely to minimize it.
    """
    if sys.platform != "darwin":
        return False
    script = (
        'if application "Google Chrome for Testing" is running then '
        'tell application "Google Chrome for Testing" to set miniaturized of every window to true'
    )
    try:
        result = subprocess.run(
            ["/usr/bin/osascript", "-e", script],
            text=True,
            capture_output=True,
            check=False,
            timeout=5,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return result.returncode == 0


def run_media_smoke_search(root: Path, profile_name: str, site: str) -> None:
    """Verify a visible login with one low-frequency search, not cookie presence."""
    browser_data = root / "browser_data"
    browser_data.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="creator-os-media-smoke-", dir=browser_data) as temporary:
        output = Path(temporary) / "smoke.json"
        run_media(
            [
                "--platform", "xhs",
                "--type", "search",
                "--keywords", "宠物友好",
                "--sort_type", "general",
                "--note_type", "image",
                "--crawler_max_notes_count", "1",
                "--research_screening", "no",
                "--fetch_details", "no",
                "--get_comment", "no",
                "--creator_os_output", str(output),
                "--headless", "yes",
            ],
            root=root,
            profile_name=profile_name,
            site=site,
            timeout=120,
        )
        if not output.is_file() or not load_records(output):
            raise ProviderRouterError("Media 登录后的低频搜索未返回候选，不能标记为可用。")


def media_auth(args: argparse.Namespace) -> dict[str, Any]:
    root = media_root()
    requested_site = None if args.site == "auto" else args.site
    profile_name, known_site = media_profile_for(
        root,
        requested_site=requested_site,
        allow_unverified=True,
    )
    result = run_media(
        ["--platform", "xhs", "--type", "session", *media_browser_args(args)],
        root=root,
        extra_env={"CREATOR_OS_INTERACTIVE_AUTH": "1"} if args.media_browser == "visible" else None,
        timeout=args.timeout,
        profile_name=profile_name,
        site=known_site or requested_site,
    )
    combined = f"{result.stdout or ''}\n{result.stderr or ''}"
    api_verified = "state=authenticated" in combined
    qr_verified = "Login confirmed by" in combined
    browser_verified = "confirmed dedicated browser session" in combined
    authenticated = api_verified or qr_verified or browser_verified
    # An explicit `--site` is a deliberate correction for an auto-detected
    # marker and must win; otherwise a prior Rednote marker could route a
    # domestic QR session into the wrong isolated profile.
    detected_site = requested_site or profile_site_marker(root, profile_name) or known_site
    if args.media_browser == "visible" and authenticated and detected_site:
        try:
            run_media_smoke_search(root, profile_name, detected_site)
        except ProviderRouterError as exc:
            return {
                "provider": "media",
                "authenticated": False,
                "verification": "登录信号已出现，但低频搜索验证未通过",
                "reason": str(exc),
                "site": detected_site,
                "profile": profile_name,
                "browser": args.media_browser,
                "login_window": "二维码已关闭；后台任务不会自动重新弹出。",
            }
        promoted = promote_media_profile(root, profile_name, detected_site)
        final_profile = str(promoted["profile"])
        # Promotion is a directory rename, so prove that the renamed Profile
        # can immediately boot as the dedicated background browser before we
        # persist it as reusable. This does not inspect session values.
        ensure_media_session(root, final_profile)
        minimized = minimize_media_testing_windows()
        state = load_media_auth_state(root)
        state["sites"][detected_site] = {
            "profile": final_profile,
            "validated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "validation": "search_smoke_success",
        }
        state["active_site"] = detected_site
        write_media_auth_state(root, state)
        return {
            "provider": "media",
            "authenticated": True,
            "verification": "二维码登录后已通过低频搜索验证",
            "site": detected_site,
            "profile": final_profile,
            "browser": args.media_browser,
            "login_window": "二维码确认成功后已自动关闭；后续任务后台复用此站点专用 Profile。",
            "browser_window": "Chrome Testing 已自动最小化。" if minimized else "Chrome Testing 已恢复为后台隐藏会话。",
        }
    return {
        "provider": "media",
        "authenticated": authenticated,
        "verification": (
            "已通过 API 会话确认" if api_verified
            else "已通过二维码会话确认" if qr_verified
            else "已通过专用浏览器会话确认" if browser_verified
            else "探测接口未确认；可见登录也未确认写入专用 Profile"
        ),
        "site": detected_site,
        "profile": profile_name,
        "browser": args.media_browser,
        "login_window": "background 模式不显示窗口；仅可见登录初始化允许原生二维码自动关闭",
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
            "auth_state": load_media_auth_state(root),
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
    search.add_argument("--refresh", action="store_true", help="ignore compatible local Media Research cache")
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
    creator.add_argument("--refresh", action="store_true", help="ignore compatible local Media creator cache")
    creator.add_argument("--media-browser", choices=MEDIA_BROWSER_MODES, default="background")
    creator.add_argument("--output", type=Path, required=True)

    auth = sub.add_parser("media-auth", help="verify the dedicated MediaCrawler login session")
    auth.add_argument("--media-browser", choices=MEDIA_BROWSER_MODES, default="background")
    auth.add_argument("--site", choices=MEDIA_SITE_MODE_CHOICES, default="auto", help="首次登录可自动识别；仅多站点用户需要显式指定")
    auth.add_argument("--timeout", type=int, default=150)
    return parser


def maintain_research_cache(command: str) -> dict[str, Any] | None:
    """Run lazy cache maintenance only for user-triggered research routes."""
    if command not in {"search", "detail", "details", "creator"}:
        return None
    try:
        result = research_cache.check_and_cleanup()
    except OSError:
        # Cache maintenance is ancillary; a local lock/state problem must not
        # prevent the requested public-data operation from running.
        print(
            json.dumps(
                {"cache_maintenance": {"status": "unavailable", "warning": "缓存维护不可用，本次继续执行 Research。"}},
                ensure_ascii=False,
            ),
            file=sys.stderr,
        )
        return None
    if result.get("due") or result.get("warning"):
        print(json.dumps({"cache_maintenance": result}, ensure_ascii=False), file=sys.stderr)
    return result


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
        maintain_research_cache(args.command)
        if args.command == "search":
            cached_research = find_cached_media_research(args)
            if cached_research is not None:
                print(json.dumps(write_cached_result(args.output, cached_research, operation="research"), ensure_ascii=False))
                return 0
        if args.command == "creator":
            cached_creator = find_cached_media_creator(args)
            if cached_creator is not None:
                print(json.dumps(write_cached_result(args.output, cached_creator, operation="creator_top"), ensure_ascii=False))
                return 0
            print(json.dumps(creator_media(args), ensure_ascii=False))
            return 0
        if args.command == "detail" and not args.refresh:
            cached = xhs_api.read_note_detail_cache(args.url)
            if cached is not None:
                write_records(cached, args.output)
                write_manifest(args.output, {"provider": "cache", "operation": "detail", "cache": "hit", "returned_count": len(cached)})
                print(json.dumps({"provider": "cache", "stage": "detail", "output": str(args.output), "records": len(cached)}, ensure_ascii=False))
                return 0
        if args.command == "details" and not args.refresh and _media_cache_allowed(args.source):
            cached_records, missing_urls = cached_detail_records(args.urls)
            if cached_records and not missing_urls:
                write_records(cached_records, args.output)
                write_manifest(args.output, {"provider": "cache", "operation": "details", "cache": "hit", "returned_count": len(cached_records)})
                print(json.dumps({"provider": "cache", "stage": "details", "output": str(args.output), "records": len(cached_records)}, ensure_ascii=False))
                return 0
            if cached_records:
                fresh_args = argparse.Namespace(**vars(args))
                fresh_args.urls = missing_urls
                fresh_result = details_media(fresh_args)
                merged_records = merge_detail_records(cached_records, load_records(args.output))
                write_records(merged_records, args.output)
                write_manifest(
                    args.output,
                    {
                        "provider": "media",
                        "data_source": "本机 MediaCrawler + 本地详情缓存",
                        "operation": "details",
                        "cache": "partial",
                        "cache_records": len(cached_records),
                        "requested_from_media": len(missing_urls),
                        "returned_count": len(merged_records),
                    },
                )
                fresh_result.update({"records": len(merged_records), "cache": "partial"})
                print(json.dumps(fresh_result, ensure_ascii=False))
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
