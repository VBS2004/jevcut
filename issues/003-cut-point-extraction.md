# 003 — Cut-point extraction

| | |
| --- | --- |
| **Milestone** | M0 Foundations |
| **Depends on** | 002 |
| **Blocks** | 006, 017 |
| **Status** | **Done** (M0 branch) — `src/jevcut/cuts.py`, `src/jevcut/render.py`, `tests/test_cuts.py`, `tests/test_render.py` |
| **Size** | M |

## Why

**This is the issue the project's quality claim rests on.** Jev can only choose a boundary
we hand it as an option — "the model cannot choose an omitted value". If the right cut
isn't in the candidate list, no amount of question tuning recovers it, and the failure
looks exactly like a model error in the logs.

## Build

`src/jevcut/cuts.py` — enumerate candidate cut points from the transcript:

| Kind | Rule |
| --- | --- |
| `sentence_end` | every sentence boundary |
| `pause` | silence gap ≥ 350ms between words |
| `speaker_change` | diarization turn boundary |
| `shot` | PySceneDetect content-detector cut (optional; off for audio-only) |

- Merge candidates within 200ms of each other, keeping the strongest kind
  (`shot` > `speaker_change` > `sentence_end` > `pause`).
- A cut point is a **gap, not an instant.** Keep `t` at the middle of the gap for merging,
  thinning and spacing — those want one representative instant — and resolve the real
  timestamp from the role it ends up playing:

  ```python
  t_start = t + gap_ms/2000   # where the next word begins   -> this cut used as a clip START
  t_end   = t - gap_ms/2000   # where the previous word ended -> used as a clip END
  ```

  **Why, and it is not about how it sounds:** `t` at the midpoint makes a *correct* choice
  measure as wrong. A human labels a start just before the first word, so on a 2s pause a
  perfect pick scores 1.0s early. That bias is systematic (always early for a start),
  proportional to gap length — and clip boundaries sit at the *longest* gaps, because that
  is what speakers do between topics. It lands directly on `start_err_p90`, the M2 ship
  criterion, and on `coverage()` below. Baseline 4 in
  [013](013-baseline-comparison.md) is word-anchored, so jevcut would lose its own
  comparison on a timestamp convention rather than on judgment.

  Making a clip *sound* right — not cutting on the first phoneme — is a render concern and
  lives in [009](009-edl-and-render.md), which also consumes `gap_ms` for its lead/tail
  clamp. Jev's answer is unaffected either way: it still picks `C07`.
- ID as `C%02d` within each region, assigned at region-construction time.
- Render helper: transcript text with `«C07»` markers inlined between sentences, the exact
  form Pass D's state uses.
- Target density: **one candidate every 2–4s**. Denser than that bloats the Choice option
  list for no gain; sparser and the right boundary starts falling between candidates.

## Acceptance criteria

- [ ] `cuts.extract(transcript)` returns candidates at the target density.
- [ ] **Recall check against the eval set (011): for ≥95% of human-labeled clip starts,
      a candidate exists within 1.0s.** This is the gating metric for this issue.
      **Measured early and it may not be reachable:** against 48 human-placed boundaries on
      real speech, caption-cue starts at 25/min — near this issue's target density — hit
      **81% within 1.0s, 94% within 2.0s**
      ([experiment](../eval/experiments/texttiling_vs_labels.py)). Those are not jevcut's
      candidates (Whisper word timings should place them better than caption chunking) but
      they are the right order of magnitude. Expect to either beat 81% by a clear margin or
      move this bar to 2.0s with the reason recorded — do not quietly relax it.
      `coverage()` must compare against `t_start`/`t_end`, not `t` — measuring the midpoint
      against word-anchored human labels spends up to half a gap of the 1.0s tolerance on
      nothing.
- [ ] A ±90s region yields 30–60 candidates — well under the 255-option Choice limit.
- [ ] Markers render without breaking sentence IDs.

## Gotchas

- The recall check can only run once 011 exists. Until then, hand-check 5 clips. Do not
  skip it — a silent recall hole is the hardest bug in this system to diagnose.
- Music beds and laughter destroy pause detection. Fall back to sentence ends when the
  pause-candidate rate collapses, and log when that happens.
- **`sentence_end` lives or dies on punctuation.** In the transcripts used for the
  experiment above, 5 of 6 sampled videos had *zero* cues ending in terminal punctuation —
  auto-generated captions carry none. Whisper does punctuate, so jevcut is not exposed the
  same way, but the primary candidate kind is one ASR setting away from vanishing. Count
  sentence candidates per minute and fail loudly if the rate collapses, the same way the
  pause fallback does.
- **Do not try to derive pauses from caption cue timings.** The same transcripts are ~99%
  contiguous (`564/583`, `682/683`, `358/358`) — each cue starts exactly where the last
  ended, so inter-cue gaps are ~0 and a pause detector reading them finds nothing. Pauses
  need word-level timings or real silence detection.

## Implementation note

`cuts.py` currently sets `t = s.t1 + gap/2` and stores `gap_ms` alongside it, so the gap
edges are already recoverable and **no re-extraction is needed** — the change is adding the
two derived values on `CutPoint` and pointing `coverage()`, Pass D's timestamp resolution
and 009's render at them. Small and mechanical; the enumeration itself is untouched.

The 95% recall criterion is **not met yet** -- it needs the labeled set from 011. `coverage()` is implemented and ready to run against it. Shot detection is written but untested (scenedetect not installed).
