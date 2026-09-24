# Architecture

> New here? [CONCEPTS.md](CONCEPTS.md) defines sentence IDs (`L018`), cut points (`C03`)
> and regions. This page assumes them.

## Division of labour

The single rule this design is built on: **Jev judges meaning; code owns everything
countable.** From the [jaggedness page](https://docs.typesafe.ai/model-jaggedness/jev-1.13.md),
`jev-1.13` cannot count, cannot compare timestamps, cannot interpolate numbers between
Score levels, and is not trained to generate. It is also text-only — no audio or video
input — so the model never touches media.

| Concern | Owner |
| --- | --- |
| ASR, word timestamps | code (faster-whisper) |
| Diarization | **not built** — measured as unnecessary for v1 (see [RESEARCH.md](../RESEARCH.md)) |
| Shot changes, silence gaps, loudness | code (ffmpeg / PySceneDetect) |
| Enumerating candidate cut points | code |
| Choosing the start and stop cut points | **code lists, Jev judges** — the boundary search (2026-09-24); was code by rule, before that Jev (Pass D) |
| "Is this a moment?" / "does it stand alone?" / "does it land?" | **Jev** |
| Durations, overlap resolution, ranking weights, thresholds | code |
| Rendering, captions, aspect crop | code (ffmpeg) |

## Data model

```
Word      { text, t0, t1, speaker }
Sentence  { id: "L042", text, t0, t1, speaker, words[] }
CutPoint  { id: "C07", t, kind: sentence_end|pause|shot|speaker_change, gap_ms }
Anchor    { sentence_id, window_id, kind, p_moment, anchor_confidence, anchor_probability }
Clip      { id, anchor_id, kind, t0, t1, render_t0, render_t1, start_cut, end_cut, text, scores{}, rank }
```

`Word.speaker` exists but ASR never fills it — there is no diarization in v1 (see
[RESEARCH.md](../RESEARCH.md)). `t0/t1` are the snapped cut points; `render_t0/render_t1`
are those edges aligned into the surrounding silence, which is what ffmpeg cuts.

Sentence IDs are the model's handle on the transcript — the
[line-by-line search cookbook](https://docs.typesafe.ai/cookbooks/semantic_find.md)
pattern: render the transcript as `L042| text…`, let Jev return a line ID, map it back to
a timestamp in code. Cut point IDs work the same way for boundaries.

## VOD pipeline

```
 media ──▶ [A] transcribe ──▶ [B] cut points ──▶ [C] coarse scan ──▶ [D+E] boundary search ──▶ [F] rank ──▶ [G] render
            code                code              JEV (cheap)        code lists, JEV judges       code        code
```

[D] and [E] are one step: code lists candidate openings and endings at real sentence
boundaries, the gate judges each candidate as a clip, and code keeps the best.

### C. Coarse scan — find anchors *(Jev, up to 3 requests per window)*

Transcript split into **80-sentence windows** (the sponsor-detection window size; keeps
state small, which matters because accuracy falls as state fills with irrelevant detail).
Each request asks all three questions in parallel against the same state:

- `contains_moment` — Noul gate.
- `anchor` — Choice over the window's line IDs **plus `none_of_these`**. Choice
  probabilities sum to 1, so something always wins; the explicit no-match option and the
  Noul gate are what stop a flat window from producing a fake anchor.
- `kind` — Choice: `story | hot_take | explanation | joke | demo | none`. It was going to
  route Pass D's boundary rules; with boundaries in code nothing decides on it, so it is
  stored on the clip as a label. Keep it if presets (020) use it, drop it if 014 doesn't.

**Code reads the anchor vote by stretch, not by line.** A moment is several lines, so
its vote splits across them; code adds the probabilities up over ±20s around each line,
the strongest stretch wins, and the anchor is Jev's top line inside it. `none_of_these`
has to beat that whole stretch to end the window. (Added 2026-09-23: on a real talk the
best hot take had 31% over four lines and lost to a single demo line on 18%.)

Iterate with the winning stretch removed, up to **3 anchors per window**, stopping when
`contains_moment` drops below threshold or `none_of_these` outweighs every stretch.
(Removal-and-repeat is the sponsor-detection loop.) The last window ends on the last
sentence at full size, so its winner competed against as many lines as any other.

### D. Boundaries — *code lists, Jev judges* (`search.py`)

**Twice changed.** Pass D was going to be a Choice over the enumerated cut points; across
six experiments a tuned constant offset matched or beat it, so on 2026-09-22 boundaries
moved into code: place the anchor a third of the way in, snap to cut points, then widen
or tighten one cut point at a time on the gate's verdict. On the pilot eval set that
dropped 79 of 138 anchors, 74 for a mid-thought edge — the rule assumed where a moment
starts, and the repair could only move a too-early start further back. So on 2026-09-24
placement and repair were replaced by a search (RESEARCH.md has both measurements):

1. **Opening.** Every real boundary — sentence end, speaker change, the transcript's
   edges; never a `pause`, which can fall mid-sentence — from as far back as the band
   allows up to the anchor. Each is judged on a short clip from there through the anchor.
   Among openings clean on `starts_mid_thought` and `dangling_reference` the strongest
   `hook` wins, ties to the tighter one.
2. **Ending.** From that opening, every real boundary after the anchor that keeps the
   clip in the band, judged as the finished clip. Among those passing the full gate the
   strongest `payoff` wins, ties to the tighter one. Its judgment is the final gate.

No thresholds of its own. A failed request skips that candidate rather than the video.
The rendered edges are then aligned into the surrounding silence (`boundaries.py`).

### E. Verify — the clip gate *(Jev, one request per candidate; ~15 per anchor)*

The state is the exact clip text and nothing else — no title, no surrounding
transcript — because that is the condition the viewer will be in.

Seven questions in one request. Exact wording lives in `src/jevcut/questions.py`; the
rationale is in [QUESTIONS.md](QUESTIONS.md#pass-e--the-clip-gate).

| question | type | role |
| --- | --- | --- |
| `needs_the_room` | Noul | **drop** — the point depends on the live audience, not the speakers. Checked on each finished clip |
| `starts_mid_thought`, `dangling_reference` | Noul | **choose the opening** — a start is clean when both are low |
| `ends_mid_thought` | Noul | **choose the ending** — must pass on the finished clip |
| `standalone` | Noul | must pass on the finished clip |
| `hook` | Score | picks among clean openings; ranking |
| `payoff` | Score | picks among passing endings; ranking; bottom level fails the clip |

The same question set judges every candidate the search lists (§D): the start questions
choose the opening, the rest choose the ending and pass or fail the finished clip. An
opening counts as clean below 0.5; a finished clip passes below 0.75 on the mid-thought
and dangling questions. All thresholds are placeholders for 014.

A `worth_clipping` question was deleted 2026-09-23: flattest of eight questions across 38
clips and never once fired, because it asked the model to combine `hook` and `payoff`,
which the ranking already does in code.

### F. Rank and resolve — *code only*

- **Ranking:** composite `0.625·hook + 0.375·payoff`, each normalised to 0–1, best first.
- **Overlap resolution:** after boundaries are placed, clips sharing >40% of their span
  (IoU) keep the higher composite. Overlap between clips that each stand alone is fine.
- **Duration:** the band bounds which candidates the search lists, so no clip is trimmed
  or padded to fit afterwards.

`hook` choosing the opening is the lesson of an earlier trim loop: a shorter clip that
still passed cut *"That guy, Terrence, is always talking about open source"* down to
*"That's the culture of this organization"* — both passed the gate, only one was a clip.
Passing is the floor; the scores pick among the clips that clear it.

## Live mode

Live is **better on latency and cost** (you hold seconds of state, not an hour) and
**worse on boundaries** (no future, and detection always lags the event). The whole design
is about buying the boundary quality back.

```
 stream ──▶ streaming ASR ──▶ ring buffer (90s) ──▶ tick every 4s ──▶ trigger ──▶ retro-start ──▶ record ──▶ (optional) VOD tighten
                              code                  JEV Noul          code FSM     JEV Choice      code        [D+E] search
```

**Not built, and planned before the VOD finding.** On VOD, code beat a Choice over cut
points at placing boundaries, so 017 should try a code retro-start (step back a fixed
lead and snap) before the Choice below. Live may still differ — detection lag is not a
constant — so measure it rather than assume either way.

- **Ring buffer, 90s.** Sentences + cut points kept in memory continuously.
- **Tick: every 4s, one Noul** — "over the last 60s, is the speaker inside a moment right
  now?" This is the sponsor-detection live cadence.
- **Hysteresis FSM.** Enter on 2 consecutive ticks `p > 0.70`; exit on 3 consecutive ticks
  `p < 0.40`. A dip mid-sentence must not end a clip.
  Note: a Noul near 0.5 means "yes and no are similarly likely", **not** "medium
  intensity". It's a gate, never a dial.
- **Retro-start.** On enter at time T, do *not* start at T. One Choice over the buffered
  cut points: "which cut point did this moment begin on?" The sponsor-detection repo hit
  this exact problem — its audio mode eats the first seconds of the read. The ring buffer
  is the fix.
- **Tail.** On exit, one `end_cut` Choice over cut points since the trigger.
- **Tighten (optional).** Once the segment is recorded it's a VOD: run the boundary search on it for a
  frame-tight cut. Live gives you a clip in ~5s with a soft tail; the tighten pass gives
  you the good cut a minute later. Ship both.

## Request budget

| | requests | why |
| --- | --- | --- |
| Pass C | up to 3 per 80-sentence window (asked again after each anchor); windows overlap by 60s | 160 for the pilot set, ~34 per hour of media |
| Boundary search + gate | ~15 per anchor, openings then endings | 2,017 for the pilot set, ~435 per hour |
| **VOD total** | **~470 per hour of media** | vs ~600/hour for per-sentence dense scoring |
| Live | ~900/hr | one tick per 4s, plus ~2 per triggered clip (planned, not measured) |

Measured on the pilot eval set: 8 videos, 4.6 hours of media, 138 anchors (2026-09-24).
The planned ~32/hour assumed one gate request per clip; the search spends ~15 per anchor
because it judges every candidate edge instead of repairing one placed clip. Still well
inside the rate limit, and cheap: a few cents per hour of media.

Against a 1,200 req/min limit, VOD backfill is free and live costs 15 req/min per stream —
so roughly 70 concurrent streams before the account limit binds. That, not the token bill,
is the number that decides whether this scales.

## Reaching the model

Two backends behind one normalized `Response`, so no pass knows which is in use:

| Backend | Transport | Model | Key |
| --- | --- | --- | --- |
| `openrouter` (default) | `POST /api/alpha/decisions`, stdlib HTTP | `typesafe/jev-1.13` | `OPENROUTER_API_KEY` |
| `typesafe` | `typesafe-sdk` | `jev-1.13.0` | `TYPESAFE_API_KEY` |

Question payloads are identical either way — the SDK's `model_dump()` already emits the
exact JSON the Decisions API documents, so questions are authored once as `Noul`/`Choice`/
`Score` objects regardless of route.

**On pinning.** `typesafe/jev-1.13` is a minor-version pointer, not a fixed build: it
resolved to `typesafe/jev-1.13-20260917` on 2026-09-20. It is stable enough to develop
against, but **issue 014 must pin the dated ID** before any threshold is called tuned,
because a threshold tuned against one build is not valid on the next. Every trace line
records `model_requested` alongside `model_answered`, so the day that pointer moves is
visible in the logs rather than inferred from drifting metrics.

## Non-goals

- No generated titles, captions or descriptions. Jev doesn't generate; use another model
  downstream if you want them. (The optional burned-in captions are the transcript's own
  words at their own timings, not generated text.)
- No visual judgment in v1 (no "is the speaker on camera"). Shot cuts are used only as
  candidate boundaries.
- No cross-video memory and no speaker identity. v1 has no diarization at all, so
  transcripts carry no speaker labels.
