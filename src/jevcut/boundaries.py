"""Clip boundaries: which cut points make good edges, and where the render actually cuts.

Choosing *which* cut points bound a clip is search.py's job: code lists the candidates
and Jev judges each finished clip. That replaced placing the clip by rule (the anchor a
third of the way in) and repairing it by widening or trimming one cut point at a time,
which on the pilot eval set dropped 57% of anchors for a mid-thought edge (RESEARCH.md).

What stays here is the part no judgment is needed for:

- **Which kinds of cut make a clip boundary** (``CUT_PREFERENCE``). A ``pause`` can fall
  mid-sentence, so only sentence ends, speaker changes and the transcript's edges count.
- **Aligning the rendered edge** into the silence the cut point sits in. A constant pad
  cannot do this: the gap before a word varies with how the speaker breathes, so one
  number clips plosives on a tight entry and leaves dead air on a slow one.

The cut point's own times are the *measured* boundary, which is what the eval scores; the
aligned edge is the *rendered* one, which is what ffmpeg cuts. They are different numbers
on purpose and both are kept.
"""

from __future__ import annotations

from dataclasses import dataclass

from jevcut.models import CutPoint

#: How good a clip boundary each kind makes, independent of how strong a physical signal
#: it is. A viewer forgives a cut on a held frame and never forgives one mid-word, and a
#: `pause` can fall *inside* a sentence, so it ranks last despite being a real silence.
CUT_PREFERENCE = {"edge": 4, "speaker_change": 3, "sentence_end": 2, "shot": 1, "pause": 0}

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
