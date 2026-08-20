from __future__ import annotations

import sys
from pathlib import Path


SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import xhs_provider  # noqa: E402


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
