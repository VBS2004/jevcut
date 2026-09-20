# 012 — Metrics harness

| | |
| --- | --- |
| **Milestone** | M2 Measure |
| **Depends on** | 010, 011 |
| **Blocks** | 013, 014 |
| **Size** | M |

## Why

Turns labels into a table. Every metric in [EVAL.md](../docs/EVAL.md) computed with one
command, so a question-wording change is answered with a number in minutes rather than a
vibe in an argument.

## Build

- `jevcut eval --set eval/labels --run runs/<id>` → a results row.
- Matching: predicted ↔ labeled by >50% IoU. Unmatched predictions = false positives,
  unmatched labels = misses.
- Metrics: `start_err_median/p90`, `end_err_median/p90`, `in_range_rate`, `precision@5`,
  `recall@10`, `hard_negative_rate`, plus tokens/requests/$/latency per video-hour.
- **Blind rating tool** for the human metrics (`mid_thought_rate`, `dangling_ref_rate`,
  `payoff_rate`): shuffles clips from all systems into one pool, hides provenance, records
  ratings. Without the shuffle these numbers are worthless.
- Append every run to `eval/results/results.csv` with model ID, thresholds, git SHA.
- Per-genre breakdown, always. An aggregate number hides that the system works on podcasts
  and fails on gameplay.

## Acceptance criteria

- [ ] One command produces the full metrics row.
- [ ] Metrics broken down by genre and by `kind`.
- [ ] Blind rating tool genuinely blind (provenance not in the UI or the filenames).
- [ ] Runs against cached responses with no API calls.
- [ ] The results row records the model ID that answered, from the response field.

## Gotchas

- Report the labeler noise floor next to `start_err_median` in every table. A number
  without its floor invites chasing noise.
- Keep false positives and misses separate. A system that ships fewer, better clips looks
  worse on recall and is the one we want.
