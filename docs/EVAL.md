# Evaluation

Every claim in the README is a hypothesis. This is how each one gets tested. The eval
harness is not the last milestone — it is [issue 011](../issues/011-eval-set.md), built
before any threshold is tuned, because thresholds tuned by eyeballing are how these
projects quietly fail.

> Treat cookbook thresholds and demo results as examples to evaluate, not universal rules.
> Typed output guarantees the interface, not truth.

## The set

**40 videos, 5 genres** × 8 each: podcast/interview, conference talk, gameplay/reaction,
tutorial, panel or debate. 20–90 min each. Mixed audio quality on purpose — ASR error is
part of the system under test, not an excuse.

**Labels, per video:**
- 5–10 human-chosen clips, each with a start and stop timestamp a human would ship.
- For each, the *acceptable* start range (usually a few seconds wide — there's rarely one
  correct frame).
- Rejected candidates: stretches that look interesting by energy but don't stand alone.
  These are the hard negatives and the most valuable labels in the set.

Two labelers per video, disagreements reconciled. **Record inter-labeler boundary
disagreement** — it's the noise floor. If humans disagree by 1.5s median, a 1.5s median
error is a solved problem and chasing lower is chasing noise.

## Metrics

### Boundary quality — the primary metric

| Metric | Definition | Target |
| --- | --- | --- |
| `start_err_median` | median \|predicted − human start\| over matched clips | ≤ labeler noise floor |
| `start_err_p90` | 90th percentile of the same | < 4s |
| `end_err_median` / `_p90` | same for stop | < 5s p90 |
| `in_range_rate` | % of starts inside the acceptable range | > 80% |

Match a predicted clip to a labeled one when their spans overlap by >50% (IoU). Unmatched
predictions are false positives; unmatched labels are misses.

### Standalone quality — what makes a clip shippable

| Metric | How | Target |
| --- | --- | --- |
| `mid_thought_rate` | blind human rating of shipped clips | **< 5%** |
| `dangling_ref_rate` | same | **< 8%** |
| `payoff_rate` | "did the point land?" | > 85% |

Rated **blind**: raters see only the clip, in a shuffled pool mixing jevcut and baseline
output, with no idea which produced which.

### Selection quality

`precision@5` against human-chosen clips, `recall@10`, and `hard_negative_rate` — how
often a labeled rejected stretch gets shipped. The last one is the honest measure of the
standalone gate.

### Cost and latency

Tokens/video-hour, requests/video-hour, $/video-hour, wall-clock to first clip and to
completion. Logged per run, always, not just during eval.

### Live-specific

| Metric | Definition | Target |
| --- | --- | --- |
| `detection_lag` | trigger time − true moment start | measure, don't target |
| `retro_recovery` | fraction of `detection_lag` recovered by the retro-start Choice | **> 80%** |
| `false_trigger_rate` | triggers per hour that produce no shippable clip | < 3/hr |
| `buffer_underrun` | % of retro-starts returning `before_this_buffer` | < 10% (else lengthen buffer) |

`retro_recovery` is the number that justifies the ring buffer. If it's low, live mode is
just a worse VOD mode and should be cut.

## Baselines (issue 013)

All three run on the same 40 videos, same ASR, same renderer. Only the selection and
boundary logic differ.

1. **Dense rolling average** (jevmeter-shaped): score every sentence, take the highest
   10–15s rolling window.
2. **Fixed windows** (jev-skip-shaped): 30s windows snapped to sentence ends, one Choice
   each, take top N.
3. **Naive**: top-scoring sentence ±15s. The dumbest thing that works — and the bar that
   matters most, because if jevcut can't beat "peak sentence plus padding", the cascade is
   ceremony.

**Ship criterion:** jevcut must beat all three on `start_err_p90` and `mid_thought_rate`
simultaneously. Winning on selection while losing on boundaries means the thesis was wrong
and the design should change.

## Failure triage

When a clip is bad, attribute it before fixing it — the classes have different owners:

| Class | Tell | Owner |
| --- | --- | --- |
| ASR error | transcript doesn't match audio | ingest |
| Missing candidate | no cut point near the right boundary | cut-point extraction |
| Model error | right candidates offered, wrong one picked | question wording |
| Composition error | good judgments, bad clip | ranking code |
| Service error | 429/5xx | client layer |

**Model errors get logged with the exact state, questions, options and answers** — that
log is what makes question wording improvable rather than guesswork
([issue 010](../issues/010-trace-logging.md)). "Missing candidate" is the sneaky one: it
looks like a model error and isn't. The model cannot choose an option it was never given.

## Cadence

Run the full eval on every question-wording change and every model version bump. Keep a
results table in `eval/results/` with model ID, thresholds and git SHA per row. When
`jev-latest` moves, re-run before believing any previously tuned threshold.
