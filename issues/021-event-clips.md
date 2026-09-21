# 021 — Event clips: non-verbal moments

| | |
| --- | --- |
| **Milestone** | Post-v1 (deferred) |
| **Depends on** | M2 complete — v1 measured on verbal content first |
| **Blocks** | nothing in 001–020 |
| **Size** | XL |
| **Status** | **Deferred by decision, 2026-09-21.** v1 is verbal-only and says so. |

## Why this exists

jevcut's judge is text-only: Jev reads the transcript, and
[CONCEPTS.md](../docs/CONCEPTS.md) builds everything on top of that. So the whole pipeline
is blind to a moment that carries no words — a crash, a scream, a stunt landing, a fail, a
jumpscare, a dunk. Those are clips. They are arguably the most clipped things on the
internet. The current design cannot see them, and worse, it does not know it cannot.

This is not a boundary problem, which is what the README's thesis is about. It is a
different clip class with a different boundary mechanism, and it needs its own detector.

## Two clip classes

| | **verbal clip** (v1) | **event clip** (this issue) |
| --- | --- | --- |
| example | a claim, a setup + punchline, a question answered | crash, scream, stunt, fail, crowd reaction |
| boundary lives in | the language — sentence, thought, turn | the signal — onset, impact, reaction tail |
| what marks the start | the setup line before the payoff | ~1–2 s *before* the transient |
| what marks the end | the thought completing | the reaction decaying |
| does text carry it | yes | no — and ASR fabricates there |

## Where the current design breaks

Three specific places, all in code that is written or specced:

1. **Pass C ([005](005-pass-c-coarse-scan.md)) can never nominate one.** The coarse scan
   reads transcript windows. A crash produces a window holding `[Music]`, `whoa`, or
   nothing. There is no anchor to find. This is a **selection recall hole** — the clip
   never enters the pipeline to be mis-bounded.

2. **ASR poisons the state exactly there.**
   [002](002-transcript-ingest.md) already records that Whisper hallucinates on silence and
   music. So the highest-energy moment in the video is where the transcript reads
   `Thanks for watching!`. The judge is not merely blind, it is fed fiction.

3. **The standalone gate ([007](007-pass-e-standalone-gate.md)) would reject them anyway.**
   `starts_mid_thought`, `dangling_reference`, `payoff` are linguistic tests. A scream has
   no thought to be mid-of, no pronoun, no payoff sentence. The quality mechanism would
   specifically destroy this clip class.

## What the eval will and will not tell us

The set in [EVAL.md](../docs/EVAL.md) includes gameplay/reaction, so labelers **will** mark
event clips as ground truth and the pipeline **will** miss them. The miss is visible.

The *cause* is not. It will present as Pass C recall failure, and the decision-log row for
that case says "gate too tight — lower `contains_moment`". Following that row would loosen
a threshold to chase clips that no threshold can reach, spending precision for nothing.

**So: when 012 reports Pass C recall, split the number by clip class before acting on it.**
That is the one thing v1 must do about this issue.

## Approach sketch (not a spec)

Detection is classical and free; only the judgment of *worth* is semantic.

- **Onset / transient** — per-frame loudness (`ffmpeg ebur128`, `astats`), spectral flux
  (`librosa.onset`). An impact is a step change; speech is not.
- **Audio event classification** — YAMNet / AudioSet: 521 labels including `screaming`,
  `crash`, `explosion`, `cheering`, `laughter`, `crowd`. Pretrained, CPU, no API. This is
  the primary candidate generator.
- **`inaSpeechSegmenter`** — speech / music / noise over the timeline, so code knows where
  the transcript is worthless and should not be fed to Jev at all.
- **`silero-vad` inverted** — the moment of interest is often exactly where speech is not.
- **Reaction as proxy** — the cleanest detector of "something happened" is often the
  reaction: a laughter burst, a crowd roar, a gasp. Acoustic (YAMNet) *and* lexical
  (interjection density: "oh my god", "no way"). The lexical half reaches the transcript,
  which is the bridge back to Jev.

**Where Jev still fits.** Code cannot judge whether the event is worth clipping — a crash
at a demolition derby is unremarkable, the same crash in a cooking video is the whole clip.
That is semantic. Code describes the event to Jev in text, the same move the sponsor repo
makes when it writes `sponsor_named_at` into state:

```
state:      event: "crash 0.91, screaming 0.84"   (from YAMNet, written by code)
            loudness step: "+18 LU"
            transcript around it: "...watch this—" [gap] "OH MY GOD"
questions:  worth_clipping        (Noul)
            needs_setup_line      (Noul — is the line before required for it to land?)
```

**Watch for this result:** the boundary for an event clip may be purely mechanical —
`onset − 1.5 s → reaction decay + 0.5 s`, no Choice needed. If that holds, it is real
evidence that the README's thesis is **scoped to verbal content** rather than general.
That is a finding worth having, not a defeat. See [RESEARCH.md](../RESEARCH.md).

## What would trigger picking this up

- v1 is measured on verbal content and passes the M2 gate, **and**
- Pass C recall split by clip class shows event clips are a material share of the labels
  we are missing.

If M2 fails on verbal content, this issue stays closed — a second detector on top of a
thesis that did not survive is the wrong order of work.
