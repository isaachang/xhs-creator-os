#!/usr/bin/env python3
"""Validate Xiaohongshu publish-copy length limits.

Input JSON must contain ``title`` and may contain ``body`` and ``tags``.
The validator counts visible characters conservatively: line breaks are
ignored, while spaces, punctuation, numbers, Latin text, and emoji count.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


TITLE_LIMIT = 20
TOTAL_LIMIT = 1000


def visible_length(value: Any) -> int:
    """Count characters except line breaks."""
    text = "" if value is None else str(value)
    return sum(1 for char in text if char not in "\r\n")


def validate(payload: dict[str, Any]) -> dict[str, Any]:
    title = payload.get("title", "")
    body = payload.get("body", "")
    tags = payload.get("tags", "")
    title_length = visible_length(title)
    body_length = visible_length(body)
    tags_length = visible_length(tags)
    total_length = title_length + body_length + tags_length

    errors: list[str] = []
    if title_length > TITLE_LIMIT:
        errors.append(f"title exceeds {TITLE_LIMIT} characters")
    if total_length > TOTAL_LIMIT:
        errors.append(f"title + body + tags exceeds {TOTAL_LIMIT} characters")

    return {
        "valid": not errors,
        "title_length": title_length,
        "body_length": body_length,
        "tags_length": tags_length,
        "total_length": total_length,
        "limits": {"title": TITLE_LIMIT, "total": TOTAL_LIMIT},
        "errors": errors,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate Xiaohongshu copy length")
    parser.add_argument("json_file", type=Path, help="JSON file containing title/body/tags")
    args = parser.parse_args()

    try:
        payload = json.loads(args.json_file.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        print(f"Unable to read JSON input: {exc}", file=sys.stderr)
        return 2
    if not isinstance(payload, dict):
        print("JSON input must be an object", file=sys.stderr)
        return 2

    result = validate(payload)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["valid"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
