#!/usr/bin/env python3
"""Build final MediaCrawler research from Creator OS relevance decisions.

The Agent decides relevance for the active request. This script only validates
the selected IDs, merges fetched detail records, and writes stable output.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path


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
            for field in ("url", "title", "body", "author_id", "author_name", "author_url", "published_at", "likes", "saves", "comments", "shares", "raw"):
                if detail.get(field) not in (None, ""):
                    candidate[field] = detail[field]
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
    print(json.dumps({"candidate_count": len(candidates), "detail_count": len(details), "selected_count": len(final)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
