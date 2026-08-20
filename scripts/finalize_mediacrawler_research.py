#!/usr/bin/env python3
"""Build final MediaCrawler research from Creator OS relevance decisions.

The Agent decides relevance for the active request. This script only validates
the selected IDs, merges fetched detail records, and writes stable output.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from store import DEFAULT_DB, connect, import_research
from xhs_api import write_note_detail_cache


def load_array(path: Path) -> list[dict]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, list):
        raise ValueError(f"Expected a JSON array: {path}")
    return [item for item in payload if isinstance(item, dict)]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--candidates", required=True, type=Path)
    parser.add_argument("--details", required=True, type=Path)
    parser.add_argument("--selection", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--limit", default=15, type=int)
    args = parser.parse_args()

    candidates = {str(item.get("note_id") or ""): item for item in load_array(args.candidates)}
    details = {str(item.get("note_id") or ""): item for item in load_array(args.details)}
    selection = json.loads(args.selection.read_text(encoding="utf-8"))
    decisions = selection.get("decisions") if isinstance(selection, dict) else None
    if not isinstance(decisions, list):
        raise ValueError("Selection must contain a decisions array")

    final: list[dict] = []
    seen: set[str] = set()
    for decision in decisions:
        if not isinstance(decision, dict) or decision.get("status") != "directly_relevant":
            continue
        note_id = str(decision.get("note_id") or "")
        if not note_id or note_id in seen or note_id not in candidates:
            continue
        candidate = dict(candidates[note_id])
        detail = details.get(note_id)
        if detail:
            for field in (
                "url", "title", "body", "author_id", "author_name", "author_url",
                "published_at", "note_type", "content_level", "detail_status",
                "likes", "saves", "comments", "shares", "raw",
            ):
                if detail.get(field) not in (None, ""):
                    candidate[field] = detail[field]
            # Older local detail files predate the shared content-level fields.
            # A successfully matched detail still has stronger provenance than
            # its search card, so normalize it here instead of leaving it as
            # card-level data forever.
            candidate["content_level"] = str(detail.get("content_level") or "detail")
            candidate["detail_status"] = str(detail.get("detail_status") or "success")
        else:
            # The record was selected for detail verification but no usable
            # detail returned. Keep the card rather than pretending it has
            # a full body; Compare and Rewrite can request it later.
            candidate["detail_status"] = "unavailable"
        candidate["relevance_status"] = "directly_relevant"
        candidate["relevance_reasons"] = decision.get("reasons") or []
        final.append(candidate)
        seen.add(note_id)
        if len(final) >= max(1, args.limit):
            break

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(final, ensure_ascii=False, indent=2), encoding="utf-8")
    screening_path = args.output.with_name(f"{args.output.stem}.screening.json")
    screening_path.write_text(json.dumps(selection, ensure_ascii=False, indent=2)
)
    manifest_path = args.output.with_name(f"{args.output.stem}.manifest.json")
    manifest_path.write_text(
        json.dumps(
            {
                "provider": "media",
                "operation": "research",
                "candidate_count": len(candidates),
                "detail_count": len(details),
                "returned_count": len(final),
                "sources": sorted({str(item.get("source") or "mediacrawler") for item in final}),
            },
            ensure_ascii=False,
            indent=2,
        ) + "\n",
        encoding="utf-8",
    )

    # Store successful local details under the same note-id cache used by the
    # Apify adapter. Future Rewrite/Compare calls can reuse them regardless of
    # which provider supplied the initial search result.
    if details:
        cache_details = []
        for detail in details.values():
            cached_detail = dict(detail)
            cached_detail.setdefault("note_type", "unknown")
            cached_detail.setdefault("content_level", "detail")
            cached_detail.setdefault("detail_status", "success")
            cache_details.append(cached_detail)
        write_note_detail_cache(cache_details)

    # Make final research discoverable by later conversations. Candidate-only
    # files are intentionally not imported because they are not final samples.
    with connect(DEFAULT_DB) as conn:
        for record in final:
            import_research(
                conn,
                record,
                str(record.get("source") or "mediacrawler"),
                str(record.get("query") or "") or None,
                None,
            )
        conn.commit()
    print(json.dumps({"candidate_count": len(candidates), "detail_count": len(details), "selected_count": len(final)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
