"""Append-only query ledger per SPEC.md Section 7.

query_id format (frozen): ts-agent-seq, e.g. 20261012T010203Z-agent1-0001
"""
from __future__ import annotations

import datetime
import json
import os


def _utcnow() -> datetime.datetime:
    return datetime.datetime.now(datetime.timezone.utc)


def next_seq(ledger_path: str) -> int:
    try:
        with open(ledger_path, encoding="utf-8") as f:
            return sum(1 for line in f if line.strip()) + 1
    except FileNotFoundError:
        return 1


def make_query_id(agent: str, seq: int, ts: datetime.datetime | None = None) -> str:
    ts = ts or _utcnow()
    return f"{ts.strftime('%Y%m%dT%H%M%SZ')}-{agent}-{seq:04d}"


def build_entry(
    agent: str,
    keywords: str,
    exit_code: int,
    hits: list[dict],
    seq: int,
    ts: datetime.datetime | None = None,
    total_hit_count: int | None = None,
) -> dict:
    ts = ts or _utcnow()
    entry = {
        "query_id": make_query_id(agent, seq, ts),
        "agent": agent,
        "keywords": keywords,
        "exit_code": exit_code,
        "hit_count": len(hits),
        "score_vector": [h["score"] for h in hits],
        "ts": ts.isoformat(),
    }
    if total_hit_count is not None and total_hit_count != len(hits):
        entry["total_hit_count"] = total_hit_count
    return entry


def append_ledger(
    ledger_path: str,
    agent: str,
    keywords: str,
    exit_code: int,
    hits: list[dict],
    total_hit_count: int | None = None,
) -> dict:
    """Append one entry to the ledger (append-only; never rewrites)."""
    seq = next_seq(ledger_path)
    entry = build_entry(agent, keywords, exit_code, hits, seq, total_hit_count=total_hit_count)
    parent = os.path.dirname(os.path.abspath(ledger_path))
    os.makedirs(parent, exist_ok=True)
    with open(ledger_path, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    return entry


def read_ledger(ledger_path: str) -> list[dict]:
    rows = []
    with open(ledger_path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows
