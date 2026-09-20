# jevcut

Auto-clipping that picks **cut points**, not windows.

Given a full video (or a live stream), jevcut finds the moments worth clipping and
decides exactly where each clip should **start** and **stop** — using
[Jev](https://docs.typesafe.ai/models.md), TypeSafe's System One model, as a judge over
transcript text, with all arithmetic, timing and rendering in code.

Status: **M0 done** (issues 001–003) — ingest, cut-point extraction and the Jev client
wrapper are implemented and tested. The passes that call Jev (005–007) are next.
See [ROADMAP.md](ROADMAP.md) and [`issues/`](issues/).

---

## The bet

Every auto-clipper on the market fails the same way: the clip is *roughly* in the right
place but starts mid-thought, opens on a pronoun with no referent, or ends before the
punchline lands. That is not a "find the interesting part" problem. It is a **boundary
problem**, and boundaries are where existing Jev-based tools are weakest too:

| Tool | Boundary method | Weakness |
| --- | --- | --- |
| [jevmeter](https://github.com/ChetasLua/jevmeter) | highest rolling average over a 10–15s stretch | finds energy, not a self-contained thought |
| [jev-skip](https://github.com/valentynkit/jev-skip) | 30s caption windows snapped to sentence ends | window granularity is coarser than a cut |
| [youtube-sponsor-detection](https://github.com/trungdq88/youtube-sponsor-detection) | scan → anchor → trace back to lead-in | **right idea** — jevcut steals this and generalizes it |

## What jevcut does differently

1. **Boundaries are a `Choice` over enumerated cut points.** Code finds every plausible
   cut (sentence end, speech pause ≥350ms, shot change) and labels them `C01…Cnn`. Jev
   picks which one is the start and which is the stop. Jev never emits a timestamp — the
   jaggedness docs are explicit that it can't do numbers, and that bounded extraction
   should be a Choice over options. See [docs/QUESTIONS.md](docs/QUESTIONS.md).

2. **A cascade, not dense scoring.** A cheap windowed pass finds candidate anchors; only
   survivors get the expensive boundary + verification passes. Est. ~8× fewer tokens and
   ~20× fewer requests than scoring every sentence. See [docs/COST-MODEL.md](docs/COST-MODEL.md).

3. **An explicit standalone gate.** Dedicated Nouls for the failure modes that actually
   kill clips: starts mid-thought, dangling pronoun, payoff never lands. A clip that fails
   the gate is widened or dropped — never shipped. Under-clip on purpose.

4. **Live with a lookback ring buffer.** Live detection is always *late*, so the start is
   never "now". On trigger, one retro `Choice` over the buffered cut points recovers the
   real start. See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md#live-mode).

5. **Measured, not asserted.** Every claim above is an issue with a metric attached.
   [docs/EVAL.md](docs/EVAL.md) defines the harness and the baselines we must beat before
   any of this is worth believing.

## Honest framing on cost

Absolute cost here is already trivial — jev-skip reports **$0.0008/video** on a comparable
workload, and Jev bills input only at $0.042/Mtok. jevcut's cascade is not going to turn
cents into fractions of cents in a way anyone feels.

The cascade is worth building for **requests and latency**, not dollars: Jev's limit is
1,200 requests/minute, and dense per-sentence scoring burns that budget on an hour of
video. Fewer, fatter requests (one state, many parallel questions) is what makes live mode
and batch backfill viable. Cost savings are a side effect; say so in that order.

## Layout

```
docs/       design: architecture, question specs, cost model, eval plan, prior art
issues/     the work, one file per task, numbered and dependency-ordered
src/        implementation (empty)
eval/       labeled clips + metric harness (empty)
```

## Running it

```bash
uv sync --extra dev          # add --extra asr for Whisper, --extra shots for scene detection
uv run pytest                # 32 tests, no API key needed

# ingest -> cut points -> the exact state Pass D will send
uv run jevcut transcribe video.mp4 --from-json eval/fixtures/interview.words.json --out t.json
uv run jevcut cuts t.json --out c.json
uv run jevcut region t.json L009

uv run jevcut smoke                         # one live Noul, traced
```

`eval/fixtures/interview.words.json` is a synthetic word list, so everything above runs
with no ASR model and no API key.

**Reaching Jev.** Two backends, same code above them. `openrouter` (the default) posts to
`/api/alpha/decisions` with `typesafe/jev-1.13` and needs `OPENROUTER_API_KEY`;
`typesafe` uses the first-party SDK and `TYPESAFE_API_KEY`. Copy `.env.example` to
`.env.local` — it is gitignored, and a variable already set in your shell always wins.

## Reading order

[docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) → [docs/QUESTIONS.md](docs/QUESTIONS.md) →
[ROADMAP.md](ROADMAP.md) → pick an issue.
