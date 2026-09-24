# jevcut

Auto-clipping that picks **cut points**, not windows.

Given a full video (or a live stream), jevcut finds the moments worth clipping and
decides exactly where each clip should **start** and **stop** — using
[Jev](https://docs.typesafe.ai/models.md), TypeSafe's System One model, as a judge over
transcript text, with all arithmetic, timing and rendering in code.

Status: **research MVP — runs end to end on real video.** `jevcut run talk.mp4` turns a
talk into ranked, rendered clips: cut points (003), Pass C anchors
(005), a boundary search where code lists candidate edges and the clip gate judges each (007), composite
ranking (008), EDL and ffmpeg render (009), and a response cache for reproducible runs
(004). Validated on two FOSDEM videos, a solo talk and a panel; a human rated the solo
talk's output. Thresholds are measured on those two videos only and are not calibrated —
that is 014. The research phase that changed the design is in [RESEARCH.md](RESEARCH.md);
see [ROADMAP.md](ROADMAP.md) and [`issues/`](issues/).

**Scope: v1 clips verbal content** — podcasts, interviews, talks, panels, streams where
people talk. The judge is Jev over transcript text, so a moment carrying no words (a crash,
a scream, a stunt) is invisible to it by construction. That is a deliberate v1 boundary,
not an oversight: see [issue 021](issues/021-event-clips.md).

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

1. **Code lists the edges; Jev judges the clips they make.** Code enumerates every
   plausible cut (sentence end, speech pause ≥350ms, speaker change) and never lets a
   model name a timestamp. *This took two tries.* First Jev was to pick a cut from a
   `Choice` — a tuned constant offset kept matching it. Then code placed and repaired the
   clip by rule — on eight labeled videos that dropped 57% of moments for a ragged edge.
   Now code offers every real opening and ending as a candidate and Jev judges the clip
   each would make: recall on the pilot set went 0.23 → 0.41. Edges are still the weak
   point (few land inside a labeler's acceptable range), and the numbers are in
   [RESEARCH.md](RESEARCH.md), with the early experiments in
   [`eval/experiments/`](eval/experiments/) for anyone who wants to disagree.

   **Jev is spent where arithmetic cannot compete even in principle:** whether a moment is
   worth clipping, whether the clip stands alone, whether the payoff lands inside the cut.
   No offset or snapping rule answers those — there is nothing for it to compute on.

2. **A cascade, not dense scoring.** A cheap windowed pass finds candidate anchors; only
   survivors get the expensive boundary + verification passes. Est. ~8× fewer tokens and
   ~20× fewer requests than scoring every sentence. See [docs/COST-MODEL.md](docs/COST-MODEL.md).

3. **An explicit standalone gate — now the main event.** Dedicated Nouls for the failure
   modes that actually kill clips: starts mid-thought, dangling pronoun, payoff never
   lands. Every candidate edge is judged; a clip no candidate can make pass is dropped — never shipped. Under-clip on
   purpose. **No open-source clipper we read has any output check at all** — autoclip asks
   its model for self-containment as a scoring criterion and never verifies the clip it
   cut. See [docs/PRIOR-ART.md](docs/PRIOR-ART.md).

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
docs/       design: concepts, architecture, question specs, cost model, eval plan, prior art
issues/     the work, one file per task, numbered and dependency-ordered
src/        the pipeline: transcript, cut points, scan, boundaries, gate, ranking, render
tests/      unit tests; no API key, model or media needed
scripts/    check_docs.py — do the docs still describe the code?
eval/       a synthetic fixture and the research experiments; no labeled set yet (011)
```

## Running it

```bash
uv sync --extra dev          # add --extra asr for Whisper (brings the CUDA runtime, so an
                             # NVIDIA GPU is used), --extra shots for scene detection
uv run pytest                # no API key needed
uv run ruff check .          # lint; the known findings are listed below
uv run python scripts/check_docs.py   # do the docs still describe the code?

# a real video, end to end -> ranked mp4s, an editable edl.json and index.html (a page
# to watch them on, best first, with the scores that ranked them), all in clips/
# a second run reuses clips/transcript.json, so ASR runs once; Jev answers are cached
uv run jevcut run talk.mp4 --language en --out clips/
# optional, on run or clip: --vertical centre-crops to 9:16 at 1080x1920 (no face
# tracking yet), --captions burns in word-level captions from the transcript
uv run jevcut run talk.mp4 --language en --out clips/ --vertical --captions

# the same in two steps
uv run jevcut transcribe talk.mp4 --model small --language en --out t.json
uv run jevcut clip t.json --media talk.mp4 --out clips/

# without ASR, from the synthetic fixture
uv run jevcut transcribe x --from-json eval/fixtures/interview.words.json --out t.json

# score every labeled video's run against its labels (eval/labels-v2, issue 011); no API
# calls. What a label means -- the shortest cut that works, opening on its hook -- is
# eval/RUBRIC.md. Score a change against the second labeler too: eval eval/labels-v2-b
uv run jevcut eval --note "what changed"
# how much two independent labelers agree -- the noise floor any boundary error sits on
uv run jevcut agree eval/labels-v2 eval/labels-v2-b

# the stages one at a time
uv run jevcut cuts t.json --out c.json
uv run jevcut region t.json L009   # the transcript around one anchor, with cut points marked
uv run jevcut scan t.json          # Pass C — costs real requests
uv run jevcut smoke                # one live Noul, traced
```

`eval/fixtures/interview.words.json` is a synthetic word list, so from there on no ASR
model is needed, and `cuts` and `region` need no API key either.

**Lint.** The tree is formatted and `ruff check` reports three findings, all left on
purpose: one long line in `cli.py` that is a Noul criterion string — splitting it risks
losing a space in prompt text that has to read exactly as written — and an `l` loop
variable with its single-element slice in `test_render.py`, where `next(...)` would only
trade an `IndexError` for a `StopIteration` in a test that fails either way.

The formatting run is listed in `.git-blame-ignore-revs`. Turn it on with
`git config blame.ignoreRevsFile .git-blame-ignore-revs` so blame skips it.

**Reaching Jev.** Two backends, same code above them. `openrouter` (the default) posts to
`/api/alpha/decisions` with `typesafe/jev-1.13` and needs `OPENROUTER_API_KEY`;
`typesafe` uses the first-party SDK and `TYPESAFE_API_KEY`. Copy `.env.example` to
`.env.local` — it is gitignored, and a variable already set in your shell always wins.

## Review

[docs/REVIEW-LOG.md](docs/REVIEW-LOG.md) records what a review of M0 found, with the
reproduction for each defect. Worth reading before trusting any of this.

## Reading order

**[docs/CONCEPTS.md](docs/CONCEPTS.md)** → [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) →
[docs/QUESTIONS.md](docs/QUESTIONS.md) → [ROADMAP.md](ROADMAP.md) → pick an issue.

Start with CONCEPTS: it defines the sentence IDs, cut points and regions that every other
document uses without explaining.
