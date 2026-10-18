# Benchmark / measurement set

Reproducible measurements: score determinism over a fixed corpus, plus an
undetected-conflict pilot.

- `corpus_fixed.jsonl` — fixed synthetic corpus (12 entries). Never changes
  without a new measurement file; its sha256 is recorded in every result.
- `run_measurements.py` — stdlib-only runner:
  - Part A: determinism (fixed query set × 5 repeats, byte-identical check)
  - Part B: undetected-conflict pilot (132 ordered task pairs, designed
    ground-truth workstream groups, precision/recall)
- `results/` — generated outputs (JSON + Markdown) per measurement date.

Reproduce:

```
python3 bench/run_measurements.py
```
