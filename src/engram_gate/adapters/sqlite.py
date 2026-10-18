"""SQLite store adapter. Implements list_visible(since) per SPEC.md Section 6.

Expected schema:
    entries(id TEXT, title TEXT, body TEXT, summary TEXT, topics TEXT, ts TEXT)
`topics` is a JSON array string (or comma-separated fallback).
"""
from __future__ import annotations

import datetime
import json
import sqlite3

from .jsonl import _parse_ts

SCHEMA = """
CREATE TABLE IF NOT EXISTS entries (
    id TEXT,
    title TEXT,
    body TEXT,
    summary TEXT,
    topics TEXT,
    ts TEXT
)
"""


def init_db(path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(path)
    conn.execute(SCHEMA)
    conn.commit()
    return conn


class SqliteAdapter:
    def __init__(self, path: str):
        self.path = path

    def list_visible(self, since: datetime.datetime | None = None) -> list[dict]:
        conn = sqlite3.connect(f"file:{self.path}?mode=ro", uri=True)
        try:
            cur = conn.execute("SELECT id, title, body, summary, topics, ts FROM entries")
            rows = cur.fetchall()
        finally:
            conn.close()
        entries = []
        for rid, title, body, summary, topics_raw, ts in rows:
            topics = []
            if topics_raw:
                try:
                    parsed = json.loads(topics_raw)
                    topics = parsed if isinstance(parsed, list) else [str(parsed)]
                except (ValueError, TypeError):
                    topics = [t.strip() for t in str(topics_raw).split(",") if t.strip()]
            entry = {
                "id": rid,
                "title": title or "",
                "body": body or "",
                "summary": summary or "",
                "topics": topics,
                "ts": ts,
            }
            if since is not None:
                parsed_ts = _parse_ts(ts)
                if parsed_ts is not None and parsed_ts < since:
                    continue
            entries.append(entry)
        return entries
