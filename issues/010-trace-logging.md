# 010 — Trace logging and failure triage

| | |
| --- | --- |
| **Milestone** | M1 VOD pipeline |
| **Depends on** | 001, 009 |
| **Blocks** | 012 |
| **Size** | S |

## Why

When a clip is bad, the question is *which layer failed*. The docs are direct about this:
inspect the exact state, questions, candidates, answers, composition and outcome, and
separate missing evidence from model errors from code errors from service failures.

Without this, every bad clip becomes an argument about prompt wording — including the ones
where the right cut point was never offered as an option.

## Build

- `runs/<run_id>/trace.jsonl` — one record per Jev call: pass, state (or its hash + a
  stored copy), full question dict, full response with probabilities and confidence,
  latency, usage, **the model ID that answered**.
- `jevcut explain <clip_id>` — prints the full chain for one clip: window → anchor →
  candidate cut points offered → chosen cuts → gate answers → composite → verdict.
- **Candidate coverage check**, run automatically against eval labels: for each labeled
  boundary, was a cut point within **2.0s** actually in the option list? Classify as
  `missing_candidate` before anything is called a model error. The tolerance matches
  [003](003-cut-point-extraction.md), which measured where it is reachable — keep the two
  in step, and count "no transcript there" separately as 003 requires.
- **Adjacency rate**, from the distributions already in the trace: how often are the top
  two options *neighbouring IDs* with a close margin? That is the signature of a pick that
  landed one line off because the labels look alike, not because the model was wrong about
  the content — and it is a different repair from either a missing candidate or a bad
  question. Feeds the label-scheme A/B in [014](014-threshold-tuning.md). Costs nothing:
  every Choice response already carries the full distribution.
- Triage classifier over traces: `asr_error | missing_candidate | model_error |
  composition_error | service_error`.

## Acceptance criteria

- [ ] Every Jev call is traced with enough detail to reconstruct the request exactly.
- [ ] `jevcut explain` renders the full chain for any clip in a run.
- [ ] Coverage check runs as part of eval and reports a `missing_candidate` rate.
- [ ] Traces replay through 004's cache without network access.

## Gotchas

- Traces contain full transcripts. Treat `runs/` as containing user content — gitignored,
  and scrubbed before sharing.
- `missing_candidate` is the failure mode that masquerades as every other one. Check it
  first, always.
