# 006 — Pass D: boundary refinement

| | |
| --- | --- |
| **Milestone** | M1 VOD pipeline |
| **Depends on** | 003, 005 |
| **Blocks** | 007 |
| **Size** | L |

## Why

**The core of the project.** Everything else is available in some form in prior art; this
isn't. Picking the exact cut point instead of snapping to a window is the entire quality
thesis, and 013 exists to test it.

## Build

- **Read the scan header before spending anything.** `read_scan` returns coverage
  alongside the anchors ([005](005-pass-c-coarse-scan.md)). A scan that missed a third of
  its windows is a floor, not a result, and refining it produces a confident-looking clip
  list for a video nobody finished looking at. Decide the policy here and state it: refuse
  under some coverage, or proceed and mark every clip. Do not ignore the field.
- Region: anchor ±90s of transcript, cut points inlined as `«C07»`
  (helper from 003).
- One request per anchor, four questions in parallel:
  `start_cut`, `end_cut`, `needs_more_setup`, `cold_open_ok`
  (specs in [QUESTIONS.md](../docs/QUESTIONS.md#pass-d--boundary-refinement)).
- **Per-`kind` instruction variants** — the `kind` from Pass C selects the wording:
  - `joke` → start includes the setup, end is the punchline's last word
  - `story` → start at the situation being established, end at the outcome
  - `hot_take` → start at the question or claim that provoked it
  - `explanation` → start at the premise, end when the idea is complete
  Keep variants in one table so 014 can A/B them.
- Handle the escapes: `before_this_region` / `after_this_region` ⇒ widen the region by 60s
  and re-ask, **once**. Then accept with a flag on the clip.
- Use `cold_open_ok` and `needs_more_setup` as code-side branches only — they're
  speculative, asked before we know which start wins.
- Emit candidate clips with `t0`, `t1`, both Choice confidences, and the escape flags.

## Acceptance criteria

- [ ] One request per anchor, four questions, ≤40 cut options per Choice.
- [ ] `start_err_median` on a 10-clip hand-labeled sample beats "anchor − 15s" before
      moving on. If it doesn't, stop and rethink before building 007.
- [ ] Escape handling re-asks at most once per anchor.
- [ ] Per-`kind` variants selectable by config so 014 can sweep them.

## Gotchas

- "LATEST mark that still includes what's needed" is a **tie-break rule**, and it's there
  because without one the model drifts earlier and earlier, producing bloated clips. Keep
  the capitalized wording; it's literal on purpose.
- Jev cannot compare timestamps or reason about durations. Never put "make it under 60
  seconds" in the instruction. Duration is 008's job, in code.
- Low Choice confidence here usually means several adjacent cut points are all acceptable —
  which is harmless. Don't gate on it without checking that first. Several acceptable
  alternatives spread probability just like genuine confusion does.

## Note: handling a near-tied `kind`

Observed live on 2026-09-20. A clip recounting an outage *and* using it to explain
thundering herd returned:

```
explanation  0.470   <- winner
story        0.440
joke         0.060
hot_take     0.030
confidence   0.33
```

Low confidence, but **not confusion** — both labels are correct, and the nonsense options
got ~0. This is the documented case where several acceptable alternatives spread
probability, which is not a reason to reject anything. A confidence gate on `kind` would
have thrown away a good clip for being two good things at once.

**Rule to implement:** when the top two `kind` probabilities are within ~0.1, prefer
**`story`** boundary wording. A story's boundaries (start where the situation is
established, end at the outcome) *contain* an explanation's, so the wider rule is the
safe one — the failure mode of guessing wrong is a clip missing its setup, which is
exactly what Pass E's `starts_mid_thought` gate is built to catch.

Diagnose a spread by looking at **which** options share the probability, never at the
confidence number alone: two fair readings of the same text is case 2, unrelated
categories lighting up is case 1 (the model did not understand) and is a real problem.
Issue 014 should sweep the tie threshold.
