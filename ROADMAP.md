# Roadmap

20 issues, 5 milestones. Ordered so that **the thing most likely to kill the project gets
tested earliest**: if Pass D can't pick boundaries better than "peak sentence ± 15s", the
whole thesis is wrong, and M2 is where that becomes undeniable.

## Milestones

| # | Milestone | Issues | Exit criterion |
| --- | --- | --- | --- |
| M0 | Foundations | 001–004 | A transcript with cut points goes in, a cached Jev response comes back |
| M1 | VOD pipeline | 005–010 | `jevcut run video.mp4` produces rendered clips end to end |
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
- [006 — Pass D: boundary refinement](issues/006-pass-d-boundary-refinement.md)
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
