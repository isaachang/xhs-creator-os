from __future__ import annotations

import importlib.util
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "scripts" / "xhs_api.py"
sys.path.insert(0, str(ROOT / "scripts"))
SPEC = importlib.util.spec_from_file_location("xhs_api", MODULE_PATH)
assert SPEC and SPEC.loader
xhs_api = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(xhs_api)


def test_normalizes_apify_shape() -> None:
    payload = {
        "items": [
            {
                "noteId": "abc",
                "title": "带狗回国时间线",
                "bodyText": "正文",
                "noteUrl": "https://example.test/note",
                "author": "作者",
                "authorProfileUrl": "https://example.test/user/author",
                "publishedAt": "2026-08-01 12:00:00",
                "likedCount": "1.2万",
                "collects": 300,
                "commentCount": 20,
                "shareCount": 5,
            }
        ]
    }
    records = xhs_api.normalize_payload(payload, "apify", "带狗回国")
    assert len(records) == 1
    assert records[0]["note_id"] == "abc"
    assert records[0]["author_name"] == "作者"
    assert records[0]["author_url"] == "https://example.test/user/author"
    assert records[0]["body"] == "正文"
    assert records[0]["likes"] == "1.2万"
    assert records[0]["saves"] == 300
    assert records[0]["url"] == "https://example.test/note"
    assert records[0]["query"] == "带狗回国"
    assert records[0]["relevance_status"] == "relevant"


def test_apify_uses_search_actor_contract(monkeypatch) -> None:
    captured = {}

    def fake_request(url, **kwargs):
        captured["url"] = url
        captured.update(kwargs)
        return [{"noteId": "abc", "title": "时间线"}]

    monkeypatch.setenv("APIFY_API_TOKEN", "test-token")
    monkeypatch.setattr(xhs_api, "request_json", fake_request)
    args = type("Args", (), {
        "keyword": "带狗回国",
        "limit": 3,
        "days": 7,
        "sort_type": "like_count_descending",
        "note_type": 0,
        "timeout": 180,
    })()

    records = xhs_api.apify_search(args)

    assert captured["url"].endswith("/acts/socialdatax~socialdatax-xhs-data-api/run-sync-get-dataset-items")
    assert captured["method"] == "POST"
    assert captured["headers"] == {"Authorization": "Bearer test-token"}
    assert captured["payload"] == {
        "operation": "search_notes",
        "keyword": "带狗回国",
        "sort_type": "like_count_descending",
        "note_type": "all",
        "publish_time_range": "week",
        "page_token": "",
        "max_items": 3,
        "auto_paginate": True,
    }
    assert records[0]["note_id"] == "abc"


def test_apify_token_prefers_environment(monkeypatch) -> None:
    monkeypatch.setenv("APIFY_API_TOKEN", "env-token")
    monkeypatch.setattr(xhs_api, "keychain_secret", lambda service: "keychain-token")
    assert xhs_api.apify_token() == "env-token"


def test_normalizes_socialdatax_search_shape() -> None:
    payload = [{
        "note_id": "social-1",
        "note_url": "https://www.xiaohongshu.com/explore/social-1?xsec_token=redacted",
        "title": "广州宠物友好商场",
        "summary": "搜索结果摘要",
        "author_name": "作者",
        "profile_url": "https://www.xiaohongshu.com/user/profile/social-author",
        "like_count": 12,
        "collect_count": 8,
        "comment_count": 3,
        "share_count": 2,
        "publish_time": 1786803942,
    }]
    records = xhs_api.normalize_payload(payload, "apify", "广州天河宠物友好商场")
    assert records[0]["author_name"] == "作者"
    assert records[0]["author_url"] == "https://www.xiaohongshu.com/user/profile/social-author"
    assert records[0]["body"] == "搜索结果摘要"
    assert records[0]["likes"] == 12
    assert records[0]["url"].startswith("https://www.xiaohongshu.com/explore/social-1")


def test_apify_detail_uses_exact_note_url(monkeypatch) -> None:
    captured = {}

    def fake_request(url, **kwargs):
        captured.update(kwargs)
        return [{"note_id": "social-1", "note_url": "http://xhslink.com/o/example", "summary": "详情摘要"}]

    monkeypatch.setenv("APIFY_API_TOKEN", "test-token")
    monkeypatch.setattr(xhs_api, "request_json", fake_request)
    args = type("Args", (), {"url": "http://xhslink.com/o/example", "timeout": 180})()
    records = xhs_api.apify_detail(args)
    assert captured["payload"] == {"operation": "get_note_detail", "note_url": "http://xhslink.com/o/example"}
    assert records[0]["url"] == "http://xhslink.com/o/example"


def test_apify_detail_adapts_rednote_host_for_actor(monkeypatch) -> None:
    captured = {}

    def fake_request(url, **kwargs):
        if url.endswith("/users/me"):
            return {"data": {"plan": {"id": "STARTER"}, "isPaying": True}}
        captured.update(kwargs)
        return [{"note_id": "social-1", "note_url": "https://www.xiaohongshu.com/explore/social-1"}]

    monkeypatch.setenv("APIFY_API_TOKEN", "test-token")
    monkeypatch.setattr(xhs_api, "request_json", fake_request)
    args = type("Args", (), {"url": "https://www.rednote.com/explore/social-1?xsec_token=token", "timeout": 180})()
    xhs_api.apify_detail(args)
    assert captured["payload"]["note_url"] == "https://www.xiaohongshu.com/explore/social-1?xsec_token=token"


def test_apify_detail_retries_xhslink_with_resolved_long_url(monkeypatch) -> None:
    captured_urls = []
    short_url = "http://xhslink.com/o/example"
    long_url = "https://www.xiaohongshu.com/explore/social-1?xsec_token=token"

    def fake_request(url, **kwargs):
        note_url = kwargs["payload"]["note_url"]
        captured_urls.append(note_url)
        if note_url == short_url:
            raise xhs_api.ProviderError("short actor failure")
        return [{"note_id": "social-1", "note_url": long_url, "summary": "详情摘要"}]

    monkeypatch.setenv("APIFY_API_TOKEN", "test-token")
    monkeypatch.setattr(xhs_api, "ensure_socialdatax_access", lambda: None)
    monkeypatch.setattr(xhs_api, "request_json", fake_request)
    monkeypatch.setattr(xhs_api, "resolve_xhslink_url", lambda value, timeout: long_url)
    args = type("Args", (), {"url": short_url, "timeout": 180, "refresh": True})()

    records = xhs_api.apify_detail(args)

    assert captured_urls == [short_url, long_url]
    assert records[0]["note_id"] == "social-1"


def test_canonicalizes_discovery_item_route() -> None:
    value = "https://www.xiaohongshu.com/discovery/item/social-1?xsec_token=token"
    assert xhs_api.canonicalize_xiaohongshu_url(value) == "https://www.xiaohongshu.com/explore/social-1?xsec_token=token"


def test_apify_detail_reports_both_xhslink_failures(monkeypatch) -> None:
    short_url = "http://xhslink.com/o/example"

    def fake_request(url, **kwargs):
        raise xhs_api.ProviderError("short actor failure")

    monkeypatch.setenv("APIFY_API_TOKEN", "test-token")
    monkeypatch.setattr(xhs_api, "ensure_socialdatax_access", lambda: None)
    monkeypatch.setattr(xhs_api, "request_json", fake_request)
    monkeypatch.setattr(
        xhs_api,
        "resolve_xhslink_url",
        lambda value, timeout: (_ for _ in ()).throw(xhs_api.ProviderError("redirect timeout")),
    )
    args = type("Args", (), {"url": short_url, "timeout": 180, "refresh": True})()

    try:
        xhs_api.apify_detail(args)
    except xhs_api.ProviderError as exc:
        message = str(exc)
    else:
        raise AssertionError("expected ProviderError")

    assert "short actor failure" in message
    assert "redirect timeout" in message


def test_deduplicates_records() -> None:
    payload = [{"id": "same", "title": "A"}, {"id": "same", "title": "B"}]
    records = xhs_api.normalize_payload(payload, "test", "query")
    assert len(records) == 1


def test_relevance_filter_distinguishes_mall_sample_from_noise() -> None:
    direct = xhs_api.normalize_payload(
        [{"noteId": "direct", "title": "天环广场带狗逛街攻略", "bodyText": "宠物友好入口和商场规则"}],
        "apify",
        "广州天河区宠物友好商场",
    )[0]
    noise = xhs_api.normalize_payload(
        [{"noteId": "noise", "title": "有鸡市集周末活动", "bodyText": "咕咕鸡派对"}],
        "apify",
        "广州天河区宠物友好商场",
    )[0]
    assert direct["relevance_status"] == "relevant"
    assert noise["relevance_status"] == "noise"
