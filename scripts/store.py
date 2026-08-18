#!/usr/bin/env python3
"""Initialize and import local Xiaohongshu research/history data."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DB = ROOT / "data" / "creator-os.sqlite3"

ALIASES: dict[str, tuple[str, ...]] = {
    "note_id": ("note_id", "id", "笔记id", "笔记ID", "内容id", "内容ID"),
    "url": ("note_url", "url", "笔记链接", "链接"),
    "title": ("title", "note_title", "笔记标题", "标题"),
    "body": ("summary", "desc", "content", "body", "note_desc", "正文", "笔记正文"),
    "author_id": ("user_id", "author_id", "creator_id", "作者id", "作者ID"),
    "author_name": ("author_name", "nickname", "author", "user_name", "作者", "昵称"),
    "published_at": ("time", "publish_time", "publish_at", "published_at", "create_time", "createTime", "发布时间", "发布日期"),
    "captured_at": ("captured_at", "last_modify_ts", "add_ts", "采集时间", "数据日期", "统计日期"),
    "query": ("query", "keyword", "关键词", "搜索词"),
    "note_type": ("note_type", "type", "content_type", "笔记类型", "内容类型"),
    "pillar": ("pillar", "content_pillar", "内容支柱", "栏目"),
    "objective": ("objective", "goal", "目标"),
    "experiment": ("experiment", "test", "实验"),
    "likes": ("liked_count", "likedCount", "likes", "like", "like_count", "点赞", "点赞数"),
    "saves": ("saves", "collect_count", "collected_count", "collectedCount", "collects", "collect", "saved_count", "收藏", "收藏数"),
    "comments": ("comment_count", "commentsCount", "comments", "comment", "评论", "评论数"),
    "shares": ("share_count", "shared_count", "sharedCount", "shares", "share", "分享", "分享数", "转发数"),
    "impressions": ("impressions", "impression", "exposures", "曝光", "曝光量", "展现量"),
    "views": ("views", "view", "read", "view_count", "阅读", "阅读量", "观看量", "播放量"),
    "profile_visits": ("profile_visits", "profile_visit", "主页访问", "主页访问量"),
    "followers_gained": ("followers_gained", "follow", "涨粉", "新增关注", "新增粉丝"),
    "avg_duration": ("avg_duration", "duration", "average_duration", "平均观看时长", "平均阅读时长"),
}

SCHEMA = """
PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;

CREATE TABLE IF NOT EXISTS notes (
    note_id TEXT PRIMARY KEY,
    url TEXT,
    title TEXT,
    body TEXT,
    author_id TEXT,
    author_name TEXT,
    published_at TEXT,
    source TEXT NOT NULL,
    is_own INTEGER NOT NULL DEFAULT 0,
    note_type TEXT,
    pillar TEXT,
    objective TEXT,
    experiment TEXT,
    raw_json TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS metric_snapshots (
    note_id TEXT NOT NULL,
    captured_at TEXT NOT NULL,
    source TEXT NOT NULL,
    likes REAL,
    saves REAL,
    comments REAL,
    shares REAL,
    impressions REAL,
    views REAL,
    profile_visits REAL,
    followers_gained REAL,
    avg_duration REAL,
    raw_json TEXT NOT NULL,
    PRIMARY KEY (note_id, captured_at, source),
    FOREIGN KEY (note_id) REFERENCES notes(note_id)
);

CREATE TABLE IF NOT EXISTS research_hits (
    query TEXT NOT NULL,
    note_id TEXT NOT NULL,
    captured_at TEXT NOT NULL,
    published_at TEXT,
    title TEXT,
    author_name TEXT,
    source TEXT NOT NULL,
    likes REAL,
    saves REAL,
    comments REAL,
    shares REAL,
    raw_json TEXT NOT NULL,
    PRIMARY KEY (query, note_id, captured_at, source)
);

CREATE INDEX IF NOT EXISTS idx_notes_own_published ON notes(is_own, published_at);
CREATE INDEX IF NOT EXISTS idx_metrics_note_time ON metric_snapshots(note_id, captured_at);
CREATE INDEX IF NOT EXISTS idx_research_query_time ON research_hits(query, captured_at);
"""


def now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def first(record: dict[str, Any], field: str) -> Any:
    for key in ALIASES[field]:
        if key in record and record[key] not in (None, ""):
            return record[key]
    return None


def parse_count(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip().replace(",", "").replace("+", "")
    if not text or text.lower() in {"unknown", "none", "null", "-", "--"}:
        return None
    multipliers = {"万": 10000, "w": 10000, "k": 1000, "千": 1000}
    match = re.fullmatch(r"(-?\d+(?:\.\d+)?)\s*([万wWkK千]?)", text)
    if not match:
        return None
    number = float(match.group(1))
    suffix = match.group(2).lower()
    return number * multipliers.get(suffix, 1)


def normalize_time(value: Any, fallback: str | None = None) -> str | None:
    if value in (None, ""):
        return fallback
    if isinstance(value, (int, float)) or str(value).strip().isdigit():
        number = float(value)
        if number > 10_000_000_000:
            number /= 1000
        try:
            return datetime.fromtimestamp(number, tz=timezone.utc).astimezone().isoformat(timespec="seconds")
        except (OverflowError, OSError, ValueError):
            return fallback
    text = str(value).strip().replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(text)
        if parsed.tzinfo is None:
            parsed = parsed.astimezone()
        return parsed.isoformat(timespec="seconds")
    except ValueError:
        for fmt in ("%Y/%m/%d %H:%M", "%Y-%m-%d %H:%M", "%Y/%m/%d", "%Y-%m-%d"):
            try:
                return datetime.strptime(text, fmt).astimezone().isoformat(timespec="seconds")
            except ValueError:
                continue
    return fallback


def stable_note_id(record: dict[str, Any]) -> str:
    direct = first(record, "note_id")
    if direct:
        return str(direct)
    basis = str(first(record, "url") or first(record, "title") or json.dumps(record, ensure_ascii=False, sort_keys=True))
    return "local-" + hashlib.sha256(basis.encode("utf-8")).hexdigest()[:20]


def resolve_own_note_id(conn: sqlite3.Connection, record: dict[str, Any]) -> str:
    direct = first(record, "note_id")
    if direct:
        return str(direct)
    url = first(record, "url")
    if url:
        match = conn.execute("SELECT note_id FROM notes WHERE url=?", (str(url),)).fetchone()
        if match:
            return str(match[0])
    title = first(record, "title")
    if title:
        matches = conn.execute("SELECT note_id FROM notes WHERE title=? AND is_own=1", (str(title),)).fetchall()
        if len(matches) == 1:
            return str(matches[0][0])
    return stable_note_id(record)


def iter_files(paths: Iterable[Path]) -> Iterable[Path]:
    supported = {".csv", ".json", ".jsonl", ".ndjson"}
    for path in paths:
        if path.is_dir():
            yield from (p for p in sorted(path.rglob("*")) if p.suffix.lower() in supported)
        elif path.suffix.lower() in supported:
            yield path


def read_records(path: Path) -> Iterable[dict[str, Any]]:
    suffix = path.suffix.lower()
    if suffix == ".csv":
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            yield from csv.DictReader(handle)
        return
    if suffix in {".jsonl", ".ndjson"}:
        with path.open("r", encoding="utf-8-sig") as handle:
            for line_no, line in enumerate(handle, start=1):
                if not line.strip():
                    continue
                value = json.loads(line)
                if not isinstance(value, dict):
                    raise ValueError(f"{path}:{line_no} is not a JSON object")
                yield value
        return
    with path.open("r", encoding="utf-8-sig") as handle:
        value = json.load(handle)
    if isinstance(value, list):
        for item in value:
            if isinstance(item, dict):
                yield item
    elif isinstance(value, dict):
        for key in ("data", "items", "notes", "records", "list"):
            if isinstance(value.get(key), list):
                yield from (item for item in value[key] if isinstance(item, dict))
                return
        yield value


def connect(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.executescript(SCHEMA)
    return conn


def import_research(
    conn: sqlite3.Connection,
    record: dict[str, Any],
    source: str,
    query_override: str | None,
    captured_override: str | None,
) -> None:
    captured_at = normalize_time(captured_override or first(record, "captured_at"), now_iso())
    query = query_override or first(record, "query") or "unlabeled"
    values = (
        str(query),
        stable_note_id(record),
        captured_at,
        normalize_time(first(record, "published_at")),
        first(record, "title"),
        first(record, "author_name"),
        source,
        parse_count(first(record, "likes")),
        parse_count(first(record, "saves")),
        parse_count(first(record, "comments")),
        parse_count(first(record, "shares")),
        json.dumps(record, ensure_ascii=False, sort_keys=True),
    )
    conn.execute(
        """INSERT INTO research_hits
        (query,note_id,captured_at,published_at,title,author_name,source,likes,saves,comments,shares,raw_json)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
        ON CONFLICT(query,note_id,captured_at,source) DO UPDATE SET
        published_at=excluded.published_at,title=excluded.title,author_name=excluded.author_name,
        likes=excluded.likes,saves=excluded.saves,comments=excluded.comments,shares=excluded.shares,
        raw_json=excluded.raw_json""",
        values,
    )


def import_own(
    conn: sqlite3.Connection,
    record: dict[str, Any],
    source: str,
    captured_override: str | None,
    note_type_override: str | None,
    pillar_override: str | None,
) -> None:
    note_id = resolve_own_note_id(conn, record)
    captured_at = normalize_time(captured_override or first(record, "captured_at"), now_iso())
    raw_json = json.dumps(record, ensure_ascii=False, sort_keys=True)
    conn.execute(
        """INSERT INTO notes
        (note_id,url,title,body,author_id,author_name,published_at,source,is_own,note_type,pillar,objective,experiment,raw_json,updated_at)
        VALUES (?,?,?,?,?,?,?,?,1,?,?,?,?,?,?)
        ON CONFLICT(note_id) DO UPDATE SET
        url=COALESCE(excluded.url,notes.url), title=COALESCE(excluded.title,notes.title),
        body=COALESCE(excluded.body,notes.body), author_id=COALESCE(excluded.author_id,notes.author_id),
        author_name=COALESCE(excluded.author_name,notes.author_name),
        published_at=COALESCE(excluded.published_at,notes.published_at), is_own=1,
        note_type=COALESCE(excluded.note_type,notes.note_type), pillar=COALESCE(excluded.pillar,notes.pillar),
        objective=COALESCE(excluded.objective,notes.objective), experiment=COALESCE(excluded.experiment,notes.experiment),
        raw_json=excluded.raw_json, updated_at=excluded.updated_at""",
        (
            note_id,
            first(record, "url"),
            first(record, "title"),
            first(record, "body"),
            first(record, "author_id"),
            first(record, "author_name"),
            normalize_time(first(record, "published_at")),
            source,
            note_type_override or first(record, "note_type"),
            pillar_override or first(record, "pillar"),
            first(record, "objective"),
            first(record, "experiment"),
            raw_json,
            now_iso(),
        ),
    )
    metrics = tuple(parse_count(first(record, field)) for field in (
        "likes", "saves", "comments", "shares", "impressions", "views",
        "profile_visits", "followers_gained", "avg_duration",
    ))
    if any(value is not None for value in metrics):
        conn.execute(
            """INSERT INTO metric_snapshots
            (note_id,captured_at,source,likes,saves,comments,shares,impressions,views,profile_visits,followers_gained,avg_duration,raw_json)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(note_id,captured_at,source) DO UPDATE SET
            likes=excluded.likes,saves=excluded.saves,comments=excluded.comments,shares=excluded.shares,
            impressions=excluded.impressions,views=excluded.views,profile_visits=excluded.profile_visits,
            followers_gained=excluded.followers_gained,avg_duration=excluded.avg_duration,raw_json=excluded.raw_json""",
            (note_id, captured_at, source, *metrics, raw_json),
        )


def run_import(args: argparse.Namespace) -> dict[str, Any]:
    conn = connect(args.db)
    files = list(iter_files(args.paths))
    records = 0
    errors: list[str] = []
    for path in files:
        try:
            for record in read_records(path):
                if args.kind == "research":
                    import_research(conn, record, args.source, args.query, args.captured_at)
                else:
                    import_own(conn, record, args.source, args.captured_at, args.note_type, args.pillar)
                records += 1
        except (OSError, ValueError, json.JSONDecodeError, csv.Error) as exc:
            errors.append(f"{path}: {exc}")
    conn.commit()
    conn.close()
    return {"files": len(files), "records": records, "errors": errors, "database": str(args.db)}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("init", help="create the SQLite schema")
    importer = subparsers.add_parser("import", help="import CSV, JSON, or JSONL records")
    importer.add_argument("paths", nargs="+", type=Path)
    importer.add_argument("--kind", choices=("research", "own"), required=True)
    importer.add_argument("--source", default="manual-import")
    importer.add_argument("--query")
    importer.add_argument("--captured-at")
    importer.add_argument("--note-type")
    importer.add_argument("--pillar")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    if args.command == "init":
        conn = connect(args.db)
        conn.close()
        result = {"database": str(args.db), "initialized": True}
    else:
        result = run_import(args)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 1 if result.get("errors") else 0


if __name__ == "__main__":
    sys.exit(main())
