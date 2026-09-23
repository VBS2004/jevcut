"""Choose a clip's start and end by search: code lists the options, Jev judges each.

This replaced placing the clip by rule (anchor a third of the way in) and repairing it by
rule (widen on a mid-thought edge, then tighten). Across eight videos in seven genres that
path dropped 79 of 138 anchors, 74 of them for a mid-thought edge: the rule assumed where
a moment starts, and the repair could only move a too-early start further back. Measured
in RESEARCH.md ("Baseline on the pilot eval set").

The search assumes neither. For each anchor:

1. **Start.** Every real sentence boundary from as far back as the band allows up to the
   anchor becomes a candidate opening. Each is judged on a short clip from there through
   the anchor; the start questions decide. Among openings clean on both
   ``starts_mid_thought`` and ``dangling_reference``, the strongest ``hook`` wins, ties to
   the later (tighter) start. With none clean, the least bad one goes forward and the
   final gate decides.
2. **End.** From that start, every real boundary after the anchor that keeps the clip in
   the band is judged as the finished clip. Among those that pass the full gate, the
   strongest ``payoff`` wins, ties to the earlier (tighter) end. The winner's judgment is
   the final gate -- every candidate got the whole question set, so no extra request.

Real boundaries only -- sentence ends, speaker changes, the transcript's edges -- because
a ``pause`` can fall mid-sentence. No thresholds of its own: it reuses the gate's.
"""

from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass

from jevcut import gate as gate_mod
from jevcut.boundaries import CUT_PREFERENCE, Boundary, align_end, align_start
from jevcut.client import JevClient
from jevcut.config import Config
from jevcut.models import CutPoint, Transcript

log = logging.getLogger(__name__)


@dataclass(slots=True)
class SearchResult:
    boundary: Boundary | None
    judgment: gate_mod.Judgment | None
    verdict: gate_mod.Verdict
    requests: int = 0
    #: Candidates whose request failed (e.g. the provider was overloaded). They are skipped,
    #: not fatal: one lost answer must not throw away a whole video's run.
    failed: int = 0

    @property
    def ok(self) -> bool:
        return self.boundary is not None and self.verdict.ok


def _real(cuts: list[CutPoint]) -> list[CutPoint]:
    return [c for c in cuts if CUT_PREFERENCE.get(c.kind, 0) >= CUT_PREFERENCE["sentence_end"]]


def _text(transcript: Transcript, t0: float, t1: float) -> str:
    return " ".join(s.text for s in transcript.between(t0, t1))


def _boundary(start: CutPoint, end: CutPoint) -> Boundary:
    return Boundary(
        t0=start.t_start,
        t1=end.t_end,
        render_t0=align_start(start),
        render_t1=align_end(end),
        start_cut=start.id,
        end_cut=end.id,
    )


def _judge_all(
    client: JevClient, transcript: Transcript, spans: list[tuple[CutPoint, CutPoint]], config
) -> list[gate_mod.Judgment | None]:
    """Verify every span in parallel; a failed request is ``None``, never an exception."""

    def one(span: tuple[CutPoint, CutPoint]) -> gate_mod.Judgment | None:
        start, end = span
        try:
            return gate_mod.verify(client, _text(transcript, start.t_start, end.t_end), config)
        except Exception as exc:  # noqa: BLE001 - one lost candidate must not sink the clip
            log.warning("gate request failed for %s-%s: %s", start.id, end.id, exc)
            return None

    with ThreadPoolExecutor(max_workers=config.scan_concurrency) as pool:
        return list(pool.map(one, spans))


def search(
    client: JevClient,
    transcript: Transcript,
    cuts: list[CutPoint],
    anchor_id: str,
    config: Config | None = None,
) -> SearchResult:
    config = config or Config()
    low, high = config.duration_band_s
    anchor = transcript.by_id(anchor_id)
    real = _real(cuts)

    def no(reason: str, **counts) -> SearchResult:
        return SearchResult(None, None, gate_mod.Verdict(gate_mod.DROP, [reason]), **counts)

    # -- 1. the opening ------------------------------------------------------------------
    starts = [c for c in real if anchor.t1 - high <= c.t_start <= anchor.t0]
    spans = []
    for s in starts:
        # A short clip from this opening through the anchor: enough for the start
        # questions to read the opening in context, and inside the band.
        ends = [c for c in real if c.t_end >= max(anchor.t1, s.t_start + low)]
        e = min(ends, key=lambda c: c.t_end, default=None)
        if e is not None and e.t_end - s.t_start <= high:
            spans.append((s, e))
    if not spans:
        return no("no opening fits the duration band")

    judged = _judge_all(client, transcript, spans, config)
    requests, failed = len(spans), sum(j is None for j in judged)
    opened = [(span, j) for span, j in zip(spans, judged, strict=True) if j is not None]
    if not opened:
        return no("gate unavailable", requests=requests, failed=failed)

    def start_badness(j: gate_mod.Judgment) -> float:
        return max(j.nouls.get("starts_mid_thought", 0.0), j.nouls.get("dangling_reference", 0.0))

    clean = [(span, j) for span, j in opened if start_badness(j) < config.repair_threshold]
    if clean:
        (start, _), _ = max(clean, key=lambda sj: (sj[1].scores.get("hook", 0.0), sj[0][0].t_start))
    else:
        (start, _), _ = min(opened, key=lambda sj: (start_badness(sj[1]), -sj[0][0].t_start))

    # -- 2. the ending -------------------------------------------------------------------
    ends = [c for c in real if c.t_end >= anchor.t1 and low <= c.t_end - start.t_start <= high]
    if not ends:
        return no("no ending fits the duration band", requests=requests, failed=failed)
    spans = [(start, e) for e in ends]
    judged = _judge_all(client, transcript, spans, config)
    requests += len(spans)
    failed += sum(j is None for j in judged)
    finished = [(span, j) for span, j in zip(spans, judged, strict=True) if j is not None]
    if not finished:
        return no("gate unavailable", requests=requests, failed=failed)

    passing = [(span, j) for span, j in finished if gate_mod.verdict(j, config).ok]
    if passing:
        (_, end), j = max(
            passing, key=lambda sj: (sj[1].scores.get("payoff", 0.0), -sj[0][1].t_end)
        )
        return SearchResult(
            _boundary(start, end), j, gate_mod.Verdict(gate_mod.SHIP), requests, failed
        )

    # Nothing passes: report the closest miss, so the drop reason names a real failure.
    (_, end), j = max(finished, key=lambda sj: sj[1].scores.get("payoff", 0.0))
    return SearchResult(_boundary(start, end), j, gate_mod.verdict(j, config), requests, failed)
