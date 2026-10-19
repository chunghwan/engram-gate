"""Regression tests for the MCP server (mcp_server.py).

Not part of SPEC v1.0 conformance (the frozen SPEC does not cover the MCP
transport); these pin review fixes P1-2 (ledger on the MCP path) and
P1-3 (malformed input must never kill the stdio server).

Runnable with pytest or with plain unittest:
    python3 -m pytest tests/conformance -q
    python3 -m unittest discover -s tests/conformance -v
"""
import contextlib
import io
import json
import os
import sys
import tempfile
import time
import unittest

sys.path.insert(
    0,
    os.path.join(os.path.dirname(__file__), "..", "..", "src"),
)

from engram_gate import mcp_server  # noqa: E402
from engram_gate.ledger import read_ledger  # noqa: E402

ENTRIES = [
    {
        "id": "e1",
        "title": "Database migration plan",
        "body": "Plan for the database migration window.",
        "summary": "",
        "topics": ["database", "migration"],
        "ts": "2026-10-10T09:00:00+00:00",
    },
    {
        "id": "e2",
        "title": "Cache notes",
        "body": "Cache invalidation and TTL discussion.",
        "summary": "",
        "topics": ["cache"],
        "ts": "2026-10-10T10:00:00+00:00",
    },
]


def write_corpus(directory, entries=ENTRIES):
    path = os.path.join(directory, "corpus.jsonl")
    with open(path, "w", encoding="utf-8") as f:
        for e in entries:
            f.write(json.dumps(e) + "\n")
    return path


def base_args(store, ledger, **extra):
    args = {
        "keywords": "database",
        "store": store,
        "agent": "mcp-tester",
        "ledger": ledger,
    }
    args.update(extra)
    return args


class TestMcpLedger(unittest.TestCase):
    """P1-2: gate_query must append to the ledger like the CLI does."""

    def test_gate_query_appends_ledger(self):
        with tempfile.TemporaryDirectory() as d:
            store = write_corpus(d)
            ledger = os.path.join(d, "ledger.jsonl")
            result = mcp_server.gate_query(base_args(store, ledger))
            self.assertEqual(result["exit_code"], 0)
            rows = read_ledger(ledger)
            self.assertEqual(len(rows), 1)
            row = rows[0]
            self.assertEqual(row["agent"], "mcp-tester")
            self.assertEqual(row["exit_code"], 0)
            self.assertEqual(row["hit_count"], len(result["hits"]))
            self.assertRegex(row["query_id"], r"^\d{8}T\d{6}Z-mcp-tester-\d{4}$")

    def test_no_ledger_opt_out(self):
        with tempfile.TemporaryDirectory() as d:
            store = write_corpus(d)
            ledger = os.path.join(d, "ledger.jsonl")
            result = mcp_server.gate_query(base_args(store, ledger, no_ledger=True))
            self.assertEqual(result["exit_code"], 0)
            self.assertFalse(os.path.exists(ledger))

    def test_null_keywords_is_exit_2_not_string_none(self):
        """keywords: null must not be coerced to the literal string "None"."""
        with tempfile.TemporaryDirectory() as d:
            store = write_corpus(d)
            ledger = os.path.join(d, "ledger.jsonl")
            result = mcp_server.gate_query(base_args(store, ledger, keywords=None))
            self.assertEqual(result["exit_code"], 2)
            self.assertEqual(result["error"], "empty keywords")
            self.assertFalse(os.path.exists(ledger))

    def test_ledger_records_original_keywords_text(self):
        """SPEC §7: ledger `keywords` is the original query text, not the
        normalized (lowercased) form used for scoring."""
        with tempfile.TemporaryDirectory() as d:
            store = write_corpus(d)
            ledger = os.path.join(d, "ledger.jsonl")
            result = mcp_server.gate_query(
                base_args(store, ledger, keywords="  Database MIGRATION ")
            )
            self.assertEqual(result["exit_code"], 0)
            rows = read_ledger(ledger)
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["keywords"], "Database MIGRATION")

    def test_ledger_write_failure_is_exit_2_not_crash(self):
        with tempfile.TemporaryDirectory() as d:
            store = write_corpus(d)
            # a directory is not a writable ledger file
            result = mcp_server.gate_query(base_args(store, d))
            self.assertEqual(result["exit_code"], 2)
            self.assertIn("ledger write failure", result["error"])

    def test_tool_schema_exposes_ledger(self):
        props = mcp_server.TOOL["inputSchema"]["properties"]
        self.assertIn("ledger", props)
        self.assertIn("no_ledger", props)


class TestMcpRobustness(unittest.TestCase):
    """P1-3: malformed input must produce errors, never kill the server."""

    def test_non_dict_request_is_invalid_request(self):
        for bad in ('"hi"', "[1, 2]", "42", "null"):
            request = json.loads(bad)
            resp = mcp_server.handle(request)
            self.assertIsNotNone(resp)
            self.assertEqual(resp["error"]["code"], -32600, msg=f"input {bad}")

    def test_null_limit_does_not_raise(self):
        with tempfile.TemporaryDirectory() as d:
            store = write_corpus(d)
            result = mcp_server.gate_query(
                base_args(store, os.path.join(d, "l.jsonl"), limit=None, no_ledger=True)
            )
            self.assertIn("exit_code", result)

    def test_garbage_limit_is_exit_2(self):
        with tempfile.TemporaryDirectory() as d:
            store = write_corpus(d)
            result = mcp_server.gate_query(
                base_args(store, os.path.join(d, "l.jsonl"), limit="abc", no_ledger=True)
            )
            self.assertEqual(result["exit_code"], 2)
            self.assertIn("invalid limit", result["error"])

    def test_garbage_days_is_exit_2(self):
        with tempfile.TemporaryDirectory() as d:
            store = write_corpus(d)
            result = mcp_server.gate_query(
                base_args(store, os.path.join(d, "l.jsonl"), days="yesterday", no_ledger=True)
            )
            self.assertEqual(result["exit_code"], 2)
            self.assertIn("invalid days", result["error"])

    def test_non_dict_arguments_is_exit_2(self):
        resp = mcp_server.handle(
            {
                "jsonrpc": "2.0",
                "id": 7,
                "method": "tools/call",
                "params": {"name": "gate_query", "arguments": "nope"},
            }
        )
        payload = json.loads(resp["result"]["content"][0]["text"])
        self.assertEqual(payload["exit_code"], 2)

    def test_main_loop_survives_garbage_lines(self):
        with tempfile.TemporaryDirectory() as d:
            store = write_corpus(d)
            lines = [
                '"hi"',
                "[1, 2]",
                '{"jsonrpc": "2.0", "id": 1, "method": "tools/call", '
                '"params": {"name": "gate_query", "arguments": '
                '{"keywords": "database", "store": %s, "no_ledger": true}}}' % json.dumps(store),
                '{"jsonrpc": "2.0", "id": 2, "method": "tools/call", '
                '"params": {"name": "gate_query", "arguments": '
                '{"keywords": "database", "store": %s, "limit": null, "no_ledger": true}}}' % json.dumps(store),
                "not json at all {{{",
            ]
            fake_in = io.StringIO("\n".join(lines) + "\n")
            fake_out = io.StringIO()
            old_in, old_out = sys.stdin, sys.stdout
            try:
                sys.stdin, sys.stdout = fake_in, fake_out
                mcp_server.main()  # must return, not raise
            finally:
                sys.stdin, sys.stdout = old_in, old_out
            responses = [json.loads(line) for line in fake_out.getvalue().splitlines()]
            codes = [r["error"]["code"] for r in responses[:2]]
            self.assertEqual(codes, [-32600, -32600])
            # the two well-formed calls both answered with a result
            self.assertIn("result", responses[2])
            self.assertIn("result", responses[3])
            payload = json.loads(responses[3]["result"]["content"][0]["text"])
            self.assertEqual(payload["exit_code"], 0)  # limit:null -> default 8
            self.assertTrue(payload["hits"])


class TestMcpTimeout(unittest.TestCase):
    """SPEC §8 escalation on the MCP surface: timeout -> exit-2 payload."""

    def test_timeout_argument_is_exit_2(self):
        class _Slow:
            def list_visible(self, since=None):
                time.sleep(30)

        real = mcp_server._make_adapter
        mcp_server._make_adapter = lambda store: _Slow()
        try:
            started = time.monotonic()
            result = mcp_server.gate_query(
                base_args("ignored.jsonl", "ignored.jsonl", timeout=0.2, no_ledger=True)
            )
            elapsed = time.monotonic() - started
        finally:
            mcp_server._make_adapter = real
        self.assertEqual(result["exit_code"], 2)
        self.assertIn("timeout", result["error"])
        self.assertLess(elapsed, 10)

    def test_garbage_timeout_is_exit_2(self):
        with tempfile.TemporaryDirectory() as d:
            store = write_corpus(d)
            result = mcp_server.gate_query(
                base_args(store, os.path.join(d, "l.jsonl"), timeout="soon", no_ledger=True)
            )
        self.assertEqual(result["exit_code"], 2)
        self.assertIn("invalid timeout", result["error"])

    def test_nonpositive_timeout_is_exit_2(self):
        with tempfile.TemporaryDirectory() as d:
            store = write_corpus(d)
            result = mcp_server.gate_query(
                base_args(store, os.path.join(d, "l.jsonl"), timeout=0, no_ledger=True)
            )
        self.assertEqual(result["exit_code"], 2)
        self.assertIn("invalid timeout", result["error"])

    def test_tool_schema_exposes_timeout(self):
        props = mcp_server.TOOL["inputSchema"]["properties"]
        self.assertIn("timeout", props)
        self.assertEqual(props["timeout"]["default"], 5.0)


if __name__ == "__main__":
    unittest.main()
