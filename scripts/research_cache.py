#!/usr/bin/env python3
"""Maintain the user-triggered lifecycle of the Research detail cache.

This module deliberately does not run on a timer. The shared provider route
calls :func:`check_and_cleanup` when a user starts a Research operation. The
cache is considered idle when the previous user-triggered operation was at
least 14 * 24 hours ago.
"""

from __future__ import annotations

import contextlib
import fcntl
import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterator

import xhs_api


SKILL_ROOT = Path(__file__).resolve().parents[1]
DETAIL_CACHE_DIR = xhs_api.DETAIL_CACHE_DIR
STATE_PATH = SKILL_ROOT / "data" / "research-cache-state.json"
LOCK_PATH = SKILL_ROOT / "data" / "research-cache-state.json.lock"
IDLE_PERIOD = timedelta(days=14)
STATE_VERSION = 1


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _now_iso(value: datetime | None = None) -> str:
    current = _utc(value or datetime.now(timezone.utc))
    return current.isoformat(timespec="seconds").replace("+00:00", "Z")


def _parse_time(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        return _utc(datetime.fromisoformat(value.strip().replace("Z", "+00:00")))
    except ValueError:
        return None


def _default_state() -> dict[str, Any]:
    return {
        "version": STATE_VERSION,
        "last_use_at": None,
        "last_cleanup_at": None,
        "last_cleanup_status": "never",
        "last_cleanup_deleted_count": 0,
        "cleanup_pending": False,
    }


def _load_state(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, OSError, UnicodeError, json.JSONDecodeError):
        return _default_state()
    if not isinstance(payload, dict):
        return _default_state()
    state = _default_state()
    state.update({key: payload[key] for key in state if key in payload})
    state["version"] = STATE_VERSION
    state["cleanup_pending"] = bool(state.get("cleanup_pending"))
    return state


def _write_state(path: Path, state: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp-{os.getpid()}")
    temporary.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.chmod(temporary, 0o600)
    temporary.replace(path)


@contextlib.contextmanager
def _state_lock(path: Path) -> Iterator[None]:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+", encoding="utf-8") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def _cache_files(cache_dir: Path) -> list[Path]:
    if not cache_dir.is_dir():
        return []
    files: list[Path] = []
    for entry in cache_dir.iterdir():
        try:
            if entry.is_file() and entry.suffix == ".json":
                files.append(entry)
        except OSError:
            continue
    return sorted(files, key=lambda item: item.name)


def _delete_cache_files(cache_dir: Path) -> tuple[int, list[str]]:
    deleted = 0
    errors: list[str] = []
    for path in _cache_files(cache_dir):
        try:
            path.unlink()
            deleted += 1
        except FileNotFoundError:
            continue
        except OSError:
            errors.append(path.name)
    return deleted, errors


def check_and_cleanup(
    *,
    now: datetime | None = None,
    state_path: Path = STATE_PATH,
    cache_dir: Path = DETAIL_CACHE_DIR,
    lock_path: Path = LOCK_PATH,
) -> dict[str, Any]:
    """Record a user use and clean an idle detail cache when due.

    The returned result is safe to print: it contains no cached note content,
    URLs, tokens, or absolute paths. A failed deletion remains pending so the
    next user-triggered operation retries it.
    """

    current = _utc(now or datetime.now(timezone.utc))
    current_iso = _now_iso(current)
    result: dict[str, Any] = {
        "checked": True,
        "due": False,
        "status": "not_due",
        "deleted_count": 0,
        "last_use_at": current_iso,
    }

    with _state_lock(lock_path):
        state = _load_state(state_path)
        previous_use = _parse_time(state.get("last_use_at"))
        idle_due = previous_use is not None and current - previous_use >= IDLE_PERIOD
        due = bool(state.get("cleanup_pending")) or idle_due
        result["due"] = due

        if due:
            deleted_count, errors = _delete_cache_files(cache_dir)
            result["deleted_count"] = deleted_count
            state["last_cleanup_deleted_count"] = deleted_count
            if errors:
                state["last_cleanup_status"] = "error"
                state["cleanup_pending"] = True
                result["status"] = "error"
                result["warning"] = "部分详情缓存未能清理，下次 Research 将继续尝试。"
            else:
                state["last_cleanup_at"] = current_iso
                state["last_cleanup_status"] = "success"
                state["cleanup_pending"] = False
                result["status"] = "success"

        state["version"] = STATE_VERSION
        state["last_use_at"] = current_iso
        try:
            _write_state(state_path, state)
        except OSError:
            result["status"] = "state_write_error"
            result["warning"] = "Research 缓存状态无法写入，本次不影响 Research 主流程。"

    return result


if __name__ == "__main__":
    print(json.dumps(check_and_cleanup(), ensure_ascii=False, indent=2))
