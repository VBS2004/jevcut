"""Choose a clip's start and end by search: code lists the options, Jev judges each.

This replaced placing the clip by rule (anchor a third of the way in) and repairing it by
rule (widen on a mid-thought edge, then tighten). Across eight videos in seven genres that
path dropped 79 of 138 anchors, 74 of them for a mid-thought edge: the rule assumed where
a moment starts, and the repair could only move a too-early start further back. Measured
in RESEARCH.md ("Baseline on the pilot eval set").

The search assumes neither. For each anchor:

1. **Start.** Every real sentence boundary from as far back as the band allows up to the
   anchor becomes a candidate opening. All of them are marked in the transcript around
   the moment and one Choice picks the mark to come in on: the line that grabs, keeping
   the setup the moment needs. It replaced judging each opening alone and keeping the
   strongest ``hook`` among the clean ones -- relative beats absolute here, and it costs
   one request instead of ~9 (RESEARCH.md, "The opening as one Choice"). The final gate
   still judges the start of the finished clip.
2. **End.** From that start, every real boundary after the anchor that keeps the clip in
   the band is judged as the finished clip. Among those that pass the full gate, the
   earliest one clean on ``ends_mid_thought`` wins: the shortest clip that finishes its
   thought. With none clean, the least bad passing one. The winner's judgment is the
   final gate -- every candidate got the whole question set, so no extra request.

Real boundaries only -- sentence ends, speaker changes, the transcript's edges -- because
a ``pause`` can fall mid-sentence. No thresholds of its own: it reuses the gate's.
"""

from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, replace

from jevcut import gate as gate_mod
from jevcut.boundaries import CUT_PREFERENCE, Boundary, align_end, align_start
from jevcut.client import JevClient
from jevcut.config import Config
from jevcut.models import CutPoint, Sentence, Transcript
from jevcut.questions import opening_questions, promotion_questions
from jevcut.render import cut_id, render_markers

#: Transcript shown past the anchor, so the Choice can read what the moment is building to.
OPENING_CONTEXT_AFTER_S = 20.0
#: Transcript the ad check reads either side of a clip: long enough to reach the "brought
#: to you by" or the link from the middle of a typical 30-90s sponsor read.
PROMOTION_CONTEXT_S = 60.0
#: How many of the Choice's openings, best first, the finished-clip check may walk.
OPENING_SHORTLIST = 3
#: The least `hook` an opening must have. Level 0 is, in the question's own words,
#: "housekeeping, hesitation, or a thought already underway"; 1 is "states plainly what is
#: about to be discussed". So this vetoes greetings and openings already mid-argument.
OPENING_HOOK_FLOOR = 1.0

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


def openings(real: list[CutPoint], anchor, config: Config) -> list[tuple[CutPoint, CutPoint]]:
    """Every candidate opening for ``anchor``, each paired with the nearest ending that
    makes a short clip through the anchor inside the band -- enough for the start
    questions to read the opening in context."""
    low, high = config.duration_band_s
    spans = []
    for s in [c for c in real if anchor.t1 - high <= c.t_start <= anchor.t0]:
        ends = [c for c in real if c.t_end >= max(anchor.t1, s.t_start + low)]
        e = min(ends, key=lambda c: c.t_end, default=None)
        if e is not None and e.t_end - s.t_start <= high:
            spans.append((s, e))
    return spans


def choose_opening(
    client: JevClient,
    transcript: Transcript,
    spans: list[tuple[CutPoint, CutPoint]],
    anchor: Sentence,
) -> list[CutPoint]:
    """One Choice over every candidate opening, marked in place and renumbered from C00.
    The openings come back best first, by the weight the Choice put on each; empty when
    the request fails."""
    marks = {cut_id(i): start for i, (start, _) in enumerate(spans)}
    shown = [replace(start, id=mark) for mark, start in marks.items()]
    sentences = transcript.between(spans[0][0].t_start - 0.01, anchor.t1 + OPENING_CONTEXT_AFTER_S)
    try:
        result = client.ask(
            {"region": {"text": render_markers(sentences, shown), "moment": anchor.text}},
            opening_questions(list(marks)),
            pass_name="opening",
        )
    except Exception as exc:  # noqa: BLE001 - reported as a drop, never a crash
        log.warning("opening request failed for %s: %s", anchor.id, exc)
        return []
    answer = result.answers["opening"]
    weight = dict(answer.probabilities or {})
    weight[answer.choice] = float("inf")  # the pick leads even when no spread came back
    return [marks[m] for m in sorted(marks, key=lambda m: -weight.get(m, 0.0))]


def _good_opening(j: gate_mod.Judgment, config: Config) -> bool:
    """Clean at the start by the repair bar, and a real hook."""
    return (
        j.nouls.get("starts_mid_thought", 0.0) < config.repair_threshold
        and j.nouls.get("dangling_reference", 0.0) < config.repair_threshold
        and j.scores.get("hook", 0.0) >= OPENING_HOOK_FLOOR
    )


def _check_opening(
    client: JevClient,
    transcript: Transcript,
    real: list[CutPoint],
    ranked: list[CutPoint],
    result: SearchResult,
    config: Config,
) -> None:
    """The Choice ranks openings well against each other but sometimes lands on a greeting,
    a "But you're..." mid-argument, or the tail of the thought before -- failures the
    gate's questions see plainly in a finished clip. So when the finished clip's opening
    is not good, its next picks are judged against the same ending, and the first good
    one takes over. One request each, and only for clips that need it.

    On 38 videos this found more clips with both edges right on both labelers (35 -> 37,
    33 -> 37) and raised recall; it does not move the far-off tail (RESEARCH.md,
    "Shortlisting openings")."""
    if result.judgment is None or _good_opening(result.judgment, config):
        return
    low, high = config.duration_band_s
    end = next(c for c in real if c.id == result.boundary.end_cut)
    for start in ranked[1:OPENING_SHORTLIST]:
        if not low <= end.t_end - start.t_start <= high:
            continue
        result.requests += 1
        try:
            j = gate_mod.verify(client, _text(transcript, start.t_start, end.t_end), config)
        except Exception as exc:  # noqa: BLE001 - a lost candidate is skipped
            log.warning("opening check failed for %s: %s", start.id, exc)
            result.failed += 1
            continue
        if _good_opening(j, config):
            result.boundary, result.judgment = _boundary(start, end), j
            result.verdict = gate_mod.verdict(j, config)
            return


def search(
    client: JevClient,
    transcript: Transcript,
    cuts: list[CutPoint],
    anchor_id: str,
    config: Config | None = None,
) -> SearchResult:
    config = config or Config()
    anchor = transcript.by_id(anchor_id)
    real = _real(cuts)

    def no(reason: str, **counts) -> SearchResult:
        return SearchResult(None, None, gate_mod.Verdict(gate_mod.DROP, [reason]), **counts)

    # -- 1. the opening ------------------------------------------------------------------
    spans = openings(real, anchor, config)
    if not spans:
        return no("no opening fits the duration band")
    ranked = choose_opening(client, transcript, spans, anchor)
    if not ranked:
        return no("gate unavailable", requests=1, failed=1)
    # The final gate still reads the start of the finished clip, and its veto is kept:
    # openings it vetoed were in a labeler's range half as often as ones it passed. What
    # changed is the retry: the runner-up is now judged against the ending already found
    # (one request), not given a whole new ending search, which was tried and cut.
    result = _finish(client, transcript, real, anchor, ranked[0], config)
    result.requests += 1
    if result.boundary is not None:
        _check_opening(client, transcript, real, ranked, result, config)
    if result.ok:
        _screen_promotion(client, transcript, result, config)
    return result


def _screen_promotion(
    client: JevClient, transcript: Transcript, result: SearchResult, config: Config
) -> None:
    """One request on the finished clip: is it an ad? Sponsor reads open like part of the
    argument and pass every other question. A failed request ships the clip -- losing a
    real moment to a provider error is worse than the rare ad it might have caught."""
    t0, t1 = result.boundary.t0, result.boundary.t1
    state = {
        "clip": {"text": _text(transcript, t0, t1)},
        "around": {
            # Strictly outside the clip: `between` counts a sentence touching its bound.
            "before": _text(transcript, t0 - PROMOTION_CONTEXT_S, t0 - 0.01),
            "after": _text(transcript, t1 + 0.01, t1 + PROMOTION_CONTEXT_S),
        },
    }
    result.requests += 1
    try:
        answer = client.ask(state, promotion_questions(), pass_name="promotion")
    except Exception as exc:  # noqa: BLE001 - see the docstring
        log.warning("promotion request failed: %s", exc)
        result.failed += 1
        return
    p = answer.answers["promotion"].noul or 0.0
    result.judgment.nouls["promotion"] = p
    if p >= config.promotion_threshold:
        result.verdict = gate_mod.Verdict(gate_mod.DROP, ["promotion"])


def _end_badness(j: gate_mod.Judgment) -> float:
    return j.nouls.get("ends_mid_thought", 0.0)


def _clean_pass(j: gate_mod.Judgment, config: Config) -> bool:
    """The ending the search keeps: passes the gate, and clean below the repair bar."""
    return gate_mod.verdict(j, config).ok and _end_badness(j) < config.repair_threshold


def _finish(
    client: JevClient,
    transcript: Transcript,
    real: list[CutPoint],
    anchor: Sentence,
    start: CutPoint,
    config: Config,
) -> SearchResult:
    """-- 2. the ending: every real boundary that keeps the clip in the band, judged as
    the finished clip from ``start``."""
    low, high = config.duration_band_s
    ends = [c for c in real if c.t_end >= anchor.t1 and low <= c.t_end - start.t_start <= high]
    if not ends:
        return SearchResult(
            None, None, gate_mod.Verdict(gate_mod.DROP, ["no ending fits the duration band"])
        )
    # Judged in time order, a few at a time, stopping once one passes clean. The rule keeps
    # the earliest clean pass, and by the time one turns up every earlier ending has been
    # judged, so the rest cannot change the pick: same clip, 31% fewer ending judgments on
    # the pilot set. `ending_batch` trades requests (smaller) against round trips (larger);
    # 0 judges every ending, for eval runs that want the whole set on record.
    spans = sorted(((start, e) for e in ends), key=lambda span: span[1].t_end)
    batch = config.ending_batch or len(spans)
    judged: list[gate_mod.Judgment | None] = []
    for i in range(0, len(spans), batch):
        judged += _judge_all(client, transcript, spans[i : i + batch], config)
        if any(j is not None and _clean_pass(j, config) for j in judged):
            break
    spans = spans[: len(judged)]
    requests, failed = len(spans), sum(j is None for j in judged)
    finished = [(span, j) for span, j in zip(spans, judged, strict=True) if j is not None]
    if not finished:
        return SearchResult(
            None, None, gate_mod.Verdict(gate_mod.DROP, ["gate unavailable"]), requests, failed
        )

    passing = [(span, j) for span, j in finished if gate_mod.verdict(j, config).ok]
    if passing:
        # The shortest clip that finishes the thought: the earliest ending clean on
        # ``ends_mid_thought`` below the repair bar. Not the strongest payoff -- payoff
        # tends to rise with more material, so picking it drifted every clip long. Not
        # merely the earliest *passing* one either: the gate's own bar is looser, and the
        # earliest pass was often the setup with its answer cut off.
        clean = [sj for sj in passing if _end_badness(sj[1]) < config.repair_threshold]
        if clean:
            (_, end), j = min(clean, key=lambda sj: sj[0][1].t_end)
        else:
            (_, end), j = min(passing, key=lambda sj: (_end_badness(sj[1]), sj[0][1].t_end))
        return SearchResult(
            _boundary(start, end), j, gate_mod.Verdict(gate_mod.SHIP), requests, failed
        )

    # Nothing passes: report the closest miss, so the drop reason names a real failure.
    (_, end), j = max(finished, key=lambda sj: sj[1].scores.get("payoff", 0.0))
    return SearchResult(_boundary(start, end), j, gate_mod.verdict(j, config), requests, failed)
