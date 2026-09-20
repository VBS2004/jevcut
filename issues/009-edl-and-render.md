# 009 — EDL output and ffmpeg render

| | |
| --- | --- |
| **Milestone** | M1 VOD pipeline |
| **Depends on** | 008 |
| **Blocks** | 011 |
| **Size** | M |

## Why

Closes the loop: judgments become files a human can watch. The eval in M2 needs real clips
to rate, and an editable EDL is what makes a human's fix visible as data.

## Build

- `edl.json` — one entry per clip: `t0`, `t1`, anchor, kind, all scores, all gate
  probabilities, composite, rank. Human-editable; a re-render reads it back without
  touching the API. (jevmeter's format, same reasoning.)
- `ffmpeg` render: accurate seek (`-ss` before `-i` for speed, re-encode for frame
  accuracy), optional 9:16 crop, optional burned word-level captions from the word
  timings in 002.
- `jevcut run <input>` = transcribe → cuts → C → D → E → F → EDL → render.
- Contact sheet / index HTML listing clips with scores, so a rater can work through them.

## Acceptance criteria

- [ ] `jevcut run` on a 60-min file produces ranked clips end to end.
- [ ] Clip boundaries land within 100ms of the EDL timestamps (verify with ffprobe).
- [ ] Hand-editing an EDL timestamp and re-rendering costs zero API calls.
- [ ] `--dry-run` writes the EDL without rendering.

## Gotchas

- Fast seek with `-ss` before `-i` lands on the nearest keyframe. For a system whose entire
  claim is boundary precision, that is not acceptable — re-encode, or seek accurately and
  eat the cost.
- Add 150–250ms of pre-roll before `t0` when rendering. The cut point sits mid-silence;
  a hard cut on the first phoneme sounds clipped even when the boundary is correct. This
  is a render-side nicety and must **not** be folded back into the measured boundary.
