"""Conformance tests for engram-gate (SPEC.md Sections 2-8).

Runnable with pytest or with plain unittest:
    python3 -m pytest tests/conformance -q
    python3 -m unittest discover -s tests/conformance -v
"""
import contextlib
import io
import json
import os
import re
import sys
import tempfile
import time
import unittest

sys.path.insert(
    0,
    os.path.join(os.path.dirname(__file__), "..", "..", "src"),
)

from engram_gate import cli  # noqa: E402
from engram_gate.ledger import append_ledger, read_ledger  # noqa: E402
from engram_gate.scoring import parse_keywords, rank_entries, score_entry  # noqa: E402

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
    {
        "id": "e3",
        "title": "Unrelated gardening",
        "body": "Watering plants on a schedule.",
        "summary": "",
        "topics": ["plants"],
        "ts": "2026-10-10T11:00:00+00:00",
    },
]


def write_corpus(directory, entries=ENTRIES):
    path = os.path.join(directory, "corpus.jsonl")
    with open(path, "w", encoding="utf-8") as f:
        for e in entries:
            f.write(json.dumps(e) + "\n")
    return path


def run_cli(argv):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = cli.main(argv)
    return code, out.getvalue(), err.getvalue()


class TestScoring(unittest.TestCase):
    def test_exact_sigma_k_score(self):
        # database: title 2 + body 2 + topic 1 = 5
        # migration: title 2 + body 2 + topic 1 = 5  -> total 10
        self.assertEqual(score_entry(ENTRIES[0], ["database", "migration"]), 10)

    def test_case_insensitive(self):
        self.assertEqual(score_entry(ENTRIES[0], parse_keywords("DATABASE Migration")), 10)

    def test_no_cap(self):
        entry = {
            "id": "x",
            "title": "alpha beta gamma delta epsilon zeta eta theta iota kappa",
            "body": "alpha beta gamma delta epsilon zeta eta theta iota kappa",
            "topics": ["alpha", "beta", "gamma", "delta", "epsilon",
                        "zeta", "eta", "theta", "iota", "kappa"],
        }
        kws = parse_keywords("alpha beta gamma delta epsilon zeta eta theta iota kappa")
        # 10 keywords x (2 title + 2 body + 1 topic) = 50, far above any per-entry cap
        self.assertEqual(score_entry(entry, kws), 50)

    def test_zero_for_unrelated(self):
        self.assertEqual(score_entry(ENTRIES[2], ["database"]), 0)

    def test_rank_descending_and_positive_only(self):
        hits = rank_entries(ENTRIES, ["database", "migration"])
        self.assertEqual([h["id"] for h in hits], ["e1"])
        hits = rank_entries(ENTRIES, ["cache", "database"])
        scores = [h["score"] for h in hits]
        self.assertEqual(scores, sorted(scores, reverse=True))
        self.assertTrue(all(s > 0 for s in scores))


class TestExitCodes(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = write_corpus(self.tmp.name)
        self.ledger = os.path.join(self.tmp.name, "ledger.jsonl")

    def tearDown(self):
        self.tmp.cleanup()

    def base(self, *extra):
        return ["query", *extra, "--store", self.store, "--ledger", self.ledger]

    def test_exit_0_on_hits(self):
        code, out, _ = run_cli(self.base("database migration", "--agent", "tester"))
        self.assertEqual(code, 0)
        payload = json.loads(out)
        self.assertEqual(payload["exit_code"], 0)
        self.assertTrue(payload["hits"])
        self.assertTrue(all(set(h) >= {"id", "score", "title"} for h in payload["hits"]))

    def test_exit_1_on_no_hits(self):
        code, out, _ = run_cli(self.base("quantum teleportation"))
        self.assertEqual(code, 1)
        self.assertEqual(json.loads(out)["hits"], [])

    def test_exit_2_on_empty_keywords(self):
        code, _, err = run_cli(self.base(""))
        self.assertEqual(code, 2)
        self.assertIn("error", json.loads(err))

    def test_exit_2_on_missing_keywords_arg(self):
        code, _, err = run_cli(["query", "--store", self.store, "--ledger", self.ledger])
        self.assertEqual(code, 2)
        self.assertIn("error", json.loads(err))

    def test_exit_2_on_unreadable_store(self):
        missing = os.path.join(self.tmp.name, "does-not-exist.jsonl")
        code, _, err = run_cli(
            ["query", "database", "--store", missing, "--ledger", self.ledger]
        )
        self.assertEqual(code, 2)
        self.assertIn("error", json.loads(err))

    def test_agent_does_not_affect_scoring(self):
        _, out_a, _ = run_cli(self.base("database", "--agent", "alice", "--no-ledger"))
        _, out_b, _ = run_cli(self.base("database", "--agent", "bob", "--no-ledger"))
        self.assertEqual(json.loads(out_a), json.loads(out_b))


class TestDeterminism(unittest.TestCase):
    def test_same_query_twice_identical(self):
        with tempfile.TemporaryDirectory() as d:
            store = write_corpus(d)
            ledger = os.path.join(d, "ledger.jsonl")
            argv = ["query", "database migration", "--store", store,
                    "--ledger", ledger, "--agent", "det"]
            code1, out1, _ = run_cli(argv)
            code2, out2, _ = run_cli(argv)
            self.assertEqual(code1, code2)
            self.assertEqual(out1, out2)

    def test_rank_is_deterministic(self):
        kws = parse_keywords("database cache")
        self.assertEqual(rank_entries(ENTRIES, kws), rank_entries(ENTRIES, list(kws)))


class _SlowAdapter:
    """Adapter whose list_visible hangs past any sane latency ceiling."""

    def __init__(self, seconds=30):
        self.seconds = seconds

    def list_visible(self, since=None):
        time.sleep(self.seconds)
        return []


class TestTimeout(unittest.TestCase):
    """SPEC §8: past the latency ceiling the query MUST escalate to exit 2."""

    def test_exit_2_on_timeout(self):
        real = cli._make_adapter
        cli._make_adapter = lambda store: _SlowAdapter(30)
        try:
            started = time.monotonic()
            code, _, err = run_cli(
                ["query", "database", "--store", "ignored.jsonl", "--no-ledger",
                 "--timeout", "0.2"]
            )
            elapsed = time.monotonic() - started
        finally:
            cli._make_adapter = real
        self.assertEqual(code, 2)
        self.assertIn("timeout", json.loads(err)["error"])
        # interrupted by the watchdog, not waited out
        self.assertLess(elapsed, 10)

    def test_timeout_leaves_no_stale_alarm(self):
        real = cli._make_adapter
        cli._make_adapter = lambda store: _SlowAdapter(30)
        try:
            code, _, _ = run_cli(
                ["query", "database", "--store", "ignored.jsonl", "--no-ledger",
                 "--timeout", "0.2"]
            )
            self.assertEqual(code, 2)
        finally:
            cli._make_adapter = real
        # the next query must succeed: handler and timer were restored
        with tempfile.TemporaryDirectory() as d:
            store = write_corpus(d)
            code, out, _ = run_cli(
                ["query", "database", "--store", store, "--no-ledger"]
            )
        self.assertEqual(code, 0)
        self.assertTrue(json.loads(out)["hits"])

    def test_default_timeout_is_budget_ceiling(self):
        # §8 default budget: p95 <= 5s
        args = cli.build_parser().parse_args(["query", "database"])
        self.assertEqual(args.timeout, 5.0)

    def test_nonpositive_timeout_is_exit_2(self):
        with tempfile.TemporaryDirectory() as d:
            store = write_corpus(d)
            code, _, err = run_cli(
                ["query", "database", "--store", store, "--no-ledger", "--timeout", "0"]
            )
        self.assertEqual(code, 2)
        self.assertIn("error", json.loads(err))


class TestLedger(unittest.TestCase):
    def test_schema_and_query_id_format(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "ledger.jsonl")
            hits = [{"id": "e1", "score": 10, "title": "t"}]
            entry = append_ledger(path, "agent1", "database migration", 0, hits)
            for key in ("query_id", "agent", "keywords", "exit_code",
                        "hit_count", "score_vector", "ts"):
                self.assertIn(key, entry)
            self.assertRegex(entry["query_id"], r"^\d{8}T\d{6}Z-agent1-\d{4}$")
            self.assertEqual(entry["score_vector"], [10])
            self.assertEqual(entry["hit_count"], 1)

    def test_append_only(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "ledger.jsonl")
            append_ledger(path, "a", "one", 1, [])
            with open(path, encoding="utf-8") as f:
                first_line = f.readline()
            append_ledger(path, "a", "two", 1, [])
            rows = read_ledger(path)
            self.assertEqual(len(rows), 2)
            with open(path, encoding="utf-8") as f:
                self.assertEqual(f.readline(), first_line)
            seqs = [r["query_id"].rsplit("-", 1)[1] for r in rows]
            self.assertEqual(seqs, ["0001", "0002"])

    def test_cli_writes_ledger(self):
        with tempfile.TemporaryDirectory() as d:
            store = write_corpus(d)
            ledger = os.path.join(d, "ledger.jsonl")
            code, _, _ = run_cli(["query", "database", "--store", store,
                                  "--ledger", ledger, "--agent", "cli-test"])
            self.assertEqual(code, 0)
            rows = read_ledger(ledger)
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["agent"], "cli-test")
            self.assertEqual(rows[0]["exit_code"], 0)


class TestAdapters(unittest.TestCase):
    def test_jsonl_adapter_list_visible(self):
        from engram_gate.adapters.jsonl import JsonlAdapter

        with tempfile.TemporaryDirectory() as d:
            store = write_corpus(d)
            entries = JsonlAdapter(store).list_visible()
            self.assertEqual(len(entries), len(ENTRIES))

    def test_sqlite_adapter_roundtrip(self):
        from engram_gate.adapters.sqlite import SqliteAdapter, init_db

        with tempfile.TemporaryDirectory() as d:
            db = os.path.join(d, "store.db")
            conn = init_db(db)
            for e in ENTRIES:
                conn.execute(
                    "INSERT INTO entries VALUES (?,?,?,?,?,?)",
                    (e["id"], e["title"], e["body"], e["summary"],
                     json.dumps(e["topics"]), e["ts"]),
                )
            conn.commit()
            conn.close()
            entries = SqliteAdapter(db).list_visible()
            self.assertEqual(len(entries), len(ENTRIES))
            hits = rank_entries(entries, parse_keywords("database migration"))
            self.assertEqual(hits[0]["id"], "e1")
            self.assertEqual(hits[0]["score"], 10)


if __name__ == "__main__":
    unittest.main()
