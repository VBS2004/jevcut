# 011 — Eval set and labeling protocol

| | |
| --- | --- |
| **Milestone** | M2 Measure |
| **Depends on** | 009 |
| **Blocks** | 012, 003's recall check |
| **Size** | XL (humans are the bottleneck) |

## Why

Without labels, "better boundaries" is an opinion. This is also the only issue that
produces the **noise floor** — how much two humans disagree about where a clip starts. If
that's 1.5s, then 1.5s median error is done, and chasing 0.5s is chasing noise.

## Build

- **40 videos, 5 genres × 8:** podcast/interview, conference talk, gameplay/reaction,
  tutorial, panel/debate. 20–90 min. Mixed audio quality deliberately — ASR error is part
  of the system under test.
- Per video, two labelers independently mark **5–10 shippable clips**: start, stop, and an
  *acceptable start range* (there is rarely one correct frame).
- Label **hard negatives**: stretches that sound energetic or emphatic but don't stand
  alone. These are the most valuable labels in the set and the only way to measure whether
  Pass E does anything.
- Reconcile disagreements in a third pass; **keep the pre-reconciliation deltas** — that's
  the noise floor.
- Store as `eval/labels/<video_id>.json`. Videos by URL + checksum, not committed.
- Rights: public/CC content, or content the team owns. No redistribution of source media.

## Acceptance criteria

- [ ] 40 videos labeled by 2 people each, reconciled.
- [ ] Inter-labeler boundary disagreement published (median, p90) per genre.
- [ ] ≥100 hard negatives across the set.
- [ ] A 5-video subset committed as a fast CI fixture with a cached run (004).

## Gotchas

- Don't let labelers see jevcut's output first. Anchoring will quietly make the eval
  agree with the system.
- Genre matters more than video count. 8 podcasts tell you less than 3 podcasts + 3 talks
  + 2 gameplay, because boundary rules differ by genre — which is exactly why Pass C asks
  `kind`.
- Budget real time here. Labeling 40 long videos twice is the single largest cost in the
  project, and doing it badly wastes every measurement downstream.
