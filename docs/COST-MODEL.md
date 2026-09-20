# Cost model

Numbers below are **estimates to be validated by [issue 013](../issues/013-baseline-comparison.md).**
Nothing here is measured yet. Treat every figure as a hypothesis with a test attached.

## Measured, 2026-09-20

First live calls through OpenRouter (`typesafe/jev-1.13`), which bills at the same
$0.042/Mtok and **reports `usage.cost` per response** — jevcut records that number rather
than recomputing it.

| Observation | Content chars | Reported input tokens |
| --- | --- | --- |
| 1 state + 1 Noul | ~94 | 275 |
| 1 state + 4 questions (Pass E shape) | ~1,532 | 696 |

**There is a fixed ~250-token cost per request**, independent of content — the API's own
scaffolding around the questions. Two consequences:

1. A naive `chars/4` estimate underestimates a small request by roughly 10x, which would
   make the budget guard useless precisely where it matters. `client.py` now models
   `250 + chars/3.5`, fitted to the two points above, and issue 018 refines it.
2. **It strengthens the cascade argument.** Per-request overhead is a per-*request* tax,
   so 600 dense requests carry ~150k tokens of pure overhead where 32 carry ~8k. Add that
   to the table below when 013 measures it for real.

A full Pass E call on a real clip cost **$0.000029**. Latency was under 2s.

## Pricing facts

From [Models](https://docs.typesafe.ai/models.md), `jev-1.13.0`:

- **$0.042 / Mtok input. Output tokens are free.** Only what you send costs money.
  (OpenRouter bills the same rate and returns `usage.cost`; prefer the reported number.)
- **Context:** 64k per request total (state + all questions); 32k for state + the single
  longest question.
- **Rate limits:** 250,000 tokens/sec, **1,200 requests/min** — and the docs warn these
  are "adjusting dynamically" under load.
- Jev ingests `state` **once** and evaluates every question against it in parallel.

That last line is the whole optimization. Questions are nearly free once the state is
paid for; **requests** are what you're actually rationing.

## Worked estimate — 1 hour of talk video

Assume ~9,000 words ≈ 12k tokens of transcript, ~600 sentences.

### Baseline A — dense per-sentence scoring (jevmeter-shaped)

600 sentences × (≈300 tok local context + ≈400 tok of 6 questions) ≈ **420k tokens**,
**≈600 requests**. → **$0.018** per video-hour.

### Baseline B — fixed 30s windows (jev-skip-shaped)

120 windows × ≈600 tok ≈ **72k tokens**, **120 requests**. → **$0.003**.
Cheap, but the boundary is the window edge — which is the thing jevcut exists to fix.

### jevcut cascade

| Pass | Requests | State each | Questions each | Tokens |
| --- | --- | --- | --- | --- |
| C scan | 8 | ~1.6k | ~1.5k (3 q, one with 80 options) | ~25k |
| D refine | 12 | ~0.9k | ~0.6k | ~18k |
| E verify | 12 | ~0.3k | ~0.5k | ~10k |
| **Total** | **~32** | | | **~53k** |

→ **≈$0.0022** per video-hour.

### Comparison

| | tokens | requests | $/hr video |
| --- | --- | --- | --- |
| Dense per-sentence | 420k | 600 | $0.018 |
| Fixed windows | 72k | 120 | $0.003 |
| **jevcut cascade** | **53k** | **32** | **$0.0022** |

**≈8× fewer tokens and ≈19× fewer requests than dense.** Sanity check against reality:
jev-skip reports 50 segments / 25.3k tokens / **$0.0011** / 1546ms on a comparable
workload, which puts the cascade's 53k for a deeper analysis in the right order of
magnitude.

## Read this before quoting the cost win

**The dollar difference is $0.016 per video-hour.** Nobody makes a decision on that. Do
not sell this project on cost.

The number that matters is **requests**. At 1,200 req/min:

- Dense scoring: 600 requests per video-hour ⇒ ~2 video-hours/min of backfill throughput.
- Cascade: 32 requests ⇒ ~37 video-hours/min. **Backfill stops being a scheduling problem.**
- Live: ~900 req/hr per stream (one tick per 4s) = 15 req/min ⇒ **~70 concurrent streams**
  before the account limit binds. Dense-per-sentence live isn't possible at all.

Latency follows the same shape: 32 sequential-ish requests is a pipeline that finishes
while the user waits; 600 is a batch job.

## Cost controls to build in

1. **Budget guard** — hard token ceiling per video, enforced in code before each pass
   ([issue 018](../issues/018-cost-telemetry.md)). Fail loud, never silently truncate.
2. **Pass C gate is the lever.** Every anchor that survives costs 2 more requests. Tune
   `contains_moment` and the anchor-confidence threshold to the yield you want, and
   measure the precision cost of each setting.
3. **Response cache keyed by (state hash, question hash, model id).** Re-running the
   pipeline after a weight change must cost $0 — the judgments are unchanged, only policy
   moved. This is a correctness property of the design, not just an optimization.
4. **Pin the model ID, not the alias.** `jev-latest` moves; thresholds tuned against a
   version have to be re-validated when it does. Log the response's `model` field.
5. **Don't pad state.** Accuracy falls as state fills with irrelevant detail, so the
   cheapest request and the most accurate request are the same request.
