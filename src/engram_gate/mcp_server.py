"""Minimal stdlib MCP server over stdio JSON-RPC.

Exposes a single tool, `gate_query`, wrapping the same contract as the CLI.
Protocol: newline-delimited JSON-RPC 2.0 (initialize / tools/list / tools/call).

Like the CLI, every query is appended to an append-only JSONL ledger
(default ``ledger.jsonl`` in the working directory); pass an explicit
``ledger`` path or ``no_ledger: true`` to override. Malformed input can
never kill the server: it is answered with a JSON-RPC error instead.
"""
from __future__ import annotations

import datetime
import json
import sys

from . import ledger as ledger_mod
from .cli import _make_adapter
from .scoring import parse_keywords, rank_entries
from .watchdog import DEFAULT_TIMEOUT_SECONDS, QueryTimeout, query_watchdog

TOOL = {
    "name": "gate_query",
    "description": "Query the trace store; returns hits and an exit code (0=hits, 1=none, 2=error).",
    "inputSchema": {
        "type": "object",
        "properties": {
            "keywords": {"type": "string"},
            "store": {"type": "string", "default": "corpus.jsonl"},
            "agent": {"type": "string", "default": "unknown"},
            "days": {"type": "integer"},
            "limit": {"type": "integer", "default": 8},
            "timeout": {"type": "number", "default": 5.0},
            "ledger": {"type": "string", "default": "ledger.jsonl"},
            "no_ledger": {"type": "boolean", "default": False},
        },
        "required": ["keywords"],
    },
}


def _coerce_int(value, name: str, default):
    if value is None:
        return default
    try:
        return int(value)
    except (TypeError, ValueError):
        raise ValueError(f"invalid {name}: {value!r}")


def _coerce_float(value, name: str, default):
    if value is None:
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        raise ValueError(f"invalid {name}: {value!r}")


def gate_query(arguments: dict) -> dict:
    try:
        return _gate_query(arguments)
    except Exception as exc:  # never let one tool call kill the stdio server
        return {"exit_code": 2, "error": f"internal error: {exc}", "hits": []}


def _gate_query(arguments: dict) -> dict:
    if not isinstance(arguments, dict):
        return {"exit_code": 2, "error": "invalid arguments", "hits": []}
    keywords_text = str(arguments.get("keywords", "")).strip()
    keywords = parse_keywords(keywords_text)
    if not keywords:
        return {"exit_code": 2, "error": "empty keywords", "hits": []}
    store = str(arguments.get("store", "corpus.jsonl"))
    agent = str(arguments.get("agent", "unknown"))
    try:
        days = _coerce_int(arguments.get("days"), "days", None)
        limit = _coerce_int(arguments.get("limit", 8), "limit", 8)
        timeout = _coerce_float(arguments.get("timeout"), "timeout", DEFAULT_TIMEOUT_SECONDS)
    except ValueError as exc:
        return {"exit_code": 2, "error": str(exc), "hits": []}
    if timeout <= 0:
        return {"exit_code": 2, "error": f"invalid timeout: {timeout}", "hits": []}
    since = None
    if days is not None:
        since = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=days)
    try:
        # §8: the escalation to exit 2 on timeout is enforced, not declared.
        with query_watchdog(timeout):
            entries = _make_adapter(store).list_visible(since=since)
            all_hits = rank_entries(entries, keywords)
    except QueryTimeout as exc:
        return {"exit_code": 2, "error": str(exc), "hits": []}
    except Exception as exc:
        return {"exit_code": 2, "error": f"store read failure: {exc}", "hits": []}
    hits = all_hits[:limit] if limit and limit > 0 else all_hits
    exit_code = 0 if all_hits else 1
    if not arguments.get("no_ledger"):
        try:
            ledger_mod.append_ledger(
                str(arguments.get("ledger", "ledger.jsonl")),
                agent=agent,
                keywords=" ".join(keywords),
                exit_code=exit_code,
                hits=hits,
                total_hit_count=len(all_hits),
            )
        except Exception as exc:
            return {"exit_code": 2, "error": f"ledger write failure: {exc}", "hits": []}
    return {"exit_code": exit_code, "hits": hits}


def _safe_id(request):
    try:
        return request.get("id")
    except AttributeError:
        return None


def handle(request) -> dict | None:
    rid = _safe_id(request)
    if not isinstance(request, dict):
        return {"jsonrpc": "2.0", "id": rid, "error": {"code": -32600, "message": "invalid request"}}
    method = request.get("method", "")
    if method == "initialize":
        return {
            "jsonrpc": "2.0",
            "id": rid,
            "result": {
                "protocolVersion": "2024-11-05",
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "engram-gate", "version": "0.1.0"},
            },
        }
    if method == "notifications/initialized":
        return None
    if method == "tools/list":
        return {"jsonrpc": "2.0", "id": rid, "result": {"tools": [TOOL]}}
    if method == "tools/call":
        params = request.get("params", {})
        if not isinstance(params, dict):
            return {"jsonrpc": "2.0", "id": rid, "error": {"code": -32602, "message": "invalid params"}}
        if params.get("name") != "gate_query":
            return {"jsonrpc": "2.0", "id": rid, "error": {"code": -32602, "message": "unknown tool"}}
        try:
            result = gate_query(params.get("arguments", {}))
        except Exception as exc:  # defense in depth; gate_query already guards itself
            return {"jsonrpc": "2.0", "id": rid, "error": {"code": -32603, "message": f"internal error: {exc}"}}
        return {
            "jsonrpc": "2.0",
            "id": rid,
            "result": {"content": [{"type": "text", "text": json.dumps(result, ensure_ascii=False)}]},
        }
    if rid is not None:
        return {"jsonrpc": "2.0", "id": rid, "error": {"code": -32601, "message": "method not found"}}
    return None


def main() -> None:
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            request = json.loads(line)
        except ValueError:
            continue
        try:
            response = handle(request)
        except Exception as exc:  # last-resort guard: a request must never kill the server
            response = {
                "jsonrpc": "2.0",
                "id": _safe_id(request),
                "error": {"code": -32603, "message": f"internal error: {exc}"},
            }
        if response is not None:
            sys.stdout.write(json.dumps(response, ensure_ascii=False) + "\n")
            sys.stdout.flush()


if __name__ == "__main__":
    main()
