# Roadmap

> **Research phase concluded 2026-09-22; the design changed.** Code now sets boundaries and
> Jev judges clips, so 006 (Pass D) left the critical path and 007 joined it — see the
> decision log below and [RESEARCH.md](RESEARCH.md). M1 runs end to end as `jevcut run`.
> The thesis paragraph below is the original plan, kept as written.

## Now (2026-09-24)

In order of what the numbers say costs the most. Scores for every step go through
`jevcut bench` on both v2 labelers ([BENCHMARKS.md](BENCHMARKS.md)).

- [x] **1. Scan recall.** Every window stopped on the 3-round cap, never on
      `contains_moment`. Cap raised to 6: moments never anchored 24 → 13 (v2 A), recall
      0.38 → 0.54 on Lemonfox transcripts, precision −2–4 points. Requests: ~520 per hour of
      video after the ending early stop (~$0.03), 660 without it.
- [ ] **2. Lemonfox by default** when `LEMONFOX_API_KEY` is set, local Whisper otherwise.
      It raised recall on all four label sets (~$0.17 per hour of media).
- [ ] **3. A screen question.** After ads, the hard negatives the gate lets through are
      mostly narration of the screen. Spread-test on the labeled texts before wiring in.
- [x] **013 baselines, run on the pilot set.** jevcut beats all five on recall, fully right
      clips, precision and median start error; **not passed** on `start_err_p90` (its
      start misses are large). [eval/results/baselines.md](eval/results/baselines.md)
- [ ] **4. Fix the openings' tail.** The opening Choice's misses are 15-21s off, worse than
      simple padding at p90. Tried 2026-09-25, neither kept: offering openings after the
      anchor, and rewording the Choice (RESEARCH.md). The far-off starts mostly follow a
      scan anchor that closes the thought before. The eval set is now 38 videos (~100 matched
      clips per labeler), and the tail is still there (p90 17.5 / 19.6s vs dense 14.6 / 14.3s):
      it is real, and measurable now.
- [ ] **5. One human review pass** on two videos: every labeler so far is the same model,
      so the 0.0s start agreement is a lower bound.

Next, by the user's call (2026-09-25): **phase 2, non-verbal event clips
([021](issues/021-event-clips.md)), in a fresh session** -- even though 013 has not
passed (jevcut wins on everything but the worst starts; RESEARCH.md "013 on 38 videos").

Done this round: the live terminal display (`ui.py`), the shortlist check on openings,
set 2 (38 videos, labeled twice), rubric v2 and two blind label sets, the shortest clean ending, the opening
Choice, the ad check, Lemonfox transcription, `jevcut bench` (RESEARCH.md has each).

20 issues, 5 milestones. Ordered so that **the thing most likely to kill the project gets
tested earliest**: if Pass D can't pick boundaries better than "peak sentence ± 15s", the
whole thesis is wrong, and M2 is where that becomes undeniable.

## Milestones

| # | Milestone | Issues | Exit criterion |
| --- | --- | --- | --- |
| M0 | Foundations | 001–004 | A transcript with cut points goes in, a cached Jev response comes back |
| M1 | VOD pipeline | 005–010 | Rendered clips end to end — **met by `jevcut run`** |
| M2 | **Measure** | 011–014 | jevcut beats all 3 baselines on boundary + standalone metrics |
| M3 | Live | 015–017, 019 | Live stream produces a clip within 10s, retro-start recovers >80% of lag |
| M4 | Product | 018, 020 | Budget guard, presets, CLI anyone can run |

**M2 is a gate, not a phase.** If jevcut doesn't beat the naive baseline there, stop and
redesign rather than building M3 on a false premise.

## Critical path

```
001 ─┬─ 002 ── 003 ─┬─ 005 ── 006 ── 007 ── 008 ── 009
     └─ 004 ────────┘                  │
                                       └── 010 ── 011 ── 012 ── 013 ── 014  ◀── GATE
                                                                          │
                                                        015 ── 016 ── 017 ─┴─ 019
                                                        018, 020 (any time after M1)
```

## Index

### M0 — Foundations
- [001 — Project scaffold and Jev client wrapper](issues/001-scaffold-and-client.md)
- [002 — Transcript ingest and sentence model](issues/002-transcript-ingest.md)
- [003 — Cut-point extraction](issues/003-cut-point-extraction.md)
- [004 — Response cache and deterministic replay](issues/004-response-cache.md)

### M1 — VOD pipeline
- [005 — Pass C: coarse scan for anchors](issues/005-pass-c-coarse-scan.md)
- [006 — Pass D: boundary refinement](issues/006-pass-d-boundary-refinement.md) — **off the
  critical path.** Boundaries are set in code now; revisit only if the gate shows the code
  boundaries are what is wrong with the clips
- [007 — Pass E: standalone gate](issues/007-pass-e-standalone-gate.md)
- [008 — Pass F: ranking, gates and overlap resolution](issues/008-pass-f-ranking.md)
- [009 — EDL output and ffmpeg render](issues/009-edl-and-render.md)
- [010 — Trace logging and failure triage](issues/010-trace-logging.md)

### M2 — Measure
- [011 — Eval set and labeling protocol](issues/011-eval-set.md)
- [012 — Metrics harness](issues/012-metrics-harness.md)
- [013 — Baseline comparison](issues/013-baseline-comparison.md)
- [014 — Threshold tuning and calibration](issues/014-threshold-tuning.md)

### M3 — Live
- [015 — Live ingest and ring buffer](issues/015-live-ingest-ring-buffer.md)
- [016 — Live trigger FSM with hysteresis](issues/016-live-trigger-fsm.md)
- [017 — Retro-start and tail](issues/017-retro-start-and-tail.md)
- [019 — Live-to-VOD tighten pass](issues/019-live-to-vod-tighten.md)

### M4 — Product
- [018 — Cost telemetry and budget guard](issues/018-cost-telemetry.md)
- [020 — CLI and content presets](issues/020-cli-and-presets.md)

### Deferred (post-v1)
- [021 — Event clips: non-verbal moments](issues/021-event-clips.md) — v1 is verbal-only by
  decision. Not on the critical path; do not start before the M2 gate passes.

## Sizes

`S` ≈ half a day · `M` ≈ 1–2 days · `L` ≈ 3–5 days · `XL` ≈ a week+ (usually because it
involves humans labeling things).

## Decision log

Things that would change the plan, and what we'd do:

| If | Then |
| --- | --- |
| Pass D loses to naive ±15s on `start_err_p90` (013) | Thesis dead. Try sentence-pair boundary Nouls instead of a Choice over cut IDs, then re-run 013 |
| `before_this_region` fires on >25% of anchors (006) | ±90s region too narrow — widen to ±150s and re-measure tokens |
| `retro_recovery` < 50% (017) | Cut live mode. It's a worse VOD mode |
| Pass C misses >30% of labeled clips (012) | Gate too tight — lower `contains_moment`, accept more anchors, let Pass E do the rejecting |
| `jev-latest` moves mid-project | Pin the old version ID, re-run 012 on both, migrate deliberately |
| Pass C recall is low and the misses are non-verbal (012) | **Not a threshold problem.** Don't loosen `contains_moment` — that row above applies to verbal misses only. Event clips need [021](issues/021-event-clips.md) |
| Event clips turn out to need no Choice (mechanical boundaries) | Thesis is scoped to verbal content, not general. Say so; it's a finding, not a defeat |
| **RESOLVED 2026-09-22 — arithmetic stayed competitive at boundaries across 5 experiments** | **Design changed: code owns boundaries (snap + silence align, no model call), Jev owns judgment (worth / standalone / payoff). 006 leaves the critical path; 007 joins it.** See [RESEARCH.md](RESEARCH.md) |
