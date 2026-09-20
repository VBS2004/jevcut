# Architecture

## Division of labour

The single rule this design is built on: **Jev judges meaning; code owns everything
countable.** From the [jaggedness page](https://docs.typesafe.ai/model-jaggedness/jev-1.13.md),
`jev-1.13` cannot count, cannot compare timestamps, cannot interpolate numbers between
Score levels, and is not trained to generate. It is also text-only — no audio or video
input — so the model never touches media.

| Concern | Owner |
| --- | --- |
| ASR, word timestamps, diarization | code (Whisper / Deepgram) |
| Shot changes, silence gaps, loudness | code (ffmpeg / PySceneDetect) |
| Enumerating candidate cut points | code |
| "Is this a moment?" / "which cut point?" / "does it stand alone?" | **Jev** |
| Durations, overlap resolution, ranking weights, thresholds | code |
| Rendering, captions, aspect crop | code (ffmpeg) |

## Data model

```
Word      { text, t0, t1, speaker }
Sentence  { id: "L042", text, t0, t1, speaker, words[] }
CutPoint  { id: "C07", t, kind: sentence_end|pause|shot|speaker_change, gap_ms }
Anchor    { sentence_id, window_id, kind, p_moment }
Clip      { start_cut, end_cut, t0, t1, anchor, scores{}, gates{}, verdict }
```

Sentence IDs are the model's handle on the transcript — the
[line-by-line search cookbook](https://docs.typesafe.ai/cookbooks/semantic_find.md)
pattern: render the transcript as `L042| text…`, let Jev return a line ID, map it back to
a timestamp in code. Cut point IDs work the same way for boundaries.

## VOD pipeline

```
 media ──▶ [A] transcribe ──▶ [B] cut points ──▶ [C] coarse scan ──▶ [D] refine ──▶ [E] verify ──▶ [F] rank ──▶ [G] render
            code                code              JEV (cheap)        JEV           JEV            code        code
```

### C. Coarse scan — find anchors *(Jev, 1 request per window)*

Transcript split into **80-sentence windows** (the sponsor-detection window size; keeps
state small, which matters because accuracy falls as state fills with irrelevant detail).
One request per window, all questions in parallel against the same state:

- `contains_moment` — Noul gate.
- `anchor` — Choice over the window's line IDs **plus `none_of_these`**. Choice
  probabilities sum to 1, so something always wins; the explicit no-match option and the
  Noul gate are what stop a flat window from producing a fake anchor.
- `kind` — Choice: `story | hot_take | explanation | joke | demo | none`. This routes
  Pass D: a joke needs a tight setup→punchline cut, an explanation needs the premise, a
  hot take needs the question that provoked it. Same pipeline, different boundary rules.

Iterate with the winning anchor's neighbourhood removed, up to **3 anchors per window**,
stopping when `contains_moment` drops below threshold. (Removal-and-repeat is the
sponsor-detection loop.)

### D. Refine — pick the cut points *(Jev, 1 request per anchor)*

State: anchor ±90s of transcript, with **every candidate cut point inlined** as
`«C07»` markers between sentences. One request, four parallel questions:
`start_cut`, `end_cut`, `needs_more_setup`, `cold_open_ok`. Specs in
[QUESTIONS.md](QUESTIONS.md).

Two Choices over ~30–50 cut IDs each. Well inside the 255-option Choice limit; a 90s
window will never approach it.

### E. Verify — the standalone gate *(Jev, 1 request per candidate clip)*

A **second request is required** here, not optional: the state is the exact clip text,
which doesn't exist until D answers. That is the documented reason to split a request —
an earlier answer constructs new state.

Six questions, all against the cut text alone, with zero surrounding context — because
that is exactly the condition the viewer will be in. `dangling_reference`,
`starts_mid_thought`, `ends_mid_thought`, `standalone`, `hook` (Score), `payoff` (Score).

### F. Rank and resolve — *code only*

Policy lives here so it can change without re-running inference (evidence and question
meanings are unchanged, so the judgments are reusable):

- **Hard gates** (any failure ⇒ widen once, then drop): `starts_mid_thought > 0.5`,
  `dangling_reference > 0.5`, `payoff` score in the bottom level.
- **Weighted score** for ranking: `hook`, `payoff`, `p_moment`, anchor Choice confidence.
- **Overlap resolution:** clips sharing >40% of their span — keep the higher composite.
- **Duration policy:** target band per preset, enforced in code. If `end_cut − start_cut`
  falls outside the band, re-ask D with the band stated in the instructions rather than
  trimming blindly.

"Widen once" = re-run D with the start constrained to earlier cut points. Never trim to
fit a duration target; a clip that doesn't fit the band is a clip that was cut wrong.

## Live mode

Live is **better on latency and cost** (you hold seconds of state, not an hour) and
**worse on boundaries** (no future, and detection always lags the event). The whole design
is about buying the boundary quality back.

```
 stream ──▶ streaming ASR ──▶ ring buffer (90s) ──▶ tick every 4s ──▶ trigger ──▶ retro-start ──▶ record ──▶ (optional) VOD tighten
                              code                  JEV Noul          code FSM     JEV Choice      code        Pass D+E
```

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
- **Tighten (optional).** Once the segment is recorded it's a VOD: re-run D+E on it for a
  frame-tight cut. Live gives you a clip in ~5s with a soft tail; the tighten pass gives
  you the good cut a minute later. Ship both.

## Request budget

| | requests / hour of video | why |
| --- | --- | --- |
| Pass C | ~8 | one per 80-sentence window |
| Pass D | ~12 | one per surviving anchor |
| Pass E | ~12 | one per candidate clip |
| **VOD total** | **~32** | vs ~600 for per-sentence dense scoring |
| Live | ~900/hr | one tick per 4s, plus ~2 per triggered clip |

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
- No cross-video memory or speaker identity beyond diarization labels.
