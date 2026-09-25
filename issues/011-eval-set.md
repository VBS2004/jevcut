# 011 — Eval set and labeling protocol

| | |
| --- | --- |
| **Milestone** | M2 Measure |
| **Depends on** | 009 |
| **Blocks** | 012, 003's recall check |
| **Size** | XL (humans are the bottleneck) |
| **Status** | **38 videos, 13 genres** (2026-09-25): the 8-video pilot plus set 2 (`eval/sets/set2.txt`: 30 videos under 30 minutes from Caleb Writes Code, Olga Loiek, Fireship, Cleo Abram, Cult of Mush and Trevor Noah). Labeled twice, blind, under rubric v2 ([eval/RUBRIC.md](../eval/RUBRIC.md), brief [eval/LABELING.md](../eval/LABELING.md)): `eval/labels-v2/` (A, 188 clips) and `eval/labels-v2-b/` (B, 195). They share 83-86% of moments; starts 0.0s apart at the median and 2.3s at p90, ends 6.5s at p90. v1 (`eval/labels/`, `eval/labels-b/`) covers the pilot only. All labelers are the same model, so the floor is a lower bound; no human review yet. |

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
- **Chat-triggered clips are a free selection label, and only that.** Every `!clip` in a
  live chat, and every Twitch Clip, is a human saying "this moment is worth clipping",
  timestamped, at scale, on public content. It is the closest thing this task has to a
  SponsorBlock, and it speaks to the [RESEARCH.md](../RESEARCH.md) failure mode that costs
  the most if true — that selection, not boundaries, is the hard part. Three limits, each
  disqualifying it for boundary work:
  - it is a **reaction**, so it lags the moment by human response time — which is exactly
    why StreamClipper and Streamsnip both subtract a flat 30s (see
    [017](017-retro-start-and-tail.md));
  - it marks **selection only**: no start, no end, no acceptable range;
  - it skews to chat-active streams and meme-able moments, not a well-made point.

  Usable for "do humans agree about *which* moments"; never for "where does it start".
  Keep it out of the boundary labels entirely.
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
