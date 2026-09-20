# 016 — Live trigger FSM with hysteresis

| | |
| --- | --- |
| **Milestone** | M3 Live |
| **Depends on** | 015 |
| **Blocks** | 017 |
| **Size** | S |

## Why

One Noul every 4 seconds decides when something is happening. Raw thresholding on that
signal flickers — a pause mid-sentence drops the probability and ends a clip that was
still going. Hysteresis is the whole issue.

## Build

- Tick every **4s**: one `in_moment` Noul over the last 60s of buffer
  ([QUESTIONS.md](../docs/QUESTIONS.md#pass-l--live-tick)). The sponsor-detection cadence.
- FSM: `IDLE → ARMED → RECORDING → COOLDOWN`
  - `IDLE → ARMED`: one tick `p > 0.70`
  - `ARMED → RECORDING`: a second consecutive tick `p > 0.70` (fires 017's retro-start)
  - `RECORDING → COOLDOWN`: three consecutive ticks `p < 0.40`
  - `COOLDOWN`: 20s minimum before re-arming, so one long moment isn't chopped into three
- Hard cap on recording length; on cap, close the clip and immediately re-arm.
- Emit trigger events with the full tick history attached — 012 needs it for
  `detection_lag`.

## Acceptance criteria

- [ ] Steady ~15 requests/min per stream.
- [ ] Replaying a recorded stream produces identical trigger points (determinism via 004).
- [ ] A 3s mid-moment pause does not end a clip (fixture test).
- [ ] `false_trigger_rate` measured over ≥5 hours of stream.
- [ ] All four thresholds in config, sweepable by 014.

## Gotchas

- **A Noul near 0.5 means yes and no are similarly likely — not "medium intensity."** This
  is a gate, never a dial. Don't build "clip strength" out of the tick probability.
- "RIGHT NOW — at the end of this text" in the instruction is load-bearing. Without it Jev
  answers about the whole 60s window and the FSM fires on moments that already ended.
- Don't let the tick state grow past 60s. More context here is context rot, and it also
  makes the question answer about the wrong thing.
