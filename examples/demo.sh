#!/usr/bin/env bash
# Demo: two queries against the synthetic example corpus.
# Query 1 matches prior work -> exit 0. Query 2 matches nothing -> exit 1.
set -u
DIR="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(cd "$DIR/.." && pwd)"
export PYTHONPATH="$ROOT/src${PYTHONPATH:+:$PYTHONPATH}"
LEDGER="$(mktemp)"
trap 'rm -f "$LEDGER"' EXIT

echo "== Query 1: 'database migration' (expect exit 0, hits) =="
python3 -m engram_gate query "database migration" --agent demo \
  --store "$DIR/corpus.jsonl" --ledger "$LEDGER"
echo "exit code: $?"
echo
echo "== Query 2: 'quantum teleportation' (expect exit 1, no hits) =="
python3 -m engram_gate query "quantum teleportation" --agent demo \
  --store "$DIR/corpus.jsonl" --ledger "$LEDGER"
echo "exit code: $?"
echo
echo "== Ledger written to a temp file (2 entries) =="
cat "$LEDGER"
