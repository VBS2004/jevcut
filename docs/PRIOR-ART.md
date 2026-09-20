# Prior art

What exists, what it does well, what jevcut takes from it. Read before designing anything —
most of these solved a piece of this problem already.

## Jev-based video tools

### [trungdq88/youtube-sponsor-detection](https://github.com/trungdq88/youtube-sponsor-detection)
**The closest prior art, and the main source of this design.** Finds the start and stop of
sponsor reads in both VOD and live audio.

- Transcript rendered as `L042| …` lines, Jev picks line IDs, code maps to timestamps
  (the semantic-find pattern).
- 80-line windows to stay inside the token budget and keep irrelevant text out of state.
- Pipeline: **scan** windows in parallel → **anchor** the winner and find the last line →
  **trace back** to the start of the lead-in → repeat with the segment removed (max 6).
- Segment defined structurally: lead-in → pitch → offer. Merch and engagement requests
  explicitly excluded.
- Boundaries cut at phrase granularity where Jev holds ≥80% confidence.
- Live: asks every few seconds, over the last minute of audio, whether the speaker is
  inside a read right now.
- **Documented weakness worth memorizing:** audio modes capture the first seconds of the
  read to avoid cutting early. Detection lags the event. jevcut's ring buffer + retro-start
  Choice is the direct answer to this.

**Taken:** window size, scan→anchor→trace-back→repeat, line-ID addressing, live cadence,
structural definition of a segment.

### [ChetasLua/jevmeter](https://github.com/ChetasLua/jevmeter)
Live scoring meter over any video: every sentence scored, rendered as a 16:9 edit.

- Up to 6 yes/no questions per sentence; presets per content type (the debate preset:
  factual claim / evasive / contradicts self / emotional appeal / dodged question).
- Whisper word timestamps + `difflib` alignment against a provided transcript, so every
  sentence gets start/end times and per-word karaoke timings.
- Highlights: highest average index over a 10–15s stretch, per speaker. Editable `edl.json`.
- Offline only — full transcription and scoring before rendering.

**Taken:** per-preset question sets, Whisper + difflib sentence alignment, `edl.json` as
the handoff format. **Rejected:** rolling-average highlight selection — it finds energy,
not a self-contained thought, and it's Baseline 1 in [EVAL.md](EVAL.md).

### [valentynkit/jev-skip](https://github.com/valentynkit/jev-skip)
Browser extension deciding sponsor segments at watch time from captions.

- 30s caption windows snapped to sentence ends, capped at 45s.
- One Choice per window: `sponsor | intro | outro | self_promo | recap | other`.
- Regex pre-filter (URL, coupon-code shape, "use my link") before spending a request.
- Seek-bar heatmap, colour strength from probability. **Unsure segments painted faint and
  never skipped — it under-skips on purpose.**
- Reported: 77% of sponsor seconds caught, 34s of false skips/hour, ~$0.0008/video;
  one measured run 50 segments / 25.3k tokens / $0.0011 / 1546ms.

**Taken:** the under-skip philosophy (for clipping: a missed clip costs nothing, a bad clip
costs credibility), cheap code-side pre-filtering, publishing real cost/latency numbers.
**Rejected:** window-granularity boundaries.

## TypeSafe docs that directly shape the design

| Page | What it decides here |
| --- | --- |
| [Line-by-line search](https://docs.typesafe.ai/cookbooks/semantic_find.md) | Choice over line IDs; `none_of_these`; the 255-option ceiling; two-pass search for longer docs |
| [Jev 1.13 jaggedness](https://docs.typesafe.ai/model-jaggedness/jev-1.13.md) | No counting, no time math, no generation, no numeric interpolation on Scores; literal reading; context rot |
| [Models](https://docs.typesafe.ai/models.md) | Text-only input; 64k/32k context; 1,200 req/min; input-only billing |
| [Score](https://docs.typesafe.ai/primitives/score.md) | Levels must describe situations; each level judged independently; read `probabilities` and `confidence`, not just `score` |
| [Noul](https://docs.typesafe.ai/primitives/noul.md) | `NoulCriteria(true=…, false=…)`; one Noul per independent label |
| [Speculative fan-out](https://docs.typesafe.ai/patterns/fan-out.md) | Many questions, one state, one request |
| [Composite scoring](https://docs.typesafe.ai/patterns/composite-scoring.md) | Score dimensions once, let code own weights and thresholds |
| [SDE cascade](https://docs.typesafe.ai/cookbooks/sde_cascade.md) | Cheap pass first, expensive pass on survivors |
| [Confidence](https://docs.typesafe.ai/confidence.md) | Confidence is distribution concentration, not permission to act |

## Non-Jev auto-clippers

Opus Clip, Vizard, Klap and similar. Not studied in depth — closed pipelines — but their
user complaints define the target: clips that start mid-sentence, clips that open on a
pronoun with no referent, clips that end before the punchline. Those three complaints are
exactly Pass E's `starts_mid_thought`, `dangling_reference` and `payoff`.

If jevcut ships with those three rates measured and published, that alone differentiates it
from everything in this section.

## Directories worth watching

New Jev projects are appearing weekly; check these before building anything:
[hellogumbo/awesome-jev](https://github.com/hellogumbo/awesome-jev),
[cobanov/awesome-jev](https://github.com/cobanov/awesome-jev),
[logicrw/awesome-jev-projects](https://github.com/logicrw/awesome-jev-projects),
[AnotiaWang/awesome-jev](https://github.com/AnotiaWang/awesome-jev),
[dbreunig/building-with-jev-skill](https://github.com/dbreunig/building-with-jev-skill).
