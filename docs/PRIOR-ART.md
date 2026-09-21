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

## Classical methods

### TextTiling (Hearst 1997), via NLTK

Tested, not just read — [`eval/experiments/texttiling_vs_labels.py`](../eval/experiments/texttiling_vs_labels.py).

**What it does.** Chops text into fixed 20-word chunks, and at every gap compares the ~200
words before against the ~200 after. Lots of shared vocabulary means one subject is still
running; a deep valley means the vocabulary changed. Boundaries are the deepest valleys,
snapped to the nearest paragraph break.

**Tested against 48 human-placed boundaries** — SponsorBlock's labels on 20 real
transcripts, 336 minutes of speech. A sponsor read starts where the creator leaves the
subject, so its start is a topic boundary a person chose and timestamped.

| params | boundaries | /min | @1s | @2s | @5s | @15s |
| --- | --- | --- | --- | --- | --- | --- |
| w=20 k=10 (default) | 505 | 1.50 | 4% / **4%** | 12% / 9% | 23% / 20% | 60% / 49% |
| w=10 k=6 | 1051 | 3.13 | 6% / **9%** | 21% / 17% | 56% / 37% | 88% / 73% |
| w=30 k=15 | 334 | 0.99 | 0% / **3%** | 4% / 5% | 15% / 14% | 44% / 35% |
| w=50 k=20 | 194 | 0.58 | 4% / 1% | 6% / 3% | 10% / 8% | 27% / 23% |

Second figure is **chance at the same boundary density** — the same number of marks
scattered at random. That pairing is the experiment. Without it the default setting reads
as "60% recall" and looks like it works; it is emitting one boundary every 40 seconds, so a
±15s window already covers most of the timeline.

**At 1–2s, the resolution a cut point needs, it is at or below chance at every setting.**
Three of four score worse than random. Precision is ≤9.5% (505 boundaries for 48 labels).

There is real signal — 11–18 points over chance in the 5–15s band, so lexical cohesion does
shift when a read begins. It resolves at tens of seconds. It is a map of the country when
you need a house number.

This was close to the easiest case available: a sponsor read introduces wholly new
vocabulary (brand names, "discount code", "link in the description"). Failing there is
strong evidence it will not find where a thought begins.

**Caveats.** Sponsor boundaries are not clip boundaries. TextTiling snaps to paragraph
breaks and a transcript has none, so one was synthesised per caption cue — a defensible
choice that could move the numbers, and the largest caveat here. n=48. C99 and the neural
successors are untested, but they answer the same coarse question.

**Taken:** the density-controlled chance baseline, which is the method, not the result —
see [012](../issues/012-metrics-harness.md). **Rejected:** topic segmentation as a source of
cut points, and as a Pass C prior: 60%/49% is not good enough to gate on.

### Snapping to a fine boundary

The other classical method, the same 48 labels, and the one that still threatens the
thesis. Caption-cue starts — linguistically dumb, free, 25/min, near issue 003's target
density — land **81% within 1.0s and 94% within 2.0s**, median 0.5s.

So **failure mode 4 splits, and only half of it dies.** "Topic segmentation already solves
this" is answered: no. "Classical boundary snapping already solves this" is very much
alive — it is what autoclip ships and what Baseline 4 measures.

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

### [artbyjazi/autoclip](https://github.com/artbyjazi/autoclip)

**The same product as jevcut, already shipped, built the other way.** Local-first, MIT,
Python + React, ~9.6k LOC backend. yt-dlp ingest -> faster-whisper (+WhisperX diarization)
-> LLM highlight detection -> MediaPipe speaker-tracked 9:16 reframe -> burned ASS captions
-> export. Four providers (Anthropic/OpenAI/Gemini/Ollama) behind one Protocol.

Read in full: `pipeline/boundaries.py`, `pipeline/highlights.py`, `providers/base.py`,
`prompts/highlight_v1.txt`.

**It reached "the model never emits a timestamp" without Jev.** The model returns
`start_word_index`/`end_word_index`; the prompt says *"They are the only timing signal you
provide — do not estimate seconds."* The transcript is rendered `[1042]word` per word, so
"it never has to derive an index, only copy one". `providers/base.py` states the reason
outright: *"a model that is bad at arithmetic — which they all are — cannot produce a clip
that starts at the wrong moment."*

> So ID-addressing is **not a Jev advantage** and must not be claimed as one. It follows
> from every LLM being bad at numbers. What survives is narrower and stronger: autoclip has
> the model **copy** an index, which can still be wrong — and `base.py` handles that by
> *clamping* an out-of-range index into the window rather than rejecting it. A Choice over
> enumerated IDs **cannot emit an invalid option at all.** Constraint by construction vs.
> constraint by cleanup. That is the defensible difference.

**Boundaries use zero model calls** — three deterministic passes in `boundaries.py`:

1. sentence snap, +/-12 words; start ties resolve *earlier*, end ties resolve *later*
2. duration clamp into 20-90s, always landing on a sentence end; if nothing fits, the
   candidate is **dropped** rather than butchered
3. silence alignment: find the measured silence trough within 0.75s, start 120ms before
   speech, hold 280ms after the last word, stay 40ms clear of the silence edge because
   silence detection has hysteresis and the true edge sits slightly inside

This is [RESEARCH.md](../RESEARCH.md) failure modes 2 and 4 ("snapping is good enough",
"classical methods already solve it") **in production**. The author treats boundary quality
as settled; the open gate for their v0.1.0 is reframe quality, not boundaries.

**It argues against a constant pad, and it is right.** `boundaries.py`: *"Padding by a
constant clips breaths and plosives, because the gap before a word varies with how the
speaker breathes. Cutting inside actual silence is where a human editor would put the
blade."* This directly changed [009](../issues/009-edl-and-render.md), which specified a
flat 150-250ms pre-roll.

> Same reasoning changed [003](../issues/003-cut-point-extraction.md), which placed a cut
> point at the **middle** of the silence. The decisive argument turned out to be
> measurement, not audio: a midpoint makes a *correct* choice measure as wrong by half the
> gap, always in the same direction, and worst at the long gaps where clip boundaries
> actually sit — landing straight on `start_err_p90`, the M2 ship criterion. A cut point is
> now a **gap**, resolved to `t_start`/`t_end` by the role it plays.

**Convergent evidence on tie-breaks.** Start ties resolve earlier because *"starting
slightly wide is recoverable while clipping the hook is not"*; end ties resolve later. Three
independent projects — this, the sponsor repo's `KEEP_CONTENT`, and jevcut's own recorded
rule — all land on **err wide when uncertain**. Treat that as settled.

**No standalone gate, and a verification that does not exist.** Self-containment is a
scoring criterion *inside the prompt*, never a check on the output; nothing re-examines the
cut clip. That whole role is [007](../issues/007-pass-e-standalone-gate.md) and it is
genuinely absent here. The prompt also asks for a `hook` field — *"quote the actual opening
words of the clip, verbatim... This is used to verify the clip starts where you think it
does."* Every use of `hook` in the backend stores it, ships it to the UI and renders it as a
label. **It is never compared against the transcript.** The check described in the prompt
was specced and not built.

**The duration prior is where it should lose.** 20-90s hard range; `_clamp_duration` walks a
short clip's end forward sentence by sentence *until it reaches 20s*. When that fires, the
end boundary is chosen by the duration floor, not by where the thought ends.

> Specific prediction for [013](../issues/013-baseline-comparison.md): autoclip's boundary
> error should concentrate on clips near the 20s floor. If jevcut wins *there* and ties
> elsewhere, the thesis is scoped-but-real — and we will know exactly what it is worth.

**Patterns taken** (all four detailed in the issues they affect):

- **Windows sized and stepped in *time*, converted back to word indices**, so overlap stays
  constant regardless of speaking pace. 8 min windows / 60s overlap — far larger than the
  sponsor repo's 80 lines, because the binding constraint is now attention, not tokens.
- **Dedupe runs twice**: once on raw candidates, again *after* boundary refinement, because
  refinement moves edges enough to create new overlaps. [008](../issues/008-pass-f-ranking.md)
  will hit this exact bug. Greedy, highest score wins, IoU 0.4 on word ranges.
- **One bad window never loses the video** — per-window try/except, log, continue.
- **Validate -> retry with the actual validation error text** pasted into the repair prompt,
  plus coercions for the things models emit anyway (scores as 0-1 floats, `null` for strings,
  JSON wrapped in prose).

> That last cluster is ~100 lines of defence against malformed generation plus a retry
> round-trip. **jevcut pays none of it** — typed Jev output makes malformed responses
> structurally impossible. That is a sharper cost-of-generation argument than the token
> counts in [COST-MODEL.md](COST-MODEL.md), and it is currently unmade.

**Nobody in this category has numbers.** Their README: *"Also unverified: whether the clip
*picks* are good. That's a judgement call about your material and your model, and no test
settles it."* The sponsor repo commits no eval results either. jevcut's
[011](../issues/011-eval-set.md)/[012](../issues/012-metrics-harness.md) harness would be the
first real measurement in the space — a stronger position than owning a better mechanism.

**Taken:** time-stepped windowing, double dedupe, per-window failure isolation,
silence-trough alignment over constant padding, the wide-on-uncertainty tie-break (confirmed,
not new). **Rejected:** hard duration priors that override meaning, clamping invalid indices
instead of making them unrepresentable. **Available as a baseline:** it installs and runs
locally with Ollama — see [013](../issues/013-baseline-comparison.md).

### [modelscope/FunClip](https://github.com/modelscope/FunClip)

Alibaba/ModelScope, ~4.2k LOC, Gradio UI. ASR the video (FunASR/Paraformer, SenseVoice),
then **the human searches or selects transcript text** and it cuts the video at those
timestamps. Speaker diarization ("clip everything speaker 2 said") and a later LLM mode
sit on top. Read `videoclipper.py`, `utils/trans_utils.py`, plus 40 issues.

**The issue tracker is the find here, and it is the first real outside evidence this
project has.** 40 issues read: ~17 install/dependency/environment, 5 timestamp-mapping
bugs, 2 output-format, 1 silent failure, 3 feature requests. **Zero complaints that a clip
was badly chosen, zero that a boundary was semantically wrong.**

> Do not over-read that. FunClip does not *choose* clips — the user does — so it cannot be
> evidence for [RESEARCH.md](../RESEARCH.md) failure mode 1. What it is evidence about is
> where a transcript→timestamp system actually breaks, which is jevcut's architecture.

**All three open bugs live in one 20-line function.** `proc()` maps text to time in three
steps, each an unstated assumption:

1. find the query string in the transcript;
2. `ti = raw_text[:fi].count(' ')` — turn a character position into a word index by
   counting spaces;
3. `timestamp[ti][0] * 16` — index the timestamp array, multiply by 16.

- `*16` is milliseconds → samples at 16 kHz, hardcoded, and appears ~6 times in one
  function (`*16`, `/16000.0`). Non-16 kHz audio is silently wrong — **issue #214**.
- Step 2 assumes the ASR emits one space-separated token per timestamp entry. Swap
  Paraformer for SenseVoice and the format shifts, so the indices no longer line up. No
  crash, just wrong times — **issue #215**.
- On zero matches it sets `res_audio = data` and **returns the entire original video**,
  distinguished only by a message — **issue #198**.

**Why jevcut is structurally immune to all three.** FunClip does fuzzy string → word index
→ array index → timestamp → samples: four conversions, four assumptions. jevcut does
**ID → timestamp**, where the ID was minted by the same code that owns the timestamp. No
string matching, no index arithmetic, and no sample rate in the maths at all — seconds as
floats, converted once at render ([009](../issues/009-edl-and-render.md) should stay the
only place a sample rate appears). This is a more concrete argument for "code owns the
mapping" than "Jev cannot do numbers".

**It also found a real bug in ours.** #198's shape — a degraded result shaped exactly like
a healthy one — sent me to jevcut's own zero-result path, where `scan()` collected
per-window failures, logged them, and returned only the anchors. Two anchors from a clean
run and two from the one window that survived twenty 5xx's were the same value. Fixed in
`0c37b83`: coverage travels with the anchors and reaches disk
([005](../issues/005-pass-c-coarse-scan.md)).

**Taken:** never put a sample rate in timestamp arithmetic; a degraded result must not be
type-identical to a healthy one. **Rejected:** locating clips by matching transcript text,
which is the whole bug family above.

### Closed-source

Opus Clip, Vizard, Klap and similar. Not studied in depth — closed pipelines — but their
user complaints define the target: clips that start mid-sentence, clips that open on a
pronoun with no referent, clips that end before the punchline. Those three complaints are
exactly Pass E's `starts_mid_thought`, `dangling_reference` and `payoff`.

If jevcut ships with those three rates measured and published, that alone differentiates it
from everything in this section.

## Research literature

### AI-Based Video Clipping of Soccer Events (Valand et al., 2021)

*Mach. Learn. Knowl. Extr. 3(4)* — SimulaMet / UiT / OsloMet. Automates highlight clipping
for Norwegian and Swedish elite soccer with logo-transition detection, scene-boundary
detection (TransNetV2) and optional trimming.

**The first outside support this thesis has, from a domain with no speech in it.** The
industry baseline they set out to beat is a **static clip at −A and +B seconds around the
marked event** — Baseline 0 and Baseline 3, exactly. Their complaint about it:

> the clips often **start far too early or in the middle of the event of interest**, and
> they often **end abruptly in the middle of a replay**

which is the README's claim about mid-thought starts and missing payoffs, reached
independently in a different medium.

**The evidence is the production process, not the models.** Those leagues run a two-tier
annotation scheme: tier one marks *which* moment (fast, cheap, low-latency); tier two
"searches for a better clipping position", described as "time-consuming and costly" and
done only "if time and resources are available" — to the point that lower-league games go
unclipped. **An industry pays a separate tier of humans purely to fix boundaries, and
drops it when money is short.**

That is the closest thing we have to an answer for [RESEARCH.md](../RESEARCH.md) failure
mode 1, *"selection is the hard part, not boundaries"*, and it points the other way:
selection is tier one and cheap, boundaries are tier two and expensive.

**A prior on the size of the win.** Subjective scores, 1 (very poor) to 10 (broadcast
ready): static clipping **5.89**, boundary-refined **6.84**, boundary-refined and trimmed
**7.40**. So beating a constant offset is worth roughly **+1 point on a 10-point scale** —
real, and not enormous. Expect the same order of magnitude, not a transformation.

**Interior trimming, a concept jevcut does not have.** They cut *inside* the clip, dropping
celebration footage between the goal and the replays, and that version scored highest.
jevcut picks `t0` and `t1` and keeps everything between. The speech analogue is dropping a
tangent or a filler stretch mid-clip. **Logged as an idea, not a recommendation:** cutting
the interior of continuous speech is far more jarring than cutting between soccer replays,
and it would need a visible-edit convention to not read as a mistake.

**Logo transitions** are a domain-specific boundary anchor — a production artifact that
already marks where a segment ends. Not literally transferable, but it is the same move as
jevcut's `speaker_change` and `shot` cut kinds: take the boundaries the medium hands you
before inferring any.

**Taken:** the subjective evaluation protocol (now in
[012](../issues/012-metrics-harness.md)), the +1-point prior, the two-tier argument for
failure mode 1. **Noted, not taken:** interior trimming.

## Directories worth watching

New Jev projects are appearing weekly; check these before building anything:
[hellogumbo/awesome-jev](https://github.com/hellogumbo/awesome-jev),
[cobanov/awesome-jev](https://github.com/cobanov/awesome-jev),
[logicrw/awesome-jev-projects](https://github.com/logicrw/awesome-jev-projects),
[AnotiaWang/awesome-jev](https://github.com/AnotiaWang/awesome-jev),
[dbreunig/building-with-jev-skill](https://github.com/dbreunig/building-with-jev-skill).
