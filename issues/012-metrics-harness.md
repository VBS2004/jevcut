# 012 — Metrics harness

| | |
| --- | --- |
| **Milestone** | M2 Measure |
| **Depends on** | 010, 011 |
| **Blocks** | 013, 014 |
| **Size** | M |
| **Status** | **Partly built** — `src/jevcut/evaluate.py`, `tests/test_evaluate.py`, `jevcut eval`. IoU>0.5 one-to-one matching, precision, recall with the chance baseline at the same density, in-range rate, hard-negative rate, start/end error, per-genre breakdown, a row appended to `eval/results/results.csv` with the git SHA. Not built: the blind rating tool, p90s, `Pk`/`WindowDiff`, cost per video-hour, the labeler noise floor (needs two labelers), per-`kind` breakdown, model ID in the row. |

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
- **Rating protocol, taken from Valand et al.** ([PRIOR-ART](../docs/PRIOR-ART.md#research-literature))
  rather than invented, since they ran it on the same question and published the design:
  - **Pairwise A/B**, not absolute scoring in isolation. Two clips of the *same moment* cut
    by different systems, side by side.
  - **1 (very poor) to 10 (broadcast ready)**, plus an optional free-text comment. The
    anchors matter: "broadcast ready" is a concrete standard, "good" is not.
  - **Every rater sees the same clips in the same pairings.** Randomising per rater buys
    nothing here and destroys direct comparability.
  - **Keep the session to 10–12 minutes** — roughly 5 moments, 10 clips. Beyond that,
    attention decays and so does the data.
  - **Record rater class**, specifically video-editing experience. In their study editors
    scored the baseline *lower* (5.47 vs 5.89) **and** separated the systems further:
    experts discriminate harder, so the class mix changes the headline number. Report per
    class, like the genre breakdown above.
  - **Attention check: drop raters who give everything the maximum.** They dropped 3 of 64
    that way. Cheap, and it catches the failure mode that matters.
  - **Expect about +1 point.** Their boundary refinement moved 5.89 → 6.84 over static
    clipping, and trimming took it to 7.40. If jevcut shows +4, suspect the harness before
    believing it.
- Append every run to `eval/results/results.csv` with model ID, thresholds, git SHA.
- Per-genre breakdown, always. An aggregate number hides that the system works on podcasts
  and fails on gameplay.
- **Report recall against chance at the same prediction density.** A system that emits
  enough boundaries hits every label by luck, and recall alone cannot tell that apart from
  skill. Scatter the same *number* of predictions at random over the same video, average a
  few hundred trials, report both. This is not theoretical: it is what turned an apparent
  60% for TextTiling into a null result
  ([PRIOR-ART](../docs/PRIOR-ART.md#classical-methods)), and the
  [experiment script](../eval/experiments/texttiling_vs_labels.py) already implements it.
- **Also report `Pk` and `WindowDiff`.** Topic segmentation has spent thirty years on
  exactly this measurement problem and these are its standard answers — both penalise
  over-segmentation, which `start_err_p90` does not. jevcut's metric may well be the better
  fit, since it cares about one exact cut while they score a whole partition, but that
  should be a stated choice. Reporting both costs nothing and is legible to anyone who
  knows the field.

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
