# 019 — Live-to-VOD tighten pass

| | |
| --- | --- |
| **Milestone** | M3 Live |
| **Depends on** | 006, 007, 017 |
| **Blocks** | — |
| **Size** | S |

## Why

Live gives a clip in ~10s with a soft tail. VOD gives a tight cut a minute later. There's
no reason to choose: once the segment is recorded it *is* a VOD, so re-run D+E on it.

Ship the fast one immediately, replace it with the good one when it lands.

## Build

- After a live clip closes, queue a tighten job: the recorded segment ±30s of buffer
  context, through Pass D and Pass E.
- Emit **v1 (live)** and **v2 (tightened)** with a stable clip ID linking them.
- If v2 fails Pass E's gates, mark v1 for review rather than auto-replacing — live's
  looser cut may still be the better artifact.
- Cost: 2 extra requests per clip. At a handful of clips per stream-hour, negligible.

## Acceptance criteria

- [ ] v2 available within 60s of a clip closing.
- [ ] v2's `start_err` beats v1's on labeled live footage (this is the point).
- [ ] v1 remains available and playable; replacement is explicit, not silent.
- [ ] Tighten failures don't block the live loop (separate queue, separate worker).

## Gotchas

- The tighten pass needs pre-trigger context, which means the ±30s must come from the
  buffer that existed at trigger time. Persist it with the clip; don't try to reconstruct
  it later.
- Measure how often v2 actually differs. If it rarely moves the boundary, live is already
  good enough and this issue is dead weight — that's a real possible outcome, and worth
  finding out cheaply.
