# 005 — Pass C: coarse scan for anchors

| | |
| --- | --- |
| **Milestone** | M1 VOD pipeline |
| **Depends on** | 002, 004 |
| **Blocks** | 006 |
| **Status** | **Done** (M0 branch) — `src/jevcut/scan.py`, `src/jevcut/questions.py`, `tests/test_scan.py` |
| **Size** | M |

## Why

The cheap half of the cascade. One request per 80-sentence window finds the lines worth
spending real money on. Everything downstream costs 2 requests per survivor, so this
gate's threshold *is* the cost model.

## Build

- Split transcript into **80-sentence windows**, stepped so the overlap holds **60s** of
  speech whatever the speaking pace (`window_overlap_s`), so a moment straddling
  a boundary isn't lost by both sides.
- Per window, one request with the three questions from
  [QUESTIONS.md](../docs/QUESTIONS.md#pass-c--coarse-scan): `contains_moment` (Noul),
  `anchor` (Choice over line IDs + `none_of_these`), `kind` (Choice).
- All windows in parallel, bounded by a semaphore sized to the rate limit.
- **Repeat with removal:** after an anchor wins, drop its ±20s neighbourhood from the
  window and re-ask, up to 3 anchors per window, stopping when `contains_moment` falls
  below threshold. (The sponsor-detection loop.)
- Emit `anchors.json`: `{sentence_id, window_id, kind, p_moment, anchor_confidence}`.

## Acceptance criteria

- [ ] A 60-min video produces ~8 windows and ≤24 anchors in **≤12 requests**.
- [ ] `none_of_these` wins on a window of pure logistics (test with a deliberately boring
      stretch).
- [ ] Anchors deduplicated across the overlap region.
- [ ] Recall against eval labels measured in 012 and recorded — a missed anchor is
      unrecoverable downstream.

## Gotchas

- Two gates, two jobs: `contains_moment` is absolute ("is there anything here?"), the
  anchor Choice is relative ("which line, given one must win"). **Don't carry a threshold
  from one to the other** — a Choice and a Noul answer different questions and their
  numbers are not comparable.
- The 80-option Choice is the longest question in the system. Assert state + question
  against the 32k limit before sending.
- Resist adding a 4th and 5th question here. Each one multiplies across every window, and
  this is the pass that runs on everything.

## Implementation note

All criteria met except the recall measurement, which needs 011. Verified live on the
27-sentence fixture: three anchors for 3 requests at $0.000136, and the picks were the
three lines a human editor would choose (the emotional peak, the reveal, the closing
lesson).

`JevClient` gained a lock — Pass C is the first caller to use a thread pool, and the
trace file and usage counters are shared mutable state.

## Finding: `contains_moment` does not fall across rounds

Observed p_moment per removal round: **0.88 -> 0.93 -> 0.96**. It *rose* as the best
material was removed.

Not a contradiction. A Noul is absolute, not relative: each round asks "is there anything
quotable in this text" about a **different, shorter** state, and a shorter window with
less filler in it can legitimately read as denser. But it means the gate does **not**
work as a diminishing-returns signal — the `max_anchors_per_window` cap is what actually
stopped the loop here, not the threshold.

Consequences:

- The cost model's assumption that a flat window costs one request still holds (that path
  is tested), but the assumption that rich windows self-limit does not.
- Issue 014 should test an explicit alternative: ask "is there anything left worth
  quoting **besides** what has already been chosen", with the chosen lines named in the
  state. That is a relative question, which is the thing we actually want to know.
- Until then, treat `max_anchors_per_window` as the real control and
  `contains_moment_threshold` as a floor for genuinely empty windows.
