# 017 — Retro-start and tail

| | |
| --- | --- |
| **Milestone** | M3 Live |
| **Depends on** | 016 |
| **Blocks** | 019 |
| **Size** | M |

## Why

**The issue that justifies live mode existing.** The trigger fires at T, but the moment
started well before T. One Choice over the buffered cut points recovers the real start —
this is the direct fix for the known weakness in the prior art, where live audio mode eats
the opening seconds of the segment it's detecting.

If `retro_recovery` comes out low, live mode should be cut. This issue is where we find out.

## Build

- On `ARMED → RECORDING`: one `RETRO_START` Choice over the buffer's cut points
  ([QUESTIONS.md](../docs/QUESTIONS.md#pass-r--retro-start-live)). Clip starts there, not
  at T.
- `before_this_buffer` ⇒ start at the buffer's oldest cut, flag it, count it toward
  `buffer_underrun`.
- On `RECORDING → COOLDOWN`: one `end_cut` Choice over cut points since the trigger.
- Cut media from the rolling recording using the recovered timestamps.
- Measure and log per clip: `detection_lag` (trigger − true start),
  `retro_recovery` = recovered / lag.

## Acceptance criteria

- [ ] Clip start precedes the trigger by a measurable margin on ≥80% of triggers.
- [ ] **`retro_recovery` > 80% median** against labeled live footage.
- [ ] `buffer_underrun` < 10%; if higher, raise the buffer past 90s and re-measure.
- [ ] Total added latency < 2s (two extra requests, one per clip, not per tick).
- [ ] End-to-end: clip file exists within 10s of the moment ending.

## Gotchas

- Retro-start needs the *media* too, not just the transcript. 015's rolling recorder is a
  hard dependency — confirm it before measuring anything here.
- The retro Choice sees a buffer ending mid-moment, unlike Pass D which sees the whole
  thing. Expect lower confidence, and don't reuse Pass D's threshold here.
- Compare against the VOD pipeline on the same footage. That difference is the honest
  price of live, and it belongs in the README.
