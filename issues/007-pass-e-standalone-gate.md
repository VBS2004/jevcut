# 007 — Pass E: standalone gate

| | |
| --- | --- |
| **Milestone** | M1 VOD pipeline |
| **Depends on** | 006 |
| **Blocks** | 008 |
| **Size** | M |
| **Status** | **Built, reshaped** — `src/jevcut/gate.py`, `src/jevcut/questions.py`, `tests/test_gate.py`. Seven questions, repair loop with widen/tighten; differs from the spec below in the ways recorded in docs/QUESTIONS.md. |

## Why

The differentiator against every commercial auto-clipper. Their three standing complaints —
starts mid-sentence, opens on a pronoun with no referent, ends before the payoff — become
three Nouls with measured rates.

This must be a **second request**: its state is the cut clip text, which doesn't exist
until 006 answers. That's the documented reason to split.

## Build

- State: **the clip text only.** No title, no speaker names, no surrounding transcript.
  The model should be in the viewer's position, and anything extra is a distractor.
- Six questions in one request:
  `starts_mid_thought`, `ends_mid_thought`, `dangling_reference`, `standalone` (Nouls),
  `hook`, `payoff` (Scores) — see
  [QUESTIONS.md](../docs/QUESTIONS.md#pass-e--standalone-gate).
- Emit gate results and scores onto each candidate clip. **No decisions here** — 008 owns
  policy, so the raw judgments stay reusable when the policy changes.

## Acceptance criteria

- [ ] One request per candidate clip, six questions.
- [ ] Hand-built adversarial fixtures behave: a clip starting on "—and that's why he did
      it" scores `starts_mid_thought` high and `dangling_reference` high; a clean
      self-contained clip scores both low.
- [ ] `hook` and `payoff` return `probabilities` and `confidence`, both persisted. A score
      of 1.0 can mean "all probability on level 1" or "split between 0 and 2" — the
      distribution is the only way to tell those apart.
- [ ] Scores are comparable across clips (identical levels, one clip per state).

## Gotchas

- **Never interpolate a magnitude between Score levels.** Use the expectation for
  threshold checks only; the levels are not numerically calibrated.
- `standalone` overlapping the three specific Nouls is deliberate. The specific ones name
  a defect code can act on; the broad one feeds ranking. All four can be low at once —
  each Noul is absolute, unlike options in a Choice.
- Write levels as concrete situations. Numbers-only levels collapse to confidence ~0.5;
  the Score docs demonstrate it.
