"""Deterministic scoring per SPEC.md Section 4.

score(s) = sum_k (2*titleHit(s,k) + 2*bodyHit(s,k) + 1*topicHit(s,k))

Per-keyword sum, NO cap. Pure function: no wall-clock, randomness, or I/O.
"""
from __future__ import annotations


def parse_keywords(text: str) -> list[str]:
    """Split a keyword string into lowercased keywords."""
    if not text:
        return []
    return text.lower().split()


def score_entry(entry: dict, keywords: list[str]) -> int:
    title = str(entry.get("title", "")).lower()
    body = (
        str(entry.get("body", "")).lower()
        + " "
        + str(entry.get("summary", "")).lower()
    )
    topics_raw = entry.get("topics", []) or []
    if isinstance(topics_raw, str):
        topics = topics_raw.lower()
    else:
        topics = " ".join(str(t) for t in topics_raw).lower()
    total = 0
    for kw in keywords:
        if not kw:
            continue
        title_hit = 1 if kw in title else 0
        body_hit = 1 if kw in body else 0
        topic_hit = 1 if kw in topics else 0
        total += 2 * title_hit + 2 * body_hit + 1 * topic_hit
    return total


def rank_entries(entries: list[dict], keywords: list[str]) -> list[dict]:
    """Return hits (score > 0) sorted by descending score.

    Stable sort preserves input order for ties, matching the reference
    pilot and keeping output deterministic for identical input.
    """
    hits = []
    for e in entries:
        s = score_entry(e, keywords)
        if s > 0:
            hits.append(
                {"id": e.get("id"), "score": s, "title": str(e.get("title", ""))[:120]}
            )
    hits.sort(key=lambda h: -h["score"])
    return hits
