# 002 — Transcript ingest and sentence model

| | |
| --- | --- |
| **Milestone** | M0 Foundations |
| **Depends on** | 001 |
| **Blocks** | 003, 005 |
| **Status** | **Done** (M0 branch) — `src/jevcut/transcript.py`, `tests/test_transcript.py`. Local faster-whisper, or hosted Lemonfox with `--model lemonfox` (2026-09-24): punctuation and speaker labels, recall up on every label set (RESEARCH.md) |
| **Size** | M |

## Why

Jev is text-only — "no image, audio, or video input". The transcript *is* the state, so
its quality is the ceiling on everything downstream. Sentence boundaries and word-level
timings are what make a cut point addressable.

## Build

- Input: local media file, or a URL via `yt-dlp`.
- ASR: `faster-whisper` with `word_timestamps=True`. Diarization optional (pyannote) —
  speaker labels improve Pass C and are required for per-speaker presets later.
- **If the platform already has a transcript, prefer it and align** Whisper's word
  timings to it with `difflib` — jevmeter's approach. Platform transcripts have correct
  proper nouns; Whisper has correct timings. Take both.
- Sentence segmentation: punctuation from Whisper, plus a forced break on silence
  > 700ms and on speaker change. Long sentences (>40 words) split at the largest internal
  pause — an 80-word "sentence" is a useless addressing unit.
- Emit `transcript.json`: `[{id: "L042", text, t0, t1, speaker, words: [...]}]`.
- IDs are `L%03d`, zero-padded, assigned once and never renumbered.

## Acceptance criteria

- [ ] `jevcut transcribe <input>` writes `transcript.json` with word timings.
- [ ] Sentence `t0`/`t1` are within 100ms of the first/last word.
- [ ] A 60-min video yields 400–800 sentences (sanity band; outside it, segmentation is
      wrong).
- [ ] Re-running on the same input is byte-identical (fixed seed, cached ASR output).
- [ ] Rendering helper produces the `L042| text` form the model sees.

## Gotchas

- Whisper hallucinates on silence and music — drop segments with no words or with
  `no_speech_prob` above threshold. Hallucinated filler in state is a context-rot tax and
  a source of fake anchors.
- Don't strip disfluencies. "I mean, the thing is—" is real evidence for
  `starts_mid_thought` in Pass E. Clean transcripts hide the defect we're trying to catch.
- Keep the raw ASR output next to the normalized form; 010's triage needs to separate ASR
  errors from model errors.

## Implementation note

Whisper backend written but unexercised -- no ASR installed here, so it is covered only by the import guard. The `--from-json` path and segmentation are fully tested. `sanity_check()` implements the 400-800 sentences/hour band.
