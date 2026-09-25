# 013 — Baseline comparison

| | |
| --- | --- |
| **Milestone** | M2 Measure |
| **Depends on** | 012 |
| **Blocks** | M3 (this is the gate) |
| **Size** | M |
| **Status** | **Run on 38 videos, 2026-09-25: not passed.** jevcut beats all five baselines on recall (0.52 / 0.54 vs at best 0.45), clips with both edges right (35 / 33 vs at best 15 / 12), precision and median start error (1.5 / 2.0s vs 5-7s), and on the judged mid-thought rate, and holds up on the 30 videos it was not developed on. It loses on `start_err_p90` (17.5 / 19.6s vs dense 14.6 / 14.3s, offset 14.9 / 15.0s). Baselines 4 and 5 lose badly, so the boundary thesis holds. [eval/results/baselines.md](../eval/results/baselines.md), RESEARCH.md "013 on 38 videos". |

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
4. **Tuned constant offset from the anchor**: Pass C's anchor minus K seconds, snapped to
   the nearest cut point, with **K swept on the tune split and fixed before scoring**. Not
   the same as baseline 3 — this one starts from the anchor jevcut actually produces, which
   is what Pass D starts from, so it isolates the boundary decision.
   **Added because it beat a Choice on a proxy task**: 5.5s median vs 8.7s over 968 AMI
   topic boundaries ([RESEARCH.md](../RESEARCH.md), `eval/experiments/pick_vs_snap.py`).
   That was a proxy with no noise floor and an untuned question, so it settles nothing — but
   a Pass D that cannot beat *this* is not worth its two requests per clip.
5. **Snap + align, no model** (autoclip-shaped): **jevcut's own Pass C anchor**, then
   boundaries chosen entirely in code — walk out to the nearest sentence end, clamp into
   the duration range landing on sentence ends, align into the silence trough (the
   constants are in [009](009-edl-and-render.md)). No Pass D, no model call for boundaries.

> **Baselines 4 and 5 are the ones that test the thesis.** Baselines 1–3 vary selection *and*
> boundaries together, so a jevcut win doesn't say which half won. Baseline 4 holds
> selection fixed and swaps only the boundary method: Jev, or fifty lines of code. It is
> also the only baseline covering [RESEARCH.md](../RESEARCH.md) failure modes 2 and 4
> ("snapping is good enough", "classical methods already solve it") — the two rated most
> likely to kill the project, and the two nothing here previously tested.
>
> It is shipped and runnable prior art, not a strawman: see
> [autoclip](../docs/PRIOR-ART.md#artbyjaziautoclip). Run autoclip end to end **once** as
> a reality check, but do not use that as the baseline number — different ASR and renderer
> make it uncontrolled.

Publish the comparison table in `eval/results/baselines.md`: all metrics, all costs, all
request counts, per genre.

## Acceptance criteria

- [ ] All six systems run on all 40 videos.
- [ ] Table covers boundary metrics, standalone metrics, selection metrics, cost, requests
      and latency.
- [ ] **Ship criterion: jevcut beats all five on `start_err_p90` AND
      `mid_thought_rate` simultaneously.**
- [ ] Baseline 4 reported separately in prose: beating 1–3 but losing to 4 means selection
      works and the boundary thesis does not. Say so plainly rather than averaging it away.
- [ ] Cost estimates in [COST-MODEL.md](../docs/COST-MODEL.md) replaced with measured
      numbers — including the ones that turn out worse than predicted.

## Gotchas

- If jevcut wins on selection but loses on boundaries, the thesis was wrong. Don't
  rationalize it — see the decision log in [ROADMAP.md](../ROADMAP.md) and try
  sentence-pair boundary Nouls instead of a Choice over cut IDs.
- **Report the variance of the target relative to the anchor, next to every boundary
  result.** If the true boundary sits at a near-constant distance from the anchor, a swept
  constant is near-optimal *by construction* and the comparison cannot discriminate between
  any two methods — it measures the sampling, not the systems. Two proxy experiments were
  wasted on exactly this (stdev 9.5s on a 27s median; see [RESEARCH.md](../RESEARCH.md)).
  A low spread invalidates the run; say so rather than reporting a winner.
- Give the baselines their best shot. A strawman baseline produces a win that evaporates
  the moment someone else runs the comparison.
- Baseline 1 costs ~10× more than jevcut per run. Budget for it, run it once, cache it.
- Baseline 4 costs nothing per run — no model call for boundaries. If it wins, the honest
  read is "use code for boundaries, reserve Jev for worth and standalone", which
  [RESEARCH.md](../RESEARCH.md) already calls a better product than the one designed.
