from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import research_cache  # noqa: E402


UTC = timezone.utc


def read_state(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def test_first_use_records_state_without_clearing(tmp_path: Path) -> None:
    cache = tmp_path / "note-detail-cache"
    cache.mkdir()
    cached = cache / "note-first.json"
    cached.write_text("[]", encoding="utf-8")
    state = tmp_path / "research-cache-state.json"

    result = research_cache.check_and_cleanup(
        now=datetime(2026, 8, 24, tzinfo=UTC),
        state_path=state,
        cache_dir=cache,
        lock_path=tmp_path / "lock",
    )

    assert result["due"] is False
    assert result["status"] == "not_due"
    assert cached.is_file()
    assert read_state(state)["last_use_at"] == "2026-08-24T00:00:00Z"


def test_cleanup_only_happens_after_fourteen_idle_days(tmp_path: Path) -> None:
    cache = tmp_path / "note-detail-cache"
    cache.mkdir()
    first = cache / "note-first.json"
    second = cache / "url-second.json"
    ignored = cache / "keep.txt"
    for path in (first, second, ignored):
        path.write_text("content", encoding="utf-8")
    state = tmp_path / "research-cache-state.json"
    state.write_text(
        json.dumps(
            {
                "version": 1,
                "last_use_at": "2026-08-01T00:00:00Z",
                "last_cleanup_at": None,
                "last_cleanup_status": "never",
                "last_cleanup_deleted_count": 0,
                "cleanup_pending": False,
            }
        ),
        encoding="utf-8",
    )

    not_due = research_cache.check_and_cleanup(
        now=datetime(2026, 8, 14, tzinfo=UTC) - timedelta(seconds=1),
        state_path=state,
        cache_dir=cache,
        lock_path=tmp_path / "lock",
    )
    assert not_due["due"] is False
    assert first.is_file() and second.is_file()

    due = research_cache.check_and_cleanup(
        now=datetime(2026, 8, 28, tzinfo=UTC),
        state_path=state,
        cache_dir=cache,
        lock_path=tmp_path / "lock",
    )
    assert due["due"] is True
    assert due["status"] == "success"
    assert due["deleted_count"] == 2
    assert not first.exists() and not second.exists()
    assert ignored.is_file()
    saved = read_state(state)
    assert saved["cleanup_pending"] is False
    assert saved["last_cleanup_at"] == "2026-08-28T00:00:00Z"


def test_pending_cleanup_retries_on_next_use(tmp_path: Path, monkeypatch) -> None:
    cache = tmp_path / "note-detail-cache"
    cache.mkdir()
    cached = cache / "note-retry.json"
    cached.write_text("content", encoding="utf-8")
    state = tmp_path / "research-cache-state.json"
    state.write_text(
        json.dumps(
            {
                "version": 1,
                "last_use_at": "2026-08-24T00:00:00Z",
                "last_cleanup_at": None,
                "last_cleanup_status": "error",
                "last_cleanup_deleted_count": 0,
                "cleanup_pending": True,
            }
        ),
        encoding="utf-8",
    )

    original_delete = research_cache._delete_cache_files
    monkeypatch.setattr(research_cache, "_delete_cache_files", lambda _cache: (0, ["note-retry.json"]))
    failed = research_cache.check_and_cleanup(
        now=datetime(2026, 8, 24, 1, tzinfo=UTC),
        state_path=state,
        cache_dir=cache,
        lock_path=tmp_path / "lock",
    )
    assert failed["status"] == "error"
    assert read_state(state)["cleanup_pending"] is True
    assert cached.is_file()

    monkeypatch.setattr(research_cache, "_delete_cache_files", original_delete)
    retried = research_cache.check_and_cleanup(
        now=datetime(2026, 8, 24, 2, tzinfo=UTC),
        state_path=state,
        cache_dir=cache,
        lock_path=tmp_path / "lock",
    )
    assert retried["status"] == "success"
    assert read_state(state)["cleanup_pending"] is False
    assert not cached.exists()
