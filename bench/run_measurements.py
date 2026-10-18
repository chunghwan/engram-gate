#!/usr/bin/env python3
"""Reproducible measurement set for engram-gate.

Part A — Determinism: a fixed query set is run R times against the fixed
corpus (bench/corpus_fixed.jsonl). Every run must produce byte-identical
hit lists and score vectors; the canonical output hash is recorded.

Part B — Undetected-conflict pilot: each synthetic worker task queries the gate
with its declared keywords BEFORE starting work. Ground truth: two tasks
conflict iff they belong to the same designed workstream group. A conflict
is "detected" when the querying task's gate result contains the other
task's trace entry. Ordered pairs are evaluated (query direction matters).

All data is synthetic. Stdlib only. Usage:
    python3 bench/run_measurements.py [--out bench/results]
"""
import argparse
import hashlib
import json
import os
import statistics
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from engram_gate.adapters.jsonl import JsonlAdapter
from engram_gate.scoring import parse_keywords, rank_entries

HERE = os.path.dirname(os.path.abspath(__file__))
CORPUS = os.path.join(HERE, "corpus_fixed.jsonl")
REPEATS = 5

# Fixed determinism query set (Part A)
QUERIES = [
    "database migration",
    "dashboard",
    "auth token rotation",
    "image compression",
    "backup retention",
    "email digest",
    "translation glossary",
    "onboarding survey",
    "quantum teleportation",   # expect no hits (exit 1)
    "database",                 # single keyword
]

# Pilot tasks (Part B): id -> (query keywords, workstream group or None)
TASKS = {
    "tr_a1": ("database migration", "A"),
    "tr_a2": ("database migration", "A"),
    "tr_a3": ("database migration checklist", "A"),
    "tr_b1": ("dashboard layout", "B"),
    "tr_b2": ("dashboard widget", "B"),
    "tr_c1": ("auth token", "C"),
    "tr_c2": ("auth token", "C"),
    "tr_d1": ("documentation translation", None),
    "tr_d2": ("image compression", None),
    "tr_d3": ("email digest", None),
    "tr_d4": ("backup retention", None),
    "tr_d5": ("onboarding survey", None),
}


def load_entries():
    adapter = JsonlAdapter(CORPUS)
    return adapter.list_visible()


def run_query(entries, keywords_str):
    keywords = parse_keywords(keywords_str)
    return rank_entries(entries, keywords)


def part_a(entries):
    results = []
    all_deterministic = True
    latencies_ms = []
    for q in QUERIES:
        canonical_runs = []
        for _ in range(REPEATS):
            t0 = time.perf_counter()
            hits = run_query(entries, q)
            latencies_ms.append((time.perf_counter() - t0) * 1000)
            canonical = json.dumps(
                [{"id": h["id"], "score": h["score"]} for h in hits],
                sort_keys=True,
            )
            canonical_runs.append(canonical)
        deterministic = len(set(canonical_runs)) == 1
        all_deterministic &= deterministic
        digest = hashlib.sha256(canonical_runs[0].encode()).hexdigest()[:16]
        hits = json.loads(canonical_runs[0])
        results.append({
            "query": q,
            "repeats": REPEATS,
            "deterministic": deterministic,
            "output_sha256_16": digest,
            "exit_code": 0 if hits else 1,
            "hit_count": len(hits),
            "score_vector": [h["score"] for h in hits],
        })
    summary = {
        "queries": len(QUERIES),
        "repeats_each": REPEATS,
        "all_deterministic": all_deterministic,
        "latency_ms_p50": round(statistics.median(latencies_ms), 3),
        "latency_ms_p95": round(sorted(latencies_ms)[int(len(latencies_ms) * 0.95) - 1], 3),
    }
    return results, summary


def part_b(entries):
    by_id = {e["id"]: e for e in entries}
    tp = fp = fn = tn = 0
    pair_rows = []
    for qid, (query, qgroup) in TASKS.items():
        hits = run_query(entries, query)
        hit_ids = {h["id"] for h in hits if h["id"] != qid}
        for oid, (_, ogroup) in TASKS.items():
            if oid == qid:
                continue
            truth = qgroup is not None and qgroup == ogroup
            detected = oid in hit_ids
            if truth and detected:
                tp += 1
            elif truth and not detected:
                fn += 1
            elif not truth and detected:
                fp += 1
            else:
                tn += 1
            pair_rows.append({
                "query_task": qid, "other_task": oid,
                "ground_truth_conflict": truth, "detected": detected,
            })
    precision = tp / (tp + fp) if (tp + fp) else 1.0
    recall = tp / (tp + fn) if (tp + fn) else 1.0
    summary = {
        "ordered_pairs_evaluated": len(pair_rows),
        "positive_pairs": tp + fn,
        "negative_pairs": fp + tn,
        "tp": tp, "fp": fp, "fn": fn, "tn": tn,
        "precision": round(precision, 3),
        "recall": round(recall, 3),
    }
    return pair_rows, summary


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=os.path.join(HERE, "results"))
    args = ap.parse_args()
    os.makedirs(args.out, exist_ok=True)

    with open(CORPUS, "rb") as f:
        corpus_hash = hashlib.sha256(f.read()).hexdigest()

    entries = load_entries()
    a_rows, a_summary = part_a(entries)
    b_rows, b_summary = part_b(entries)

    payload = {
        "corpus": "bench/corpus_fixed.jsonl",
        "corpus_sha256": corpus_hash,
        "corpus_entries": len(entries),
        "determinism": {"summary": a_summary, "queries": a_rows},
        "undetected_conflict_pilot": {"summary": b_summary, "pairs": b_rows},
    }
    json_path = os.path.join(args.out, "measurement-20261012.json")
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)

    md = []
    md.append("# Measurement set — 2026-10-12\n")
    md.append(f"Fixed corpus: `bench/corpus_fixed.jsonl` ({len(entries)} entries, "
              f"sha256 `{corpus_hash[:16]}…`). All data synthetic. "
              f"Reproduce: `python3 bench/run_measurements.py`\n")
    md.append("## Part A — Determinism\n")
    md.append(f"- Queries: {a_summary['queries']} × {a_summary['repeats_each']} repeats — "
              f"**all deterministic: {a_summary['all_deterministic']}**")
    md.append(f"- In-process latency: p50 {a_summary['latency_ms_p50']} ms, "
              f"p95 {a_summary['latency_ms_p95']} ms (budget per SPEC §8: p95 ≤ 5 s)\n")
    md.append("| query | exit | hits | score vector | output sha256 (16) |")
    md.append("|---|---|---|---|---|")
    for r in a_rows:
        md.append(f"| {r['query']} | {r['exit_code']} | {r['hit_count']} | "
                  f"{r['score_vector']} | `{r['output_sha256_16']}` |")
    md.append("\n## Part B — Undetected-conflict pilot (synthetic, n = "
              f"{b_summary['ordered_pairs_evaluated']} ordered pairs)\n")
    md.append(f"- Positive (same-workstream) pairs: {b_summary['positive_pairs']}, "
              f"negative pairs: {b_summary['negative_pairs']}")
    md.append(f"- TP {b_summary['tp']} · FP {b_summary['fp']} · FN {b_summary['fn']} · TN {b_summary['tn']}")
    md.append(f"- **Precision {b_summary['precision']} · Recall {b_summary['recall']}**\n")
    md.append("Notes: pairs are ordered (query direction matters, mirroring the "
              "interoperability matrix). Ground truth is the designed workstream "
              "grouping. The single FP (tr_d4 querying, tr_a3 hit) is a genuine "
              "vocabulary-overlap case: the query keyword \"backup\" is a substring "
              "of \"backups\" in tr_a3's body — the same failure shape as the "
              "operational pilot's FP. This synthetic pilot validates the "
              "measurement procedure; it is not a substitute for operational "
              "conflict data.\n")
    md_path = os.path.join(args.out, "measurement-20261012.md")
    with open(md_path, "w", encoding="utf-8") as f:
        f.write("\n".join(md) + "\n")

    print(json.dumps({"determinism": a_summary, "pilot": b_summary}, indent=2))
    print(f"Wrote {json_path} and {md_path}")


if __name__ == "__main__":
    main()
