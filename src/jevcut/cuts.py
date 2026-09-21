"""Issue 003 -- cut-point extraction.

The quality claim rests on this module. Jev can only choose a boundary we hand it as an
option, so a boundary missing from this list is unrecoverable downstream -- and in the
traces it looks exactly like a model error. Issue 010's coverage check exists to tell
those two apart; this module's job is to make it rarely matter.
"""

from __future__ import annotations

import itertools
import statistics
from pathlib import Path

from jevcut.config import MAX_CHOICE_OPTIONS, Config
from jevcut.models import CUT_KIND_PRIORITY, CutPoint, Region, Transcript
from jevcut.render import cut_id, render_markers

# Which candidate survives thinning. Deliberately NOT CUT_KIND_PRIORITY: that one names
# the strongest *physical* signal when two candidates coincide, while this one ranks how
# good a *clip boundary* each kind makes. A sentence end beats a shot change, because a
# viewer forgives a cut on a held frame and never forgives one mid-word.
# "edge" is first because it is unrecoverable: no other candidate can stand in for the
# start of the first sentence or the end of the last.
CUT_THIN_WEIGHT = {"edge": 5, "speaker_change": 4, "sentence_end": 3, "shot": 2, "pause": 1}


def extract(
    transcript: Transcript,
    config: Config | None = None,
    *,
    shots: list[float] | None = None,
) -> list[CutPoint]:
    """Enumerate every plausible boundary, then thin to the target density."""
    config = config or Config()
    raw: list[CutPoint] = []

    if transcript.sentences:
        # The two boundaries the sentence-pair loop below can never emit: a clip may
        # legitimately open on the first word or close on the last, and without these
        # the model is simply not offered that option. That is a silent recall hole --
        # it looks like a model error in the traces and is really a missing candidate.
        raw.append(CutPoint(id="", t=transcript.sentences[0].t0, kind="edge"))
        raw.append(CutPoint(id="", t=transcript.sentences[-1].t1, kind="edge"))

    for i, s in enumerate(transcript.sentences):
        nxt = transcript.sentences[i + 1] if i + 1 < len(transcript.sentences) else None

        if nxt is not None:
            gap = max(nxt.t0 - s.t1, 0.0)
            # Sit in the middle of the silence: a clip that opens on a breath sounds wrong
            # even when the boundary is semantically correct.
            t = s.t1 + gap / 2
            kind = (
                "speaker_change"
                if (s.speaker and nxt.speaker and s.speaker != nxt.speaker)
                else "sentence_end"
            )
            raw.append(CutPoint(id="", t=t, kind=kind, gap_ms=gap * 1000))

        for a, b in zip(s.words, s.words[1:]):
            gap = b.t0 - a.t1
            if gap >= config.pause_cut_s:
                raw.append(
                    CutPoint(id="", t=a.t1 + gap / 2, kind="pause", gap_ms=gap * 1000)
                )

    for t in shots or []:
        raw.append(CutPoint(id="", t=float(t), kind="shot", gap_ms=0.0))

    merged = _merge(raw, config.merge_window_s)
    thinned = _thin(merged, config.min_cut_spacing_s)
    return _assign_ids(thinned)


def _merge(cuts: list[CutPoint], window_s: float) -> list[CutPoint]:
    """Collapse candidates within ``window_s``, keeping the strongest kind present."""
    if not cuts:
        return []
    ordered = sorted(cuts, key=lambda c: c.t)
    out: list[CutPoint] = [ordered[0]]
    for c in ordered[1:]:
        last = out[-1]
        if c.t - last.t <= window_s:
            better = CUT_KIND_PRIORITY[c.kind] > CUT_KIND_PRIORITY[last.kind]
            tie = CUT_KIND_PRIORITY[c.kind] == CUT_KIND_PRIORITY[last.kind] and c.gap_ms > last.gap_ms
            if better or tie:
                out[-1] = CutPoint(id="", t=c.t, kind=c.kind, gap_ms=max(c.gap_ms, last.gap_ms))
        else:
            out.append(c)
    return out


def _thin(cuts: list[CutPoint], min_spacing_s: float) -> list[CutPoint]:
    """Greedy: keep the best candidate in each neighbourhood.

    Denser than one per ~2s bloats the Choice option list without giving Jev a
    meaningfully different boundary to pick; sparser and the right cut starts falling
    between candidates.
    """
    kept: list[CutPoint] = []
    for c in sorted(cuts, key=lambda c: (-CUT_THIN_WEIGHT[c.kind], -c.gap_ms, c.t)):
        if all(abs(c.t - k.t) >= min_spacing_s for k in kept):
            kept.append(c)
    return sorted(kept, key=lambda c: c.t)


def _assign_ids(cuts: list[CutPoint]) -> list[CutPoint]:
    return [CutPoint(id=cut_id(i), t=c.t, kind=c.kind, gap_ms=c.gap_ms) for i, c in enumerate(cuts)]


def build_region(
    transcript: Transcript,
    cuts: list[CutPoint],
    anchor_id: str,
    config: Config | None = None,
) -> Region:
    """Anchor +/- ``region_pad_s``, with cut points renumbered locally from C00.

    Local numbering keeps the option list short and stable regardless of where in a
    three-hour video the anchor sits.
    """
    config = config or Config()
    anchor = transcript.by_id(anchor_id)
    t0 = max(anchor.t0 - config.region_pad_s, 0.0)
    t1 = anchor.t1 + config.region_pad_s

    sentences = transcript.between(t0, t1)
    local = _assign_ids([c for c in cuts if t0 <= c.t <= t1])

    if len(local) > MAX_CHOICE_OPTIONS - 1:  # -1 leaves room for the no-match option
        raise ValueError(
            f"{len(local)} cut points in region for {anchor_id} exceeds the Choice option "
            f"limit; raise min_cut_spacing_s or lower region_pad_s"
        )

    return Region(
        anchor_id=anchor_id,
        t0=sentences[0].t0 if sentences else t0,
        t1=sentences[-1].t1 if sentences else t1,
        sentences=sentences,
        cuts=local,
        text=render_markers(sentences, local),
    )


def stats(cuts: list[CutPoint], duration: float) -> dict:
    """Density report. ``median_spacing_s`` should land in the 2-4s target band."""
    spacings = [b.t - a.t for a, b in itertools.pairwise(cuts)]
    by_kind: dict[str, int] = {}
    for c in cuts:
        by_kind[c.kind] = by_kind.get(c.kind, 0) + 1
    return {
        "count": len(cuts),
        "per_minute": len(cuts) / (duration / 60.0) if duration else 0.0,
        "median_spacing_s": statistics.median(spacings) if spacings else 0.0,
        "max_spacing_s": max(spacings) if spacings else 0.0,
        "by_kind": by_kind,
    }


def coverage(
    cuts: list[CutPoint],
    targets: list[float],
    tolerance_s: float = 1.0,
    role: str = "either",
) -> dict:
    """Issue 003's gating metric: is there a candidate near every boundary a human chose?

    Below 95%, no amount of question tuning helps -- the model cannot choose an option it
    was never given.

    Compares the **role-resolved** edge, never the midpoint ``t``: human labels are
    word-anchored, so matching them against a midpoint spends up to half a gap of the
    tolerance on a difference of convention rather than of judgment.

    ``role`` is ``"start"``, ``"end"``, or ``"either"``. ``"either"`` is the honest answer
    to "could a candidate serve this boundary at all", since one cut point can serve both
    roles at two different instants; pass the specific role when the targets are known to
    be all starts or all ends.
    """
    if not targets:
        return {"recall": 1.0, "misses": [], "n": 0}

    if role == "start":
        edges = [(c.t_start,) for c in cuts]
    elif role == "end":
        edges = [(c.t_end,) for c in cuts]
    elif role == "either":
        edges = [(c.t_start, c.t_end) for c in cuts]
    else:
        raise ValueError(f"role must be 'start', 'end' or 'either', not {role!r}")

    misses = [
        t for t in targets if not any(abs(e - t) <= tolerance_s for pair in edges for e in pair)
    ]
    return {
        "recall": 1 - len(misses) / len(targets),
        "misses": misses,
        "n": len(targets),
    }


def detect_shots(media: str | Path, threshold: float = 27.0) -> list[float]:
    """Shot-change times via PySceneDetect. Optional; audio-only content has none."""
    try:
        from scenedetect import ContentDetector, detect
    except ImportError as exc:  # pragma: no cover - depends on optional extra
        raise RuntimeError("scenedetect is not installed; `uv sync --extra shots`") from exc
    return [scene[0].get_seconds() for scene in detect(str(media), ContentDetector(threshold))]
