from __future__ import annotations

import sys
import subprocess
import json
from argparse import Namespace
from datetime import datetime, timezone
from pathlib import Path


SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import xhs_provider  # noqa: E402


def write_media_research_cache(run_dir: Path, *, query: str, records: int = 2) -> None:
    run_dir.mkdir(parents=True)
    now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    payload = [
        {"note_id": f"note-{index}", "title": f"sample {index}", "source": "mediacrawler"}
        for index in range(records)
    ]
    (run_dir / "research.json").write_text(json.dumps(payload), encoding="utf-8")
    (run_dir / "research.candidates.manifest.json").write_text(
        json.dumps(
            {
                "provider": "media",
                "operation": "research_candidates",
                "query": query,
                "sort_type": "general",
                "note_type": "image",
                "publish_days": 3650,
                "candidate_count": 30,
                "captured_at": now,
            }
        ),
        encoding="utf-8",
    )
    (run_dir / "research.manifest.json").write_text(
        json.dumps({"provider": "media", "operation": "research", "returned_count": records, "captured_at": now}),
        encoding="utf-8",
    )


def media_search_args(keyword: str, *, refresh: bool = False) -> Namespace:
    return Namespace(
        source="media",
        refresh=refresh,
        keyword=keyword,
        sort_type="general",
        content_type="image",
        days=3650,
        limit=2,
    )


def test_auto_prefers_apify_when_configured(monkeypatch) -> None:
    monkeypatch.setattr(xhs_provider.xhs_api, "apify_token", lambda: "configured")
    monkeypatch.setattr(xhs_provider, "media_installed", lambda: True)
    assert xhs_provider.resolve_source("auto") == "apify"


def test_auto_uses_media_when_apify_missing(monkeypatch) -> None:
    monkeypatch.setattr(xhs_provider.xhs_api, "apify_token", lambda: "")
    monkeypatch.setattr(xhs_provider, "media_installed", lambda: True)
    assert xhs_provider.resolve_source("auto") == "media"


def test_media_root_can_be_kept_in_local_env(monkeypatch) -> None:
    monkeypatch.delenv("MEDIA_CRAWLER_ROOT", raising=False)
    monkeypatch.setattr(xhs_provider.xhs_api, "local_env_secret", lambda name: "/tmp/media" if name == "MEDIA_CRAWLER_ROOT" else "")
    assert xhs_provider.media_root() == Path("/tmp/media")


def test_explicit_apify_requires_key(monkeypatch) -> None:
    monkeypatch.setattr(xhs_provider.xhs_api, "apify_token", lambda: "")
    try:
        xhs_provider.resolve_source("apify")
    except xhs_provider.ProviderRouterError as exc:
        assert "Apify" in str(exc)
    else:
        raise AssertionError("expected missing-key error")


def test_media_worker_reuses_dedicated_cdp_session(monkeypatch, tmp_path: Path) -> None:
    captured: dict[str, object] = {}

    def fake_run(*_args, **kwargs):
        captured["env"] = kwargs["env"]
        return subprocess.CompletedProcess(args=[], returncode=0, stdout="", stderr="")

    monkeypatch.setattr(xhs_provider, "ensure_media_session", lambda root, _profile: captured.setdefault("session", root))
    monkeypatch.setattr(xhs_provider.subprocess, "run", fake_run)
    xhs_provider.run_media(
        ["--platform", "xhs", "--type", "search", "--headless", "yes"],
        root=tmp_path,
        profile_name="creator-os-rednote-profile",
        site="rednote",
    )
    assert captured["session"] == tmp_path
    assert captured["env"]["CREATOR_OS_CDP_CONNECT_EXISTING"] == "1"
    assert captured["env"]["CREATOR_OS_CDP_PORT"] == str(xhs_provider.MEDIA_SESSION_PORT)
    assert captured["env"]["CREATOR_OS_PROFILE_DIR"].endswith("creator-os-rednote-profile")
    assert captured["env"]["CREATOR_OS_BACKGROUND_MODE"] == "1"


def test_media_auth_accepts_confirmed_browser_session(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(xhs_provider, "media_root", lambda: tmp_path)
    monkeypatch.setattr(
        xhs_provider,
        "run_media",
        lambda *_args, **_kwargs: subprocess.CompletedProcess(
            args=[], returncode=0, stdout="confirmed dedicated browser session", stderr=""
        ),
    )
    result = xhs_provider.media_auth(type("Args", (), {"media_browser": "background", "timeout": 30, "site": "auto"})())
    assert result["authenticated"] is True
    assert result["verification"] == "已通过专用浏览器会话确认"


def test_minimize_media_testing_windows_on_macos(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def fake_run(command, **kwargs):
        captured["command"] = command
        captured["kwargs"] = kwargs
        return subprocess.CompletedProcess(args=command, returncode=0, stdout="", stderr="")

    monkeypatch.setattr(xhs_provider.sys, "platform", "darwin")
    monkeypatch.setattr(xhs_provider.subprocess, "run", fake_run)

    assert xhs_provider.minimize_media_testing_windows() is True
    assert captured["command"][0] == "/usr/bin/osascript"
    assert "is running" in captured["command"][-1]


def test_media_details_reads_each_url_and_deduplicates(monkeypatch, tmp_path: Path) -> None:
    output = tmp_path / "details.json"
    calls: list[list[str]] = []

    monkeypatch.setattr(xhs_provider, "media_root", lambda: tmp_path)
    monkeypatch.setattr(xhs_provider, "media_profile_for", lambda *_args, **_kwargs: ("creator-os-rednote-profile", "rednote"))
    monkeypatch.setattr(xhs_provider.xhs_api, "write_note_detail_cache", lambda *_args: None)

    def fake_run_media(command, **_kwargs):
        calls.append(command)
        destination = Path(command[command.index("--creator_os_output") + 1])
        url = command[command.index("--specified_id") + 1]
        note_id = "note-a" if url.endswith("a") else "note-b"
        destination.write_text(json.dumps([{"note_id": note_id, "url": url}]), encoding="utf-8")
        return subprocess.CompletedProcess(args=[], returncode=0, stdout="", stderr="")

    monkeypatch.setattr(xhs_provider, "run_media", fake_run_media)
    result = xhs_provider.details_media(
        Namespace(urls=["https://www.rednote.com/explore/a", "https://www.rednote.com/explore/b"], output=output, media_browser="background", timeout=30)
    )

    assert result["records"] == 2
    assert len(calls) == 2
    assert all("," not in command[command.index("--specified_id") + 1] for command in calls)
    assert [record["note_id"] for record in json.loads(output.read_text(encoding="utf-8"))] == ["note-a", "note-b"]


def test_cached_details_rejects_mismatched_legacy_batch_record(monkeypatch) -> None:
    requested = "https://www.rednote.com/explore/right-note"
    monkeypatch.setattr(
        xhs_provider.xhs_api,
        "read_note_detail_cache",
        lambda _url: [{"note_id": "wrong-note", "url": "https://www.rednote.com/explore/wrong-note"}],
    )

    cached, missing = xhs_provider.cached_detail_records([requested])

    assert cached == []
    assert missing == [requested]


def test_visible_media_auth_promotes_only_after_search_smoke(monkeypatch, tmp_path: Path) -> None:
    started: list[str] = []
    monkeypatch.setattr(xhs_provider, "media_root", lambda: tmp_path)
    monkeypatch.setattr(
        xhs_provider,
        "media_profile_for",
        lambda *_args, **_kwargs: ("creator-os-bootstrap-profile", "rednote"),
    )
    monkeypatch.setattr(
        xhs_provider,
        "run_media",
        lambda *_args, **_kwargs: subprocess.CompletedProcess(
            args=[], returncode=0, stdout="confirmed dedicated browser session", stderr=""
        ),
    )
    monkeypatch.setattr(xhs_provider, "run_media_smoke_search", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        xhs_provider,
        "promote_media_profile",
        lambda *_args, **_kwargs: {"profile": "creator-os-rednote-profile", "site": "rednote"},
    )
    monkeypatch.setattr(
        xhs_provider,
        "ensure_media_session",
        lambda _root, profile: started.append(profile),
    )
    monkeypatch.setattr(xhs_provider, "minimize_media_testing_windows", lambda: True)

    result = xhs_provider.media_auth(type("Args", (), {"media_browser": "visible", "timeout": 30, "site": "auto"})())

    assert result["authenticated"] is True
    assert result["profile"] == "creator-os-rednote-profile"
    assert started == ["creator-os-rednote-profile"]
    state = xhs_provider.load_media_auth_state(tmp_path)
    assert state["active_site"] == "rednote"
    assert state["sites"]["rednote"]["profile"] == "creator-os-rednote-profile"
    assert state["sites"]["rednote"]["validation"] == "search_smoke_success"
    assert result["browser_window"] == "Chrome Testing 已自动最小化。"


def test_media_auth_state_keeps_sites_isolated(tmp_path: Path) -> None:
    state = {
        "version": 1,
        "active_site": "rednote",
        "sites": {
            "xiaohongshu": {"profile": "creator-os-xiaohongshu-profile", "validation": "search_smoke_success"},
            "rednote": {"profile": "creator-os-rednote-profile", "validation": "search_smoke_success"},
        },
    }
    (tmp_path / "browser_data" / "creator-os-rednote-profile").mkdir(parents=True)
    (tmp_path / "browser_data" / "creator-os-xiaohongshu-profile").mkdir(parents=True)
    xhs_provider.write_media_auth_state(tmp_path, state)
    rednote_profile, rednote_site = xhs_provider.media_profile_for(tmp_path)
    domestic_profile, domestic_site = xhs_provider.media_profile_for(tmp_path, requested_site="xiaohongshu")
    assert (rednote_profile, rednote_site) == ("creator-os-rednote-profile", "rednote")
    assert (domestic_profile, domestic_site) == ("creator-os-xiaohongshu-profile", "xiaohongshu")


def test_unverified_media_profile_cannot_run_background(tmp_path: Path) -> None:
    try:
        xhs_provider.media_profile_for(tmp_path)
    except xhs_provider.ProviderRouterError as exc:
        assert "可用验证" in str(exc)
    else:
        raise AssertionError("expected media auth validation error")


def test_media_research_cache_requires_exact_compatible_query(tmp_path: Path) -> None:
    runs_root = tmp_path / "runs"
    write_media_research_cache(runs_root / "guangzhou-parks", query="广州 宠物友好公园")

    hit = xhs_provider.find_cached_media_research(media_search_args("广州 宠物友好公园"), runs_root=runs_root)
    partial = xhs_provider.find_cached_media_research(media_search_args("广州 天河 宠物友好公园"), runs_root=runs_root)

    assert hit is not None
    assert len(hit["records"]) == 2
    assert partial is None


def test_media_research_cache_refresh_bypasses_exact_hit(tmp_path: Path) -> None:
    runs_root = tmp_path / "runs"
    write_media_research_cache(runs_root / "guangzhou-parks", query="广州 宠物友好公园")

    assert xhs_provider.find_cached_media_research(
        media_search_args("广州 宠物友好公园", refresh=True), runs_root=runs_root
    ) is None


def test_main_returns_media_cache_before_provider_resolution(monkeypatch, tmp_path: Path) -> None:
    output = tmp_path / "result.json"
    cached = {
        "records": [{"note_id": "cached-note", "title": "cached", "source": "mediacrawler"}],
        "captured_at": "2026-08-24T00:00:00Z",
        "origin": tmp_path / "origin.json",
    }
    monkeypatch.setattr(xhs_provider, "maintain_research_cache", lambda _command: None)
    monkeypatch.setattr(xhs_provider, "find_cached_media_research", lambda _args: cached)
    monkeypatch.setattr(
        xhs_provider,
        "resolve_source",
        lambda _source: (_ for _ in ()).throw(AssertionError("provider must not be resolved on cache hit")),
    )
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "xhs_provider.py", "search", "广州 宠物友好公园", "--source", "media",
            "--output", str(output),
        ],
    )

    assert xhs_provider.main() == 0
    assert json.loads(output.read_text(encoding="utf-8"))[0]["note_id"] == "cached-note"


def test_media_creator_cache_requires_same_creator_and_sufficient_top_n(tmp_path: Path) -> None:
    runs_root = tmp_path / "runs"
    run_dir = runs_root / "creator"
    run_dir.mkdir(parents=True)
    now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    (run_dir / "creator-top.json").write_text(
        json.dumps([{"note_id": "one"}, {"note_id": "two"}, {"note_id": "three"}]), encoding="utf-8"
    )
    (run_dir / "creator-top.manifest.json").write_text(
        json.dumps(
            {
                "provider": "media",
                "operation": "creator_top",
                "creator_url": "https://www.xiaohongshu.com/user/profile/creator-a",
                "requested_top": 3,
                "scan_limit": 120,
                "captured_at": now,
            }
        ),
        encoding="utf-8",
    )
    exact = Namespace(
        creator_url="https://www.xiaohongshu.com/user/profile/creator-a",
        top=2,
        scan_limit=120,
        refresh=False,
    )
    different_creator = Namespace(
        creator_url="https://www.xiaohongshu.com/user/profile/creator-b",
        top=2,
        scan_limit=120,
        refresh=False,
    )
    too_many = Namespace(
        creator_url="https://www.xiaohongshu.com/user/profile/creator-a",
        top=5,
        scan_limit=120,
        refresh=False,
    )

    assert xhs_provider.find_cached_media_creator(exact, runs_root=runs_root) is not None
    assert xhs_provider.find_cached_media_creator(different_creator, runs_root=runs_root) is None
    assert xhs_provider.find_cached_media_creator(too_many, runs_root=runs_root) is None


def test_main_returns_all_cached_details_before_provider_resolution(monkeypatch, tmp_path: Path) -> None:
    output = tmp_path / "details.json"
    monkeypatch.setattr(xhs_provider, "maintain_research_cache", lambda _command: None)
    monkeypatch.setattr(
        xhs_provider,
        "cached_detail_records",
        lambda _urls: ([{"note_id": "cached-note", "title": "cached"}], []),
    )
    monkeypatch.setattr(
        xhs_provider,
        "resolve_source",
        lambda _source: (_ for _ in ()).throw(AssertionError("provider must not be resolved on all-cache hit")),
    )
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "xhs_provider.py", "details", "https://www.xiaohongshu.com/explore/cached-note",
            "--source", "media", "--output", str(output),
        ],
    )

    assert xhs_provider.main() == 0
    assert json.loads(output.read_text(encoding="utf-8"))[0]["note_id"] == "cached-note"
