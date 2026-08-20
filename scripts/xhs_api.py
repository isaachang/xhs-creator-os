#!/usr/bin/env python3
"""Read-only Xiaohongshu research adapter for Apify.

The script never accepts API keys on the command line. Set credentials through
environment variables and use `status` to inspect availability without values.
"""

from __future__ import annotations

import argparse
import getpass
import hashlib
import json
import os
import re
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from research_filters import annotate_record


APIFY_API_ORIGIN = "https://api.apify.com/v2"
DEFAULT_APIFY_XHS_ACTOR = "socialdatax~socialdatax-xhs-data-api"
APIFY_KEYCHAIN_SERVICE = "xhs-creator-os/apify-api-token"
SKILL_ROOT = Path(__file__).resolve().parents[1]
LOCAL_ENV_FILE = SKILL_ROOT / ".env.local"
DETAIL_CACHE_DIR = SKILL_ROOT / "data" / "note-detail-cache"


class ProviderError(RuntimeError):
    pass


def now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def env_set(name: str) -> bool:
    return bool(os.environ.get(name, "").strip())


def keychain_secret(service: str) -> str:
    """Read one secret from the macOS login keychain without exposing it."""
    if sys.platform != "darwin":
        return ""
    try:
        result = subprocess.run(
            [
                "/usr/bin/security",
                "find-generic-password",
                "-a",
                getpass.getuser(),
                "-s",
                service,
                "-w",
            ],
            check=False,
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    return result.stdout.strip() if result.returncode == 0 else ""


def local_env_secret(name: str) -> str:
    """Read one local secret file without printing or logging its value."""
    try:
        for line in LOCAL_ENV_FILE.read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith("#") or "=" not in stripped:
                continue
            key, value = stripped.split("=", 1)
            if key.strip() != name:
                continue
            value = value.strip()
            if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
                value = value[1:-1]
            return value.strip()
    except (OSError, UnicodeError):
        return ""
    return ""


def usable_secret(value: str) -> bool:
    """Reject empty values and shell/tool error text before using a credential."""
    lowered = value.strip().lower()
    return bool(lowered) and not any(char.isspace() for char in value) and not lowered.startswith(("security", "error", "warning"))


def apify_token() -> str:
    for candidate in (
        os.environ.get("APIFY_API_TOKEN", ""),
        local_env_secret("APIFY_API_TOKEN"),
        keychain_secret(APIFY_KEYCHAIN_SERVICE),
    ):
        if usable_secret(candidate):
            return candidate.strip()
    return ""


def first(record: dict[str, Any], *names: str) -> Any:
    for name in names:
        value = record.get(name)
        if value not in (None, ""):
            return value
    return None


def nested_first(*records: dict[str, Any], names: tuple[str, ...]) -> Any:
    for record in records:
        value = first(record, *names)
        if value not in (None, ""):
            return value
    return None


def iter_items(value: Any) -> Iterable[dict[str, Any]]:
    if isinstance(value, list):
        yield from (item for item in value if isinstance(item, dict))
        return
    if not isinstance(value, dict):
        return
    for key in ("items", "results", "notes", "articles", "list", "records"):
        if isinstance(value.get(key), list):
            yield from (item for item in value[key] if isinstance(item, dict))
            return
    data = value.get("data")
    if isinstance(data, list):
        yield from (item for item in data if isinstance(item, dict))
        return
    if isinstance(data, dict):
        nested = list(iter_items(data))
        if nested:
            yield from nested
            return
        yield data
        return
    yield value


def normalize_record(item: dict[str, Any], source: str, query: str | None) -> dict[str, Any]:
    user = item.get("user") if isinstance(item.get("user"), dict) else {}
    author = item.get("author") if isinstance(item.get("author"), dict) else {}
    note = item.get("note") if isinstance(item.get("note"), dict) else {}
    note_id = nested_first(item, note, names=("note_id", "noteId", "id", "workId", "id_str"))
    url = nested_first(item, note, names=("note_url", "noteUrl", "noteLink", "shareInfoLink", "url", "workUrl", "link"))
    xsec_token = nested_first(item, note, names=("xsec_token", "xsecToken"))
    # SocialDataX's note_url is authoritative. Do not rebuild or canonicalize it.
    # The fallback remains only for legacy providers that expose an ID/token pair.
    if not url and note_id and xsec_token and source != "apify":
        url = f"https://www.xiaohongshu.com/explore/{note_id}?xsec_token={xsec_token}"
    record = {
        "note_id": str(note_id) if note_id is not None else None,
        "url": url,
        "title": nested_first(item, note, names=("title", "note_title", "noteTitle", "workTitle")) or "",
        "body": nested_first(item, note, names=("body", "bodyText", "summary", "desc", "description", "content", "text", "note_desc", "workDesc")) or "",
        "author_id": first(item, "author_id", "authorId", "user_id", "userId", "accountUserid") or first(user, "user_id", "userId", "id") or first(author, "user_id", "userId", "id"),
        "author_name": first(item, "author_name", "authorName", "authorNickname", "nickname", "accountNickname", "author") or first(user, "nickname", "name") or first(author, "nickname", "name"),
        "author_url": first(item, "author_url", "authorUrl", "authorProfileUrl", "profile_url", "profileUrl", "user_url", "userUrl", "account_url", "accountUrl") or first(user, "url", "profile_url", "profileUrl", "user_url", "userUrl", "link") or first(author, "url", "profile_url", "profileUrl", "user_url", "userUrl", "link"),
        "published_at": nested_first(item, note, names=("published_at", "publishedAt", "publish_time", "publishTime", "createTime", "time", "workPublishTime")),
        "captured_at": now_iso(),
        "query": query,
        "source": source,
        "likes": nested_first(item, note, names=("likes", "like_count", "liked_count", "likedCount", "likeCount", "workLikedCount")),
        "saves": nested_first(item, note, names=("saves", "collects", "collected_count", "collectedCount", "collect_count", "collectCount", "favorites", "workCollectedCount")),
        "comments": nested_first(item, note, names=("commentsCount", "comment_count", "commentCount", "workCommentsCount", "comments")),
        "shares": nested_first(item, note, names=("shares", "shared_count", "sharedCount", "share_count", "shareCount", "workSharedCount")),
        "raw": item,
    }
    return {key: value for key, value in record.items() if value is not None}


def normalize_payload(value: Any, source: str, query: str | None) -> list[dict[str, Any]]:
    records = [annotate_record(normalize_record(item, source, query), query) for item in iter_items(value)]
    seen: set[str] = set()
    unique: list[dict[str, Any]] = []
    for record in records:
        key = str(record.get("note_id") or record.get("url") or record.get("title") or "")
        if not key or key in seen:
            continue
        seen.add(key)
        unique.append(record)
    return unique


def request_json(
    url: str,
    *,
    method: str = "GET",
    headers: dict[str, str] | None = None,
    payload: Any | None = None,
    timeout: int = 30,
) -> Any:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8") if payload is not None else None
    final_headers = {"Accept": "application/json", **(headers or {})}
    if body is not None:
        final_headers.setdefault("Content-Type", "application/json")
    req = urllib.request.Request(url, data=body, headers=final_headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            raw = response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:500]
        raise ProviderError(f"HTTP {exc.code}: {detail}") from exc
    except urllib.error.URLError as exc:
        raise ProviderError(f"network error: {exc.reason}") from exc
    try:
        return json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ProviderError(f"provider returned invalid JSON: {exc}") from exc


def apify_account_plan() -> dict[str, Any] | None:
    """Return non-sensitive Apify plan metadata when the account endpoint is available."""
    token = apify_token()
    if not token:
        return None
    try:
        response = request_json(
            f"{APIFY_API_ORIGIN}/users/me",
            headers={"Authorization": f"Bearer {token}"},
            timeout=15,
        )
    except ProviderError:
        return None
    data = response.get("data") if isinstance(response, dict) else None
    plan = data.get("plan") if isinstance(data, dict) else None
    if not isinstance(plan, dict):
        return None
    return {
        "id": plan.get("id"),
        "tier": plan.get("tier"),
        "is_paying": bool(data.get("isPaying")) if isinstance(data, dict) else None,
    }


def ensure_socialdatax_access() -> None:
    """Fail clearly before a paid SocialDataX Actor call on a free Apify plan."""
    plan = apify_account_plan()
    if plan and plan.get("id") == "FREE":
        raise ProviderError(
            "SocialDataX Actor requires a paid Apify plan; the configured Apify account is on FREE. "
            "Upgrade the Apify plan, then rerun this command. The API key is readable, but the account "
            "does not currently have access to SocialDataX data events."
        )


def apify_actor_id() -> str:
    actor = os.environ.get("APIFY_XHS_ACTOR", DEFAULT_APIFY_XHS_ACTOR).strip()
    if not re.fullmatch(r"[A-Za-z0-9_.-]+~[A-Za-z0-9_.-]+", actor):
        raise ProviderError("APIFY_XHS_ACTOR must be owner~actor-name")
    return actor


def apify_sort_type(value: str) -> str:
    return {
        "general": "general",
        "time_descending": "time_descending",
        "like_count_descending": "like_count_descending",
        "comment_count_descending": "comment_count_descending",
        "collect_count_descending": "collect_count_descending",
    }.get(value, "general")


def apify_time_filter(days: int) -> str:
    if days <= 1:
        return "day"
    if days <= 7:
        return "week"
    if days <= 183:
        return "half_year"
    return "all"


def apify_note_type(value: int) -> str:
    return {0: "all", 1: "video", 2: "image"}.get(value, "all")


XHSLINK_HOSTS = {"xhslink.com", "www.xhslink.com"}
REDNOTE_HOSTS = {"rednote.com", "www.rednote.com"}
XIAOHONGSHU_HOSTS = {"xiaohongshu.com", "www.xiaohongshu.com"}


def canonicalize_xiaohongshu_url(value: str) -> str:
    """Use the long Xiaohongshu explore route while preserving query parameters."""
    parsed = urllib.parse.urlsplit(value.strip())
    hostname = (parsed.hostname or "").lower()
    if hostname not in XIAOHONGSHU_HOSTS:
        return value.strip()
    match = re.fullmatch(r"/discovery/item/([A-Za-z0-9_-]+)", parsed.path)
    if not match:
        return value.strip()
    return urllib.parse.urlunsplit(parsed._replace(path=f"/explore/{match.group(1)}"))


def socialdatax_note_input(value: str) -> str:
    """Convert RedNote input to the long Xiaohongshu host/route for the Actor."""
    parsed = urllib.parse.urlsplit(value.strip())
    if parsed.hostname and parsed.hostname.lower() in REDNOTE_HOSTS:
        value = urllib.parse.urlunsplit(parsed._replace(netloc="www.xiaohongshu.com"))
    return canonicalize_xiaohongshu_url(value)


def is_xhslink_url(value: str) -> bool:
    parsed = urllib.parse.urlsplit(value.strip())
    return (parsed.hostname or "").lower() in XHSLINK_HOSTS


def resolve_xhslink_url(value: str, *, timeout: int = 30) -> str:
    """Follow an xhslink redirect and return a long Xiaohongshu URL."""
    request = urllib.request.Request(
        value.strip(),
        headers={"Accept": "text/html,application/xhtml+xml", "User-Agent": "Mozilla/5.0"},
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            resolved = response.geturl()
    except (urllib.error.HTTPError, urllib.error.URLError) as exc:
        raise ProviderError(f"xhslink long-link resolution failed: {exc}") from exc
    long_url = socialdatax_note_input(resolved)
    parsed = urllib.parse.urlsplit(long_url)
    if (parsed.hostname or "").lower() not in XIAOHONGSHU_HOSTS:
        raise ProviderError("xhslink resolved to a non-Xiaohongshu URL")
    if long_url.strip() == value.strip():
        raise ProviderError("xhslink did not redirect to a long Xiaohongshu URL")
    return long_url


def note_cache_keys(value: str) -> set[str]:
    """Build stable cache aliases for a note URL without retaining query tokens in filenames."""
    keys: set[str] = set()
    parsed = urllib.parse.urlsplit(value.strip())
    match = re.search(r"/(?:explore|discovery/item)/([A-Za-z0-9_-]+)", parsed.path)
    if match:
        keys.add(f"note-{match.group(1)}")
    digest = hashlib.sha256(value.strip().encode("utf-8")).hexdigest()
    keys.add(f"url-{digest}")
    return keys


def read_note_detail_cache(*urls: str) -> list[dict[str, Any]] | None:
    """Return the first non-empty cached detail result for any equivalent input URL."""
    for url in urls:
        for key in note_cache_keys(url):
            path = DETAIL_CACHE_DIR / f"{key}.json"
            try:
                value = json.loads(path.read_text(encoding="utf-8"))
            except (FileNotFoundError, OSError, UnicodeError, json.JSONDecodeError):
                continue
            if isinstance(value, list) and value and all(isinstance(item, dict) for item in value):
                return value
    return None


def write_note_detail_cache(records: list[dict[str, Any]], *urls: str) -> None:
    """Persist non-empty detail results under URL and note-ID aliases."""
    if not records:
        return
    keys: set[str] = set()
    for url in urls:
        keys.update(note_cache_keys(url))
    for record in records:
        if record.get("note_id"):
            keys.add(f"note-{record['note_id']}")
        if record.get("url"):
            keys.update(note_cache_keys(str(record["url"])))
    DETAIL_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(records, ensure_ascii=False, indent=2) + "\n"
    for key in keys:
        path = DETAIL_CACHE_DIR / f"{key}.json"
        path.write_text(payload, encoding="utf-8")
        os.chmod(path, 0o600)


def apify_search(args: argparse.Namespace) -> list[dict[str, Any]]:
    token = apify_token()
    if not token:
        raise ProviderError("APIFY_API_TOKEN is not set")
    ensure_socialdatax_access()
    actor = apify_actor_id()
    endpoint = f"{APIFY_API_ORIGIN}/acts/{urllib.parse.quote(actor, safe='~')}/run-sync-get-dataset-items"
    response = request_json(
        endpoint,
        method="POST",
        headers={"Authorization": f"Bearer {token}"},
        payload={
            "operation": "search_notes",
            "keyword": args.keyword,
            "sort_type": apify_sort_type(args.sort_type),
            "note_type": apify_note_type(args.note_type),
            "publish_time_range": apify_time_filter(args.days),
            "page_token": "",
            "max_items": args.limit,
            "auto_paginate": True,
        },
        timeout=min(args.timeout, 300),
    )
    return normalize_payload(response, "apify", args.keyword)[: args.limit]


def apify_detail_request(args: argparse.Namespace, note_url: str) -> list[dict[str, Any]]:
    token = apify_token()
    if not token:
        raise ProviderError("APIFY_API_TOKEN is not set and no Apify token was found in the macOS Keychain")
    actor = apify_actor_id()
    endpoint = f"{APIFY_API_ORIGIN}/acts/{urllib.parse.quote(actor, safe='~')}/run-sync-get-dataset-items"
    response = request_json(
        endpoint,
        method="POST",
        headers={"Authorization": f"Bearer {token}"},
        payload={
            "operation": "get_note_detail",
            "note_url": note_url,
        },
        timeout=min(getattr(args, "timeout", 180), 300),
    )
    records = normalize_payload(response, "apify", None)
    if not records:
        raise ProviderError("SocialDataX returned no detail records")
    return records


def apify_detail(args: argparse.Namespace) -> list[dict[str, Any]]:
    input_url = socialdatax_note_input(args.url)
    if not getattr(args, "refresh", False):
        cached = read_note_detail_cache(args.url, input_url)
        if cached is not None:
            print(json.dumps({"cache": "hit", "records": len(cached)}, ensure_ascii=False), file=sys.stderr)
            return cached
    ensure_socialdatax_access()
    try:
        records = apify_detail_request(args, input_url)
        write_note_detail_cache(records, args.url, input_url)
        return records
    except ProviderError as initial_error:
        if not is_xhslink_url(args.url):
            raise
        try:
            long_url = resolve_xhslink_url(args.url, timeout=min(getattr(args, "timeout", 180), 30))
        except ProviderError as resolution_error:
            raise ProviderError(
                f"xhslink request failed ({initial_error}); long-link resolution failed ({resolution_error})"
            ) from resolution_error
        if not getattr(args, "refresh", False):
            cached = read_note_detail_cache(long_url)
            if cached is not None:
                print(json.dumps({"cache": "hit", "records": len(cached), "via": "xhslink-long-url"}, ensure_ascii=False), file=sys.stderr)
                return cached
        try:
            records = apify_detail_request(args, long_url)
        except ProviderError as fallback_error:
            raise ProviderError(
                f"xhslink request failed ({initial_error}); long-link fallback failed ({fallback_error})"
            ) from fallback_error
        write_note_detail_cache(records, args.url, input_url, long_url)
        return records


def run_search(args: argparse.Namespace) -> list[dict[str, Any]]:
    routes = [args.source] if args.source != "auto" else ["apify"]
    errors: list[str] = []
    for route in routes:
        try:
            if route == "apify":
                return apify_search(args)
            raise ProviderError(f"unsupported source: {route}")
        except ProviderError as exc:
            errors.append(f"{route}: {exc}")
            if args.source != "auto":
                break
    raise ProviderError("; ".join(errors) or "no provider available")


def run_detail(args: argparse.Namespace) -> list[dict[str, Any]]:
    routes = [args.source] if args.source != "auto" else ["apify"]
    errors: list[str] = []
    for route in routes:
        try:
            if route == "apify":
                return apify_detail(args)
            raise ProviderError(f"unsupported source: {route}")
        except ProviderError as exc:
            errors.append(f"{route}: {exc}")
            if args.source != "auto":
                break
    raise ProviderError("; ".join(errors) or "no provider available")


def write_output(records: list[dict[str, Any]], path: Path | None) -> None:
    text = json.dumps(records, ensure_ascii=False, indent=2) + "\n"
    if path:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        print(json.dumps({"records": len(records), "output": str(path)}, ensure_ascii=False))
    else:
        print(text, end="")


def add_shared_api_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--limit", type=int, default=15)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--timeout", type=int, default=180)
    parser.add_argument("--poll-attempts", type=int, default=60)
    parser.add_argument("--poll-interval", type=float, default=2.0)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("status", help="show provider availability without secret values")

    search = sub.add_parser("search", help="collect keyword research")
    search.add_argument("keyword")
    search.add_argument("--source", choices=("auto", "apify"), default="auto")
    search.add_argument("--days", type=int, default=3650, help="1/7/183 or less maps to Actor ranges; larger values means all")
    search.add_argument("--sort-type", default="general")
    search.add_argument("--note-type", type=int, choices=(0, 1, 2), default=2, help="0=all, 1=video, 2=image")
    add_shared_api_options(search)

    detail = sub.add_parser("detail", help="read one public note through SocialDataX")
    detail.add_argument("url")
    detail.add_argument("--source", choices=("auto", "apify"), default="auto")
    detail.add_argument("--refresh", action="store_true", help="ignore local detail cache and request fresh data")
    add_shared_api_options(detail)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    if args.command == "status":
        apify_configured = bool(apify_token())
        result = {
            "apify": {
                "configured": apify_configured,
                "actor": os.environ.get("APIFY_XHS_ACTOR", DEFAULT_APIFY_XHS_ACTOR),
                "storage": "environment_or_project_env_or_macos_keychain",
            },
        }
        if apify_configured:
            plan = apify_account_plan()
            if plan:
                result["apify"]["plan"] = plan
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    try:
        if args.command == "search":
            records = run_search(args)
        else:
            records = run_detail(args)
        write_output(records, args.output)
        return 0
    except ProviderError as exc:
        print(json.dumps({"status": "error", "command": args.command, "message": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
