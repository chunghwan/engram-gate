# Measurement set — 2026-10-12

Fixed corpus: `bench/corpus_fixed.jsonl` (12 entries, sha256 `6d3ac84c6c8fcaac…`). All data synthetic. Reproduce: `python3 bench/run_measurements.py`

## Part A — Determinism

- Queries: 10 × 5 repeats — **all deterministic: True**
- In-process latency: p50 0.022 ms, p95 0.032 ms (budget per SPEC §8: p95 ≤ 5 s)

| query | exit | hits | score vector | output sha256 (16) |
|---|---|---|---|---|
| database migration | 0 | 3 | [10, 10, 8] | `a14076984d66f218` |
| dashboard | 0 | 2 | [5, 5] | `fb69361e1c21cf8c` |
| auth token rotation | 0 | 2 | [12, 8] | `61f85bf4269bd1a2` |
| image compression | 0 | 1 | [10] | `e65f1eba181dce41` |
| backup retention | 0 | 2 | [10, 2] | `fcd1428685e1c560` |
| email digest | 0 | 1 | [10] | `30d9170063fdbbc7` |
| translation glossary | 0 | 1 | [7] | `89240e45f1b90d9d` |
| onboarding survey | 0 | 1 | [10] | `1e07148ff3eccba8` |
| quantum teleportation | 1 | 0 | [] | `4f53cda18c2baa0c` |
| database | 0 | 3 | [5, 5, 3] | `0277eac38c264253` |

## Part B — Undetected-conflict pilot (synthetic, n = 132 ordered pairs)

- Positive (same-workstream) pairs: 10, negative pairs: 122
- TP 10 · FP 1 · FN 0 · TN 121
- **Precision 0.909 · Recall 1.0**

Notes: pairs are ordered (query direction matters, mirroring the interoperability matrix). Ground truth is the designed workstream grouping. The single FP (tr_d4 querying, tr_a3 hit) is a genuine vocabulary-overlap case: the query keyword "backup" is a substring of "backups" in tr_a3's body — the same failure shape as the operational pilot's FP. This synthetic pilot validates the measurement procedure; it is not a substitute for operational conflict data.

