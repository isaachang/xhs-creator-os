"""Deterministic relevance labels for public Xiaohongshu research samples."""

from __future__ import annotations

from typing import Any


PET_TERMS = (
    "宠物",
    "宠物友好",
    "毛孩子",
    "带狗",
    "带宠物",
    "狗狗",
    "狗",
    "猫咪",
    "猫",
    "萌宠",
    "养狗",
    "养猫",
    "犬",
)
MALL_TERMS = (
    "商场",
    "购物中心",
    "商圈",
    "天环",
    "天河城",
    "太古汇",
    "正佳",
    "万菱汇",
    "广场",
    "天地",
)
VENUE_TERMS = MALL_TERMS + ("门店", "市集", "主题店", "餐厅", "咖啡", "公园", "活动")
TRAVEL_TERMS = (
    "回国",
    "入境",
    "出境",
    "旅行",
    "旅游",
    "航空",
    "飞机",
    "检疫",
    "托运",
)


def _text(record: dict[str, Any]) -> str:
    parts = [record.get("title"), record.get("body"), record.get("location")]
    raw = record.get("raw")
    if isinstance(raw, dict):
        parts.extend((raw.get("title"), raw.get("bodyText"), raw.get("desc"), raw.get("description"), raw.get("location")))
        hashtags = raw.get("hashtags")
        if isinstance(hashtags, list):
            parts.extend(hashtags)
    return " ".join(str(part) for part in parts if part not in (None, "")).lower()


def _hits(text: str, terms: tuple[str, ...]) -> list[str]:
    return [term for term in terms if term.lower() in text]


def classify_record(record: dict[str, Any], query: str | None) -> dict[str, Any]:
    """Return a reviewable label; this never deletes or mutates the source record."""
    text = _text(record)
    if not query:
        return {"status": "unknown", "score": 0, "reasons": ["没有搜索词，无法做意图匹配"]}

    query_text = query.lower()
    pet_hits = _hits(text, PET_TERMS)
    mall_hits = _hits(text, MALL_TERMS)
    venue_hits = _hits(text, VENUE_TERMS)
    travel_hits = _hits(text, TRAVEL_TERMS)
    query_pet = bool(_hits(query_text, PET_TERMS))
    query_mall = bool(_hits(query_text, MALL_TERMS))
    query_travel = bool(_hits(query_text, TRAVEL_TERMS))
    reasons: list[str] = []

    if query_mall and query_pet:
        if pet_hits and mall_hits:
            reasons = [f"宠物词: {', '.join(pet_hits[:3])}", f"商场词: {', '.join(mall_hits[:3])}"]
            return {"status": "relevant", "score": 100, "reasons": reasons}
        if pet_hits and venue_hits:
            reasons = [f"宠物词: {', '.join(pet_hits[:3])}", f"场景词但非明确商场: {', '.join(venue_hits[:3])}"]
            return {"status": "adjacent", "score": 60, "reasons": reasons}
        if mall_hits:
            return {"status": "adjacent", "score": 35, "reasons": [f"只有商场词: {', '.join(mall_hits[:3])}"]}
        if pet_hits:
            return {"status": "adjacent", "score": 35, "reasons": [f"只有宠物词: {', '.join(pet_hits[:3])}"]}
        return {"status": "noise", "score": 0, "reasons": ["未命中宠物词和商场词"]}

    if query_pet and query_travel:
        if pet_hits and travel_hits:
            return {"status": "relevant", "score": 100, "reasons": [f"宠物词: {', '.join(pet_hits[:3])}", f"出行词: {', '.join(travel_hits[:3])}"]}
        if pet_hits or travel_hits:
            return {"status": "adjacent", "score": 50, "reasons": ["只命中部分出行研究意图"]}
        return {"status": "noise", "score": 0, "reasons": ["未命中宠物出行词"]}

    query_terms = [term for term in PET_TERMS + MALL_TERMS + TRAVEL_TERMS if term.lower() in query_text]
    matched = [term for term in query_terms if term.lower() in text]
    if matched:
        return {"status": "relevant", "score": 80, "reasons": [f"命中搜索意图词: {', '.join(matched[:5])}"]}
    return {"status": "unknown", "score": 0, "reasons": ["当前规则没有足够证据判定相关性"]}


def annotate_record(record: dict[str, Any], query: str | None) -> dict[str, Any]:
    result = dict(record)
    label = classify_record(result, query)
    result["relevance_status"] = label["status"]
    result["relevance_score"] = label["score"]
    result["relevance_reasons"] = label["reasons"]
    return result
