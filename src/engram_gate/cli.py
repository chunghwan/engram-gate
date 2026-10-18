"""CLI for engram-gate. Implements SPEC.md Sections 2, 3, 5, 7 and the
§8 timeout escalation (watchdog, see watchdog.py).

Usage:
    engram-gate query "<keywords>" [--days N] [--no-refresh] [--agent ID]
                      [--store PATH] [--ledger PATH] [--limit N]
                      [--timeout SECONDS]
Exit codes: 0 = hits, 1 = no hits, 2 = error.
"""
from __future__ import annotations

import argparse
import datetime
import json
import sys

from . import ledger as ledger_mod
from .scoring import parse_keywords, rank_entries
from .watchdog import DEFAULT_TIMEOUT_SECONDS, QueryTimeout, query_watchdog


def _make_adapter(store: str):
    lower = store.lower()
    if lower.endswith((".db", ".sqlite", ".sqlite3")):
        from .adapters.sqlite import SqliteAdapter

        return SqliteAdapter(store)
    from .adapters.jsonl import JsonlAdapter

    return JsonlAdapter(store)


def run_query(args) -> int:
    keywords_text = " ".join(args.keywords or []).strip()
    keywords = parse_keywords(keywords_text)
    if not keywords:
        print(json.dumps({"error": "empty keywords"}), file=sys.stderr)
        return 2
    if args.timeout <= 0:
        print(json.dumps({"error": f"invalid timeout: {args.timeout}"}), file=sys.stderr)
        return 2

    since = None
    if args.days is not None:
        since = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=args.days)

    # --no-refresh: with file/SQLite adapters there is no delta ingestion to
    # skip, so the flag is accepted and is a no-op (frozen-corpus mode).
    _ = args.no_refresh

    try:
        # §8: the escalation to exit 2 on timeout is enforced, not declared.
        with query_watchdog(args.timeout):
            adapter = _make_adapter(args.store)
            entries = adapter.list_visible(since=since)
            all_hits = rank_entries(entries, keywords)
    except QueryTimeout as exc:
        print(json.dumps({"error": str(exc)}), file=sys.stderr)
        return 2
    except Exception as exc:  # backend failure / unreadable store -> exit 2
        print(json.dumps({"error": f"store read failure: {exc}"}), file=sys.stderr)
        return 2
    limit = args.limit if args.limit is not None else 8
    hits = all_hits[:limit] if limit and limit > 0 else all_hits
    exit_code = 0 if all_hits else 1

    print(json.dumps({"exit_code": exit_code, "hits": hits}, ensure_ascii=False))

    if not args.no_ledger:
        try:
            ledger_mod.append_ledger(
                args.ledger,
                agent=args.agent,
                keywords=" ".join(keywords),
                exit_code=exit_code,
                hits=hits,
                total_hit_count=len(all_hits),
            )
        except Exception as exc:
            print(json.dumps({"error": f"ledger write failure: {exc}"}), file=sys.stderr)
            return 2
    return exit_code


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="engram-gate", description="Deterministic coordination gate")
    sub = parser.add_subparsers(dest="command")
    q = sub.add_parser("query", help="Query the trace store")
    q.add_argument("keywords", nargs="*", help="Space-separated keywords")
    q.add_argument("--days", type=int, default=None)
    q.add_argument("--no-refresh", action="store_true")
    q.add_argument("--agent", default="unknown")
    q.add_argument("--store", default="corpus.jsonl")
    q.add_argument("--ledger", default="ledger.jsonl")
    q.add_argument("--limit", type=int, default=8)
    q.add_argument(
        "--timeout",
        type=float,
        default=DEFAULT_TIMEOUT_SECONDS,
        help="Per-query wall-clock ceiling in seconds (SPEC §8; default 5)",
    )
    q.add_argument("--no-ledger", action="store_true", help="Do not append to the ledger (testing)")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command != "query":
        print(json.dumps({"error": 'usage: engram-gate query "<keywords>" [--agent <id>]'}), file=sys.stderr)
        return 2
    return run_query(args)


def entry() -> None:
    sys.exit(main())


if __name__ == "__main__":
    entry()
