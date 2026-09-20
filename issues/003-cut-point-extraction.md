# 003 — Cut-point extraction

| | |
| --- | --- |
| **Milestone** | M0 Foundations |
| **Depends on** | 002 |
| **Blocks** | 006, 017 |
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
- Place the cut timestamp **in the middle of the silence**, not at the last word's end —
  clips that start on a breath sound wrong.
- ID as `C%02d` within each region, assigned at region-construction time.
- Render helper: transcript text with `«C07»` markers inlined between sentences, the exact
  form Pass D's state uses.
- Target density: **one candidate every 2–4s**. Denser than that bloats the Choice option
  list for no gain; sparser and the right boundary starts falling between candidates.

## Acceptance criteria

- [ ] `cuts.extract(transcript)` returns candidates at the target density.
- [ ] **Recall check against the eval set (011): for ≥95% of human-labeled clip starts,
      a candidate exists within 1.0s.** This is the gating metric for this issue.
- [ ] A ±90s region yields 30–60 candidates — well under the 255-option Choice limit.
- [ ] Markers render without breaking sentence IDs.

## Gotchas

- The recall check can only run once 011 exists. Until then, hand-check 5 clips. Do not
  skip it — a silent recall hole is the hardest bug in this system to diagnose.
- Music beds and laughter destroy pause detection. Fall back to sentence ends when the
  pause-candidate rate collapses, and log when that happens.
