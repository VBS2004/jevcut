"""Clip boundaries, set in code.

This used to be Pass D's job -- a Choice over enumerated cut points. Six experiments
later a tuned constant offset was still matching or beating that Choice on every
boundary task we could measure, so the work moved here and Jev moved to the judgments
arithmetic cannot make at all. The reasoning is in RESEARCH.md; the experiments are in
eval/experiments/ for anyone who wants to disagree with them.

Three steps, no model call:

1. **Place** the clip around the anchor, with the anchor about a third of the way in --
   a clip needs a run-up to make sense and a longer tail for the point to land.
2. **Snap** each edge to a cut point, preferring the kinds that make good clip
   boundaries. Never land mid-word.
3. **Align** the rendered edge into the silence the cut point sits in. A constant pad
   cannot do this: the gap before a word varies with how the speaker breathes, so one
   number clips plosives on a tight entry and leaves dead air on a slow one.

Steps 1-2 produce the *measured* boundary, which is what the eval scores. Step 3
produces the *rendered* edge, which is what ffmpeg cuts. They are different numbers on
purpose and both are kept.
"""

from __future__ import annotations

from dataclasses import dataclass

from jevcut.config import Config
from jevcut.models import CutPoint, Transcript

#: How good a clip boundary each kind makes, independent of how strong a physical signal
#: it is. A viewer forgives a cut on a held frame and never forgives one mid-word, and a
#: `pause` can fall *inside* a sentence, so it ranks last despite being a real silence.
CUT_PREFERENCE = {"edge": 4, "speaker_change": 3, "sentence_end": 2, "shot": 1, "pause": 0}

#: A cut this much better-preferred is worth moving this much further for.
SNAP_WINDOW_S = 2.5

#: Where the anchor sits in the finished clip. A clip is mostly payoff, with a shorter
#: run-up: enough setup to follow, not so much that the hook is buried.
LEAD_FRACTION = 0.35

#: Render-side only, and never folded back into the measured boundary.
SILENCE_LEAD_S = 0.12
SILENCE_TAIL_S = 0.28
SILENCE_MARGIN_S = 0.04
FALLBACK_LEAD_S = 0.25
FALLBACK_TAIL_S = 0.35


@dataclass(frozen=True, slots=True)
class Boundary:
    """A clip's edges. ``t0``/``t1`` are measured; ``render_t0``/``render_t1`` are cut."""

    t0: float
    t1: float
    render_t0: float
    render_t1: float
    start_cut: str
    end_cut: str

    @property
    def duration(self) -> float:
        return self.t1 - self.t0


def _snap(cuts: list[CutPoint], target: float, *, as_start: bool) -> CutPoint | None:
    """The cut nearest ``target``, preferring kinds that make good clip boundaries.

    Within ``SNAP_WINDOW_S`` a better kind wins outright; past that, distance decides.
    Ties resolve *wide* -- earlier for a start, later for an end -- because a clip that
    begins slightly early is recoverable and one that clips its own first word is not.
    """
    if not cuts:
        return None
    near = [c for c in cuts if abs(c.t_start - target) <= SNAP_WINDOW_S]
    pool = near or cuts
    return max(
        pool,
        key=lambda c: (
            CUT_PREFERENCE.get(c.kind, 0) if near else 0,
            -abs(c.t_start - target),
            # Ties resolve outward: earlier for a start, later for an end.
            (-c.t_start if as_start else c.t_start) * 1e-6,
        ),
    )


def place(
    transcript: Transcript,
    cuts: list[CutPoint],
    anchor_id: str,
    config: Config | None = None,
) -> Boundary | None:
    """Turn one anchor into a cuttable clip, or ``None`` if no valid one exists.

    Returning ``None`` is a real answer: a candidate that would have to be butchered to
    fit the duration band is better dropped than shipped short.
    """
    config = config or Config()
    low, high = config.duration_band_s
    target = (low + high) / 2.0
    anchor = transcript.by_id(anchor_id)

    before = [c for c in cuts if c.t_end <= anchor.t0]
    after = [c for c in cuts if c.t_start >= anchor.t1]
    if not before or not after:
        return None

    start = _snap(before, anchor.t0 - target * LEAD_FRACTION, as_start=True)
    end = _snap(after, (start.t_start if start else anchor.t0) + target, as_start=False)
    if start is None or end is None:
        return None

    # Clamp into the band by moving the END: the run-up is what makes the clip legible,
    # so it is the last thing to give up.
    if end.t_end - start.t_start > high:
        fits = [c for c in after if c.t_end - start.t_start <= high]
        if not fits:
            return None
        end = max(fits, key=lambda c: c.t_end)
    if end.t_end - start.t_start < low:
        longer = [c for c in after if low <= c.t_end - start.t_start <= high]
        if longer:
            end = min(longer, key=lambda c: c.t_end)
        else:
            # Nothing forward fits, so reach further back instead.
            wider = [c for c in before if low <= end.t_end - c.t_start <= high]
            if not wider:
                return None
            start = max(wider, key=lambda c: c.t_start)

    duration = end.t_end - start.t_start
    if not (low <= duration <= high):
        return None

    return Boundary(
        t0=start.t_start,
        t1=end.t_end,
        render_t0=align_start(start),
        render_t1=align_end(end),
        start_cut=start.id,
        end_cut=end.id,
    )


def align_start(cut: CutPoint) -> float:
    """Pull the rendered start back into the silence before the first word."""
    gap = cut.gap_ms / 1000.0
    if gap <= 0:
        return max(0.0, cut.t_start - FALLBACK_LEAD_S)
    earliest = min(cut.t_end + SILENCE_MARGIN_S, cut.t_start)
    return max(0.0, max(earliest, cut.t_start - SILENCE_LEAD_S))


def align_end(cut: CutPoint) -> float:
    """Hold the rendered end into the silence after the last word."""
    gap = cut.gap_ms / 1000.0
    if gap <= 0:
        return cut.t_end + FALLBACK_TAIL_S
    latest = max(cut.t_start - SILENCE_MARGIN_S, cut.t_end)
    return min(latest, cut.t_end + SILENCE_TAIL_S)
