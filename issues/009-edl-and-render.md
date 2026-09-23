# 009 — EDL output and ffmpeg render

| | |
| --- | --- |
| **Milestone** | M1 VOD pipeline |
| **Depends on** | 008 |
| **Blocks** | 011 |
| **Size** | M |
| **Status** | **Built** — `src/jevcut/edl.py`, `src/jevcut/boundaries.py`, `src/jevcut/captions.py`, `src/jevcut/sheet.py`, `tests/test_edl.py`, `tests/test_captions.py`, `tests/test_cli.py`, `tests/test_sheet.py`. Runs as `jevcut run`, or `jevcut clip` on an existing transcript; every run writes `index.html` beside the clips. The 9:16 crop is a centre crop to 1080x1920; following the speaker's face is a separate, later job. Captions are burned from the word timings as an ASS file, a few words a line with the spoken word highlighted. |

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
- **Align the rendered edges into the measured silence — never pad by a constant.** A hard
  cut on the first phoneme sounds clipped even when the boundary is correct, but a flat
  150–250ms pre-roll (what this issue used to specify) is the wrong fix: the gap before a
  word varies with how the speaker breathes, so one constant clips plosives on a tight entry
  and leaves dead air on a slow one. autoclip states the reasoning and ships the fix — see
  [PRIOR-ART](../docs/PRIOR-ART.md#artbyjaziautoclip).

  The chosen cut point already carries its own gap (`gap_ms` on `CutPoint`, see
  [003](003-cut-point-extraction.md)), so no separate silence lookup is needed — derive
  `silence.start`/`silence.end` from it. Anchor each offset to the adjacent **word**, then
  clamp it inside the gap:

  ```
  LEAD_S   = 0.12   # start this far before the first word — catches the breath, no dead beat
  TAIL_S   = 0.28   # hold this long after the last word — an abrupt tail reads as a mistake
  MARGIN_S = 0.04   # never cut this close to a silence edge; detection has hysteresis
  RADIUS_S = 0.75   # no silence found within this of the boundary → fall back to a constant

  start = max(silence.start + MARGIN_S, min(silence.end   - LEAD_S, t0))
  end   = min(silence.end   - MARGIN_S, max(silence.start + TAIL_S, t1))
  ```

  Head and tail offsets **differ on purpose**: tight in, hold out. Fallback when no silence
  is within `RADIUS_S`: 0.25s lead, 0.35s tail.

- Alignment can only ever widen a clip, so **re-check any duration ceiling after aligning**,
  not before.

- All of the above is render-side and must **not** be folded back into the measured
  boundary — 012 scores `t0`/`t1`, not the rendered edges. Keep both in the EDL.
