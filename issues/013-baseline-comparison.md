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
4. **Snap + align, no model** (autoclip-shaped): **jevcut's own Pass C anchor**, then
   boundaries chosen entirely in code — walk out to the nearest sentence end, clamp into
   the duration range landing on sentence ends, align into the silence trough (the
   constants are in [009](009-edl-and-render.md)). No Pass D, no model call for boundaries.

> **Baseline 4 is the one that tests the thesis.** Baselines 1–3 vary selection *and*
> boundaries together, so a jevcut win doesn't say which half won. Baseline 4 holds
> selection fixed and swaps only the boundary method: Jev, or fifty lines of code. It is
> also the only baseline covering [RESEARCH.md](../RESEARCH.md) failure modes 2 and 4
> ("snapping is good enough", "classical methods already solve it") — the two rated most
> likely to kill the project, and the two nothing here previously tested.
>
> It is shipped and runnable prior art, not a strawman: see
> [autoclip](../docs/PRIOR-ART.md#artbyjazi-autoclip). Run autoclip end to end **once** as
> a reality check, but do not use that as the baseline number — different ASR and renderer
> make it uncontrolled.

Publish the comparison table in `eval/results/baselines.md`: all metrics, all costs, all
request counts, per genre.

## Acceptance criteria

- [ ] All five systems run on all 40 videos.
- [ ] Table covers boundary metrics, standalone metrics, selection metrics, cost, requests
      and latency.
- [ ] **Ship criterion: jevcut beats all four on `start_err_p90` AND
      `mid_thought_rate` simultaneously.**
- [ ] Baseline 4 reported separately in prose: beating 1–3 but losing to 4 means selection
      works and the boundary thesis does not. Say so plainly rather than averaging it away.
- [ ] Cost estimates in [COST-MODEL.md](../docs/COST-MODEL.md) replaced with measured
      numbers — including the ones that turn out worse than predicted.

## Gotchas

- If jevcut wins on selection but loses on boundaries, the thesis was wrong. Don't
  rationalize it — see the decision log in [ROADMAP.md](../ROADMAP.md) and try
  sentence-pair boundary Nouls instead of a Choice over cut IDs.
- Give the baselines their best shot. A strawman baseline produces a win that evaporates
  the moment someone else runs the comparison.
- Baseline 1 costs ~10× more than jevcut per run. Budget for it, run it once, cache it.
- Baseline 4 costs nothing per run — no model call for boundaries. If it wins, the honest
  read is "use code for boundaries, reserve Jev for worth and standalone", which
  [RESEARCH.md](../RESEARCH.md) already calls a better product than the one designed.
