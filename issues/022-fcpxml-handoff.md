# 022 — FCPXML: hand the cut to an editor

| | |
| --- | --- |
| **Milestone** | M4 Product |
| **Depends on** | [009](009-edl-and-render.md) — the EDL and the render |
| **Blocks** | — |
| **Size** | S |
| **Status** | **Done** (2026-09-27) — `src/jevcut/fcpxml.py`, `tests/test_fcpxml.py`. `jevcut clip`/`run` write `clips.fcpxml` beside `edl.json` whenever `--media` is known, and `jevcut fcpxml` converts an EDL on its own, including one edited by hand. |

## Why this exists

Two outputs existed, and neither is something an editor can work with.

`edl.json` is jevcut's own format. The renderer reads it back and a human can edit it,
which is the point — [009](009-edl-and-render.md) argues that a correction belongs in data
rather than in an argument about prompt wording. But no NLE knows what it is. The name is
borrowed from the industry's EDL and collides with it; this file is not a CMX3600 EDL and
never claimed to be.

The mp4s are the other end: finished goods. Fine to post, useless to adjust. A clip that
wants two more seconds at the head has already lost them — the handles are gone.

So between "a number in a JSON file" and "a rendered file" there was nothing in between.
The gap matters because the judge is not going to be right every time, and the honest
answer to a boundary a human disagrees with is *let them move it*, not re-render and hope.

## What it writes

One FCPXML. Premiere, DaVinci Resolve and Final Cut all import it.

- **It points at the source video, not at the mp4s.** That is the whole reason to emit
  it: the clip keeps its handles, so an editor drags for two more seconds instead of
  asking for a re-render.
- **One project (sequence) per clip.** Each clip ships as its own Short; a single timeline
  holding all of them in a row would be one more thing to cut apart. Named
  `NN <the clip's own words>`, so the bin reads in rank order.
- **`render_t0`/`render_t1`, the times ffmpeg cuts**, so the timeline and the mp4s agree.
- **The measured boundary rides along as a marker**, because that is the judgment being
  handed over. An editor moving a cut should be able to see what the model actually chose,
  and the two timestamps differ on purpose ([009](009-edl-and-render.md)).
- **The clip's text as a note**, so the reason it was picked travels with it.

## The part that is easy to get wrong

FCPXML times are rationals on the format's frame grid, not decimals. `12.5s` is a file
some importers reject and others silently round somewhere you did not choose. At 29.97
(`30000/1001`) a whole second is not a whole number of frames at all: 12.0s is frame 360,
which is `3003/250s`. Everything converts through `Fraction`, and `probe_frame_rate` keeps
the rate exact — 30000/1001 is not 29.97, and rounding it puts every later timecode a
frame further out the longer the video runs.

The other trap is an `asset-clip` claiming media the `asset` does not have. A clip on the
last sentence has its tail nudged past the final word ([009](009-edl-and-render.md)), and
an importer reads the overhang as a corrupt file rather than as a clip to shorten. Spans
are clamped to the probed duration.

## Not built

- **CMX3600 `.edl`.** Universal and older, but one flat timeline with no names, no notes
  and no markers — everything above that makes the handoff worth having is exactly what it
  cannot carry. Worth adding only if something downstream demands it.
- **Captions into the timeline.** `captions.py` burns ASS into the render. Carrying them
  as titles an editor can restyle is a bigger job and a separate decision.
- **Renaming `edl.json`.** The collision with the industry term is real and now more
  confusing, since a genuine interchange file sits beside it. A rename touches
  [009](009-edl-and-render.md), the renderer, the eval and every stored run, so it is its
  own change.
