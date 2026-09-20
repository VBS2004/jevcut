# 008 — Pass F: ranking, gates and overlap resolution

| | |
| --- | --- |
| **Milestone** | M1 VOD pipeline |
| **Depends on** | 007 |
| **Blocks** | 009 |
| **Size** | M |

## Why

Where policy lives, in code, so it can change without re-running inference. Keeping raw
judgments and policy separate is what makes 014's threshold sweeps cost $0.

## Build

`src/jevcut/rank.py`, pure functions over the judgment records — **no API calls in this
module**, enforced by a test.

- **Hard gates** (fail ⇒ widen once via 006, then drop):
  `starts_mid_thought > 0.5`, `dangling_reference > 0.5`, `payoff` expectation in the
  bottom level. An "any serious defect" rule needs separate conditions, not a weighted
  average that lets a strong hook buy off a broken opening.
- **Composite score** for ranking (weighted, compensating dimensions only):
  `hook`, `payoff`, `p_moment`, `standalone`, anchor confidence. Weights in config.
- **Duration policy:** per-preset band (default 25–75s). Outside the band ⇒ re-ask 006
  with a wider or narrower region. **Never trim to fit** — a clip that doesn't fit the
  band was cut wrong, and trimming hides that.
- **Overlap resolution:** clips sharing >40% of their span, keep the higher composite.
- Output top-N plus every rejected clip **with its rejection reason** — the rejects are
  what 012 needs to compute the hard-negative rate.

## Acceptance criteria

- [ ] Changing any weight and re-running makes **zero** API calls (004 verifies).
- [ ] Gates and weights are separate code paths; no gate is expressible as a weight.
- [ ] Rejected clips are persisted with reasons, not dropped.
- [ ] Overlap resolution is deterministic given the same inputs.

## Gotchas

- Uncertainty on unused branches is irrelevant — if `cold_open_ok` didn't drive the
  decision, its confidence doesn't enter the score.
- Confidence summarizes how concentrated a distribution is. It is not a measure of whether
  the overall pipeline is right, and it is not permission to ship.
- Default thresholds here are placeholders until 014. Mark them as such in the config so
  nobody mistakes a guess for a finding.
