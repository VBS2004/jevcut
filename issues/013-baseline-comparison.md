# 013 — Baseline comparison

| | |
| --- | --- |
| **Milestone** | M2 Measure |
| **Depends on** | 012 |
| **Blocks** | M3 (this is the gate) |
| **Size** | M |

## Why

**The issue that decides whether this project should exist.** Everything in the README is
a claim about beating existing approaches. Here it either survives or it doesn't.

## Build

Three baselines, same ASR, same cut points, same renderer, same eval set. Only selection
and boundary logic differ.

1. **Dense rolling average** (jevmeter-shaped): score every sentence with the Pass E
   question set, take the highest average over a 10–15s rolling window.
2. **Fixed windows** (jev-skip-shaped): 30s windows snapped to sentence ends, capped 45s,
   one Choice each, top N.
3. **Naive**: top-scoring sentence ±15s. The dumbest thing that works — and the most
   important bar. If the cascade can't beat peak-sentence-plus-padding, it's ceremony.

Publish the comparison table in `eval/results/baselines.md`: all metrics, all costs, all
request counts, per genre.

## Acceptance criteria

- [ ] All four systems run on all 40 videos.
- [ ] Table covers boundary metrics, standalone metrics, selection metrics, cost, requests
      and latency.
- [ ] **Ship criterion: jevcut beats all three on `start_err_p90` AND
      `mid_thought_rate` simultaneously.**
- [ ] Cost estimates in [COST-MODEL.md](../docs/COST-MODEL.md) replaced with measured
      numbers — including the ones that turn out worse than predicted.

## Gotchas

- If jevcut wins on selection but loses on boundaries, the thesis was wrong. Don't
  rationalize it — see the decision log in [ROADMAP.md](../ROADMAP.md) and try
  sentence-pair boundary Nouls instead of a Choice over cut IDs.
- Give the baselines their best shot. A strawman baseline produces a win that evaporates
  the moment someone else runs the comparison.
- Baseline 1 costs ~10× more than jevcut per run. Budget for it, run it once, cache it.
