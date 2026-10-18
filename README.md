# engram-gate

A **deterministic coordination gate** for multi-agent fleets.

Before an agent starts work, it asks one question of a shared trace store:
*is there related prior work?* engram-gate answers with an **exit code** and
JSON evidence — no LLM calls, no embeddings, no randomness on the query path.

The contract is store-agnostic: it sits in front of any trace store
(a JSONL file, SQLite, or your own adapter), and it is advisory — the gate
presents evidence, the caller decides.

Specification: [SPEC.md](SPEC.md) (v1.0) ·
Korean edition: [SPEC.ko.md](SPEC.ko.md)

## 30-second demo

```bash
pip install -e .
engram-gate query "database migration" --agent demo \
  --store examples/corpus.jsonl --ledger /tmp/ledger.jsonl
echo "exit code: $?"   # 0 — related prior work exists
```

Output:

```json
{"exit_code": 0, "hits": [{"id": "sess_demo_001", "score": 10, "title": "Database migration plan for the billing service"}, {"id": "sess_demo_004", "score": 7, "title": "Database backup verification run"}]}
```

Or run both the hit and no-hit cases:

```bash
bash examples/demo.sh
```

## Exit codes

| Code | Meaning | What the caller should do |
|---|---|---|
| `0` | Related prior work exists | Read the JSON evidence on stdout; plan around the prior work |
| `1` | No related prior work | Proceed with the work |
| `2` | Error (bad input, unreadable store, timeout) | **Do not** treat as "no prior work" — retry or hold |

The 1-vs-2 distinction is the safety property of the contract: "cannot
answer" is never disguised as "all clear".

## How scoring works

```
score(s) = Σ_k (2·titleHit(s,k) + 2·bodyHit(s,k) + 1·topicHit(s,k))
```

Each query keyword is matched as a case-insensitive substring against the
entry title, body (including summary), and topics. Scores sum per keyword
with **no cap** — ranking discrimination is the point. A display `LIMIT`
(default 8) only truncates how many hits are shown; it never changes scores.

Every query is appended to an append-only JSONL **ledger** with a
`ts-agent-seq` query id, the score vector, and the exit code — an audit
trail you can analyse later.

## Usage

```
engram-gate query "<keywords>" [--days N] [--no-refresh] [--agent ID]
                  [--store PATH] [--ledger PATH] [--limit N] [--timeout SECONDS]
```

- `--store`: a `.jsonl` file (or a directory containing `corpus.jsonl` /
  `traces.jsonl`), or a `.db` / `.sqlite` file for the SQLite adapter.
- `--days N`: only consider entries newer than N days.
- `--no-refresh`: frozen-corpus mode; skip delta ingestion (a no-op for
  the file adapters, part of the contract for live stores).
- `--timeout SECONDS`: per-query wall-clock ceiling (default 5 — the §8
  budget's ceiling). Past it the query is interrupted and exits `2` with
  a timeout error: a timeout is never read as "no prior work" (SPEC §8).

### MCP server

A minimal stdio MCP server exposing a `gate_query` tool is included:

```bash
engram-gate-mcp
```

It wraps the same contract as the CLI: every query is appended to an
append-only JSONL ledger (default `ledger.jsonl`), and exit codes follow
the same 0/1/2 semantics. Override with the `ledger` argument or pass
`no_ledger: true`. Malformed requests are answered with JSON-RPC errors —
they never kill the server process.

## Install

```bash
pip install -e .        # from a clone of this repository
python3 -m pytest tests/conformance -q   # or: python3 -m unittest discover -s tests/conformance -v
```

Pure Python standard library — no runtime dependencies. Python ≥ 3.9.

## Repository layout

```
SPEC.md                  normative specification, v1.0 (frozen)
SPEC.ko.md               Korean edition of the specification
src/engram_gate/         CLI, scoring, ledger, adapters (JSONL/SQLite), MCP server
examples/                synthetic corpus + demo.sh
tests/conformance/       spec conformance tests
```

## License

Apache License 2.0 — see [LICENSE](LICENSE).

Copyright 2026 blushine
