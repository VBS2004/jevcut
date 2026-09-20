# 005 — Pass C: coarse scan for anchors

| | |
| --- | --- |
| **Milestone** | M1 VOD pipeline |
| **Depends on** | 002, 004 |
| **Blocks** | 006 |
| **Size** | M |

## Why

The cheap half of the cascade. One request per 80-sentence window finds the lines worth
spending real money on. Everything downstream costs 2 requests per survivor, so this
gate's threshold *is* the cost model.

## Build

- Split transcript into **80-sentence windows**, 10-sentence overlap so a moment straddling
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
