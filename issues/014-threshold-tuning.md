# 014 — Threshold tuning and calibration

| | |
| --- | --- |
| **Milestone** | M2 Measure |
| **Depends on** | 012, 004 |
| **Blocks** | M4 |
| **Size** | M |

## Why

Every threshold in the config is currently a guess. Thresholds must be evaluated on our
own data and consequences, not inherited from a cookbook — cookbook numbers are examples
to evaluate, not rules.

Because of 004 and the judgment/policy split in 008, this whole issue runs on cached
responses at **zero marginal cost**.

## Build

- Sweep, on cached runs: `contains_moment` gate, anchor-confidence floor, all Pass E gate
  thresholds, composite weights, duration bands, anchors-per-window, region width.
- Also sweep the per-`kind` instruction variants from 006 — those *do* cost API calls, so
  run them last and on a subset.
- Produce **calibration plots** per Noul: predicted probability vs. observed rate on
  labeled data, bucketed. This is the check that a 0.7 threshold means anything.
- Per-genre threshold sets if the sweep shows genre-dependence — feeds 020's presets.
- Write the chosen values into config with a comment naming the run that justified each.

## Acceptance criteria

- [ ] Sweep runs with no API calls (except the instruction-variant subset).
- [ ] Calibration plot per gate Noul, on labeled data.
- [ ] Every threshold in config traceable to a results row.
- [ ] Sensitivity noted: which thresholds move the metrics and which don't.

## Gotchas

- **Don't carry a Noul threshold to a Choice or vice versa.** They answer different
  questions and their numbers aren't comparable — the jaggedness docs show a case where a
  Noul reads 0.22 and the equivalent Choice reads 0.01.
- A threshold tuned on `jev-1.13.0` is not valid on the next version. Pin the version, and
  re-run this issue when it moves.
- Resist tuning on the same videos used to report final numbers. Split the 40 into tune
  (25) and holdout (15), and report on the holdout.
