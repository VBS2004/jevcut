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

## Baseline 0 — trigger minus a constant

The comparison this issue lacked. `retro_recovery` is measured against the true start but
not against the obvious alternative: **start the clip a fixed number of seconds before the
trigger and do nothing else.**

That is what practitioners actually ship.
[StreamClipper](https://github.com/iamashishjaiswal/streamclipper) fires from a chat
command — a human reacting, so late for the same reason detection is — and subtracts a flat
30s (`clip.py:27`). Streamsnip, the commercial product it is an open alternative to, works
the same way. Neither has a model anywhere, and people pay for one of them.

So trigger − 30s is Baseline 0, it costs nothing, and if one retro Choice over the buffered
cut points cannot beat it, live mode is ceremony. Same argument Baseline 4 makes for VOD
boundaries in [013](013-baseline-comparison.md).

It also gives the buffer size a prior instead of a guess: 30s is what people shipping this
think you need to look back, against the 90s budgeted here.

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
- [ ] **Beats Baseline 0** on start error, with both reported. A tie means the retro Choice
      is buying nothing — cut it and subtract a constant, rather than keeping it because it
      is the more interesting design.
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
- Give Baseline 0 its best shot: sweep the constant on the eval set instead of fixing it at
  30s. Beating a badly-tuned constant proves nothing, and 013 already makes this point about
  strawman baselines.
