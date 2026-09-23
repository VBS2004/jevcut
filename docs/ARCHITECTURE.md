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
| Choosing the start and stop cut points | **code** — changed 2026-09-22; was Jev (Pass D) |
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
 media ──▶ [A] transcribe ──▶ [B] cut points ──▶ [C] coarse scan ──▶ [D] boundaries ──▶ [E] verify ──▶ [F] rank ──▶ [G] render
            code                code              JEV (cheap)        code               JEV            code        code
                                                                          ▲                 │
                                                                          └─ widen/tighten ─┘
```

[D] and [E] loop: the gate's verdict moves an edge by whole cut points and the clip is
verified again.

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

Iterate with the winning anchor's neighbourhood removed, up to **3 anchors per window**,
stopping when `contains_moment` drops below threshold. (Removal-and-repeat is the
sponsor-detection loop.)

### D. Boundaries — *code only* (was: Jev, 1 request per anchor)

**Changed 2026-09-22.** Pass D was going to be a Choice over the enumerated cut points.
Across six experiments a tuned constant offset matched or beat that Choice on every
boundary task we could measure, so boundaries moved into code and Jev moved to judging
clips instead. Issue 006 is off the critical path; the reasoning is in
[RESEARCH.md](../RESEARCH.md).

`boundaries.place()`: put the anchor about a third of the way into the clip, snap each
edge to a cut point (preferring kinds that make good boundaries — a `pause` can fall
mid-sentence, so it ranks last), clamp into the duration band by moving the end first,
and align the rendered edges into the surrounding silence. No request.

### E. Verify — the clip gate *(Jev, 1+ requests per candidate clip)*

The state is the exact clip text and nothing else — no title, no surrounding
transcript — because that is the condition the viewer will be in.

Seven questions in one request. Exact wording lives in `src/jevcut/questions.py`; the
rationale is in [QUESTIONS.md](QUESTIONS.md#pass-e--the-clip-gate).

| question | type | role |
| --- | --- | --- |
| `needs_the_room` | Noul | **drop** — the point depends on the live audience, not the speakers. Judged only on the final cut |
| `starts_mid_thought`, `dangling_reference` | Noul | **repair** — widen the start |
| `ends_mid_thought` | Noul | **repair** — widen the end |
| `standalone` | Noul | **repair** — widen both, when nothing more specific failed |
| `hook` | Score | ranking; guards start-side trims |
| `payoff` | Score | ranking; guards end-side trims; bottom level ⇒ widen the end |

It runs as a loop, not a single pass: widen on a low bar (0.5) for up to three
attempts, then judge on a high bar (0.75); a clip that passes is then **tightened** one
cut point at a time, keeping each trim only if it still passes and neither `hook` nor
`payoff` drops. All thresholds are measured on two videos only — placeholders for 014.

A `worth_clipping` question was deleted 2026-09-23: flattest of eight questions across 38
clips and never once fired, because it asked the model to combine `hook` and `payoff`,
which the ranking already does in code.

### F. Rank and resolve — *code only*

- **Ranking:** composite `0.625·hook + 0.375·payoff`, each normalised to 0–1, best first.
- **Overlap resolution:** after boundaries are placed, clips sharing >40% of their span
  (IoU) keep the higher composite. Overlap between clips that each stand alone is fine.
- **Duration:** the band is enforced by `place()` and by the widen/tighten loop, never
  by re-asking the model.

The original plan said never trim to fit; the loop now does trim, because a human judged
a 65s clip ten seconds too long. The guard is what makes that safe: an unguarded trim
cut *"That guy, Terrence, is always talking about open source"* down to *"That's the
culture of this organization"* — both passed the gate, only one was a clip.

## Live mode

Live is **better on latency and cost** (you hold seconds of state, not an hour) and
**worse on boundaries** (no future, and detection always lags the event). The whole design
is about buying the boundary quality back.

```
 stream ──▶ streaming ASR ──▶ ring buffer (90s) ──▶ tick every 4s ──▶ trigger ──▶ retro-start ──▶ record ──▶ (optional) VOD tighten
                              code                  JEV Noul          code FSM     JEV Choice      code        [D]+[E] loop
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
- **Tighten (optional).** Once the segment is recorded it's a VOD: run the [D]+[E] loop on it for a
  frame-tight cut. Live gives you a clip in ~5s with a soft tail; the tighten pass gives
  you the good cut a minute later. Ship both.

## Request budget

| | requests | why |
| --- | --- | --- |
| Pass C | up to 3 per 80-sentence window (asked again after each anchor); windows overlap by 60s | measured 15 and 18 per video |
| Boundaries | 0 | code |
| Pass E | 1–7 per candidate clip | one verify, up to 3 widens, up to 3 tightens; measured 35–73 per video |
| **VOD total** | **~50–90 per video** | vs ~600/hour for per-sentence dense scoring |
| Live | ~900/hr | one tick per 4s, plus ~2 per triggered clip (planned, not measured) |

Measured on the two test videos (~335 and ~430 sentences, 5 and 6 windows). Their durations were not
recorded, so there is no per-hour VOD figure yet; 018 adds it. The planned ~32/hour
assumed one gate request per clip — the widen/tighten loop is most of the difference.

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
  downstream if you want them.
- No visual judgment in v1 (no "is the speaker on camera"). Shot cuts are used only as
  candidate boundaries.
- No cross-video memory and no speaker identity. v1 has no diarization at all, so
  transcripts carry no speaker labels.
