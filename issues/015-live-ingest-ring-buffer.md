# 015 — Live ingest and ring buffer

| | |
| --- | --- |
| **Milestone** | M3 Live |
| **Depends on** | 003, 013 (gate) |
| **Blocks** | 016, 017 |
| **Size** | M |

## Why

Live detection always lags the event — the sponsor-detection repo documents its audio mode
capturing the first seconds of a read for exactly this reason. **The ring buffer is what
makes the lag recoverable**: if the last 90 seconds of transcript and cut points are still
in memory when the trigger fires, the real start is still addressable.

No buffer, no retro-start, and live mode is just a worse VOD mode.

## Build

- Streaming ASR with interim + final results: Deepgram, or faster-whisper over a rolling
  window. Abstract behind one interface so the provider is swappable.
- **Ring buffer: 90s** of finalized sentences, with cut points extracted incrementally via
  003 as sentences finalize.
- Media recorder running continuously into a rolling segment file, so a clip can be cut
  from the past — the transcript buffer is useless if the video is already gone.
- Buffer exposes: `recent(seconds)` for the tick state, `cuts()` for the retro-start
  options, `text_since(t)` for the tail.
- Wall-clock ↔ stream-time mapping, held in code. Jev never sees a timestamp.

## Acceptance criteria

- [ ] Sustains a 1080p stream with <2s ASR latency.
- [ ] Buffer holds exactly 90s ±1 sentence, memory flat over an 8-hour run.
- [ ] Cut points available for the whole buffer at any moment.
- [ ] Recorded media covers the full buffer window — verify by cutting a clip that starts
      80s in the past.
- [ ] Reconnects after a stream drop without losing the buffer.

## Gotchas

- Interim ASR results are unstable; only finalized sentences enter the buffer, or the same
  text gets judged twice with different wording.
- 90s is a hypothesis. 017 measures `buffer_underrun` and this number gets revised from
  data.
- Disk: continuous recording of a long stream is large. Rolling segments with a retention
  window, not one growing file.
