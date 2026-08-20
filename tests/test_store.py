from __future__ import annotations

import sqlite3
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
STORE = ROOT / "scripts" / "store.py"
TREND = ROOT / "scripts" / "trend_report.py"


def run(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run([sys.executable, *args], check=True, capture_output=True, text=True)


def test_end_to_end(tmp_path: Path) -> None:
    db = tmp_path / "test.sqlite3"
    research = tmp_path / "research.jsonl"
    research.write_text(
        '{"note_id":"r1","title":"一周准备清单","body":"带狗回国的检疫材料和航空流程","url":"https://www.xiaohongshu.com/explore/r1","keyword":"带狗回国","author_name":"作者A","author_url":"https://www.xiaohongshu.com/user/profile/a","liked_count":"1.2万","collected_count":3000,"comment_count":120,"time":"2026-08-03"}\n'
        '{"note_id":"r2","title":"材料踩坑","body":"带狗回国材料避坑","url":"https://www.xiaohongshu.com/explore/r2","keyword":"带狗回国","liked_count":800,"collected_count":500,"comment_count":50,"time":"2026-08-02"}\n',
        encoding="utf-8",
    )
    run(str(STORE), "--db", str(db), "init")
    run(str(STORE), "--db", str(db), "import", str(research), "--kind", "research", "--source", "test")
    trend = run(str(TREND), "--db", str(db), "--days", "30").stdout
    assert "带狗回国" in trend
    assert "[一周准备清单](https://www.xiaohongshu.com/explore/r1)" in trend
    assert "作者账户：[作者A](https://www.xiaohongshu.com/user/profile/a)" in trend
    assert "抓取结果：2 条" in trend
    assert "赞 12000.0｜藏 3000.0｜评 120.0｜转 unknown" in trend
    assert "你可以继续让我做什么" in trend
    with sqlite3.connect(db) as conn:
        assert conn.execute("SELECT COUNT(*) FROM research_hits").fetchone()[0] == 2
