#!/usr/bin/env python3
"""Create an evidence summary from normalized Xiaohongshu research hits."""

from __future__ import annotations

import argparse
import math
import sqlite3
import statistics
import json
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from store import DEFAULT_DB
from research_filters import classify_record


def parse_time(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.astimezone()
        return parsed
    except ValueError:
        return None


def median(values: list[float]) -> float:
    return float(statistics.median(values)) if values else 0.0


def minmax(value: float, values: list[float]) -> float:
    if not values or max(values) == min(values):
        return 0.5 if values else 0.0
    return (value - min(values)) / (max(values) - min(values))


def row_record(row: sqlite3.Row) -> dict[str, Any]:
    try:
        value = json.loads(row["raw_json"])
        if isinstance(value, dict):
            result = dict(value)
            if not result.get("url") and result.get("note_url"):
                result["url"] = result["note_url"]
            if not result.get("body") and result.get("summary"):
                result["body"] = result["summary"]
            if not result.get("author_name") and result.get("author"):
                result["author_name"] = result["author"]
            return result
    except (TypeError, json.JSONDecodeError):
        pass
    return {"note_id": row["note_id"], "title": row["title"] or "", "query": row["query"]}


def row_url(row: sqlite3.Row) -> str | None:
    record = row_record(row)
    url = record.get("url")
    return str(url) if url else None


def raw_value(row: sqlite3.Row, *names: str) -> Any:
    record = row_record(row)
    for name in names:
        if record.get(name) not in (None, ""):
            return record[name]
    raw = record.get("raw")
    if isinstance(raw, dict):
        for name in names:
            if raw.get(name) not in (None, ""):
                return raw[name]
    return None


def display_value(value: Any, mapping: dict[str, str], fallback: str = "未知") -> str:
    return mapping.get(str(value), str(value)) if value not in (None, "") else fallback


def source_label(row: sqlite3.Row) -> str:
    operation = raw_value(row, "operation")
    if row["source"] == "apify" and operation == "search_notes":
        return "Apify → SocialDataX"
    return str(row["source"] or "未知")


def collect(db: Path, days: int) -> list[dict[str, Any]]:
    conn = sqlite3.connect(db)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "SELECT * FROM research_hits ORDER BY captured_at DESC"
    ).fetchall()
    conn.close()
    cutoff = datetime.now(timezone.utc).astimezone() - timedelta(days=days)
    groups: dict[str, list[sqlite3.Row]] = defaultdict(list)
    for row in rows:
        captured = parse_time(row["captured_at"])
        if captured and captured >= cutoff:
            groups[row["query"]].append(row)

    summaries: list[dict[str, Any]] = []
    for query, hits in groups.items():
        unique = {row["note_id"]: row for row in hits}
        records = list(unique.values())
        labels = {row["note_id"]: classify_record(row_record(row), query) for row in records}
        relevant = [row for row in records if labels[row["note_id"]]["status"] == "relevant"]
        adjacent = [row for row in records if labels[row["note_id"]]["status"] == "adjacent"]
        # Keep every sampled record in the output. Relevance is a warning only.
        display_records = records
        fresh = 0
        weighted: list[float] = []
        comment_intent: list[float] = []
        for row in relevant:
            published = parse_time(row["published_at"])
            if published and published >= cutoff:
                fresh += 1
            likes = row["likes"] or 0
            saves = row["saves"] or 0
            comments = row["comments"] or 0
            shares = row["shares"] or 0
            weighted.append(likes + 2 * saves + 3 * comments + shares)
            comment_intent.append(comments / (likes + saves + comments + 1))
        summaries.append({
            "query": query,
            "sampled_count": len(records),
            "count": len(relevant),
            "adjacent_count": len(adjacent),
            "excluded_count": len(records) - len(relevant) - len(adjacent),
            "freshness": fresh / len(relevant) if relevant else 0,
            "median_engagement": median(weighted),
            "comment_intent": median(comment_intent),
            "examples": sorted(display_records, key=lambda row: (row["likes"] or 0) + 2 * (row["saves"] or 0) + 3 * (row["comments"] or 0), reverse=True)[:3],
            "labels": labels,
            "all_records": records,
            "source_label": source_label(records[0]) if records else "未知",
            "sort_type": raw_value(records[0], "query_sort_type") if records else None,
            "note_type": raw_value(records[0], "query_note_type") if records else None,
            "publish_time_range": raw_value(records[0], "query_publish_time_range") if records else None,
        })

    engagements = [math.log1p(item["median_engagement"]) for item in summaries]
    intents = [item["comment_intent"] for item in summaries]
    for item in summaries:
        density = min(item["count"] / 20, 1)
        engagement = minmax(math.log1p(item["median_engagement"]), engagements)
        intent = minmax(item["comment_intent"], intents)
        item["score"] = 100 * (0.35 * item["freshness"] + 0.25 * density + 0.25 * engagement + 0.15 * intent)
    return sorted(summaries, key=lambda item: item["score"], reverse=True)


def format_report(summaries: list[dict[str, Any]], days: int) -> str:
    lines = [
        "# 小红书前期调研结果",
        "",
    ]
    for item in summaries:
        lines.extend([
            "## 调研方向",
            "",
            f"数据源：{item['source_label']}",
            f"关键词：{item['query']}",
            f"排序：{display_value(item['sort_type'], {'general': '综合', 'time_descending': '最新', 'like_count_descending': '点赞最多', 'comment_count_descending': '评论最多', 'collect_count_descending': '收藏最多'})}",
            f"笔记类型：{display_value(item['note_type'], {'all': '全部', 'image': '图文', 'video': '视频'})}",
            f"发布时间：{display_value(item['publish_time_range'], {'all': '不限', 'day': '一天内', 'week': '一周内', 'half_year': '半年内'})}",
            f"抓取结果：{item['sampled_count']} 条",
            "",
            "## 样本列表",
            "",
        ])
        for row in item["all_records"]:
            label = item["labels"][row["note_id"]]
            warning = "" if label["status"] == "relevant" else "⚠️ "
            title = row["title"] or "无标题"
            url = row_url(row)
            linked_title = f"[{title}]({url})" if url else title
            author = row["author_name"] or raw_value(row, "author_name", "author") or "unknown"
            author_url = raw_value(row, "author_url", "authorProfileUrl", "profile_url", "profileUrl", "user_url", "userUrl")
            author_account = f"[{author}]({author_url})" if author_url else str(author)
            metrics = f"赞 {row['likes'] if row['likes'] is not None else 'unknown'}｜藏 {row['saves'] if row['saves'] is not None else 'unknown'}｜评 {row['comments'] if row['comments'] is not None else 'unknown'}｜转 {row['shares'] if row['shares'] is not None else 'unknown'}"
            lines.append(f"{warning}{linked_title}")
            lines.append(f"作者账户：{author_account}")
            lines.append(metrics)
            lines.append("")
        lines.extend([
            f"> ⚠️ 相关性仅作提示：相关 {item['count']} 条，邻近 {item['adjacent_count']} 条，噪声/待确认 {item['excluded_count']} 条；本次完整保留全部 {item['sampled_count']} 条。",
            "",
        ])
    if not summaries:
        lines.extend(["没有找到时间窗内的研究记录。先用 `scripts/xhs_api.py` 导入外部 API 样本，或导入人工整理的公开数据。"])
        return "\n".join(lines) + "\n"
    lines.extend([
        "## 你可以继续让我做什么",
        "",
        "1. 提取高频商场、地点、规则和用户痛点。",
        "2. 对比正面体验、负面体验和争议点。",
        "3. 从完整样本中提炼 3–5 个选题方向。",
        "4. 指定一条笔记链接，我继续读取详情并做结构拆解。",
        "5. 提供一条具体笔记链接，我基于详情进行仿写；不会复制原文或冒充原作者经历。",
        "",
        "## 下一步",
        "",
        "以上样本全部保留。后续可再基于摘要、正文详情和账号定位提炼 3–5 个具体选题。",
    ])
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    parser.add_argument("--days", type=int, default=7)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if not args.db.exists():
        parser.error(f"database does not exist: {args.db}")
    report = format_report(collect(args.db, args.days), args.days)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(report, encoding="utf-8")
    else:
        print(report, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
