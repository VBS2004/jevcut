"""Issue 005 -- Pass C: the coarse scan for anchors.

The cheap half of the cascade. One request per 80-sentence window finds the lines worth
spending real money on; everything downstream costs two more requests per survivor, so
this gate's threshold *is* the cost model.
"""

from __future__ import annotations

import json
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass, field
from pathlib import Path

from jevcut.client import JevClient
from jevcut.config import Config
from jevcut.models import Sentence, Transcript
from jevcut.questions import NO_ANCHOR, scan_questions
from jevcut.render import render_lines

log = logging.getLogger(__name__)


@dataclass(slots=True)
class Window:
    id: int
    sentences: list[Sentence]

    @property
    def line_ids(self) -> list[str]:
        return [s.id for s in self.sentences]


@dataclass(slots=True)
class Anchor:
    sentence_id: str
    window_id: int
    kind: str
    t0: float
    t1: float
    p_moment: float
    anchor_confidence: float
    anchor_probability: float

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(slots=True)
class ScanResult:
    """Pass C's output, carrying enough context to tell a thin scan from a broken one.

    The anchor list alone cannot. Two anchors from a fully scanned video and two from
    the single window that survived while twenty others 5xx'd are the same list, and
    the second is a recall hole wearing the first's clothes -- 003's hardest bug to
    diagnose, because it reads downstream as "the model found nothing here".

    So the counts travel with the anchors, and reach disk. Deciding what to do about a
    partial scan is Pass D's ([006](../../issues/006-pass-d-boundary-refinement.md)),
    which is only possible because the numbers are here to decide on.
    """

    anchors: list[Anchor]
    windows_total: int
    windows_failed: int = 0
    #: One line per failed window, e.g. "window 3: HTTPError: 503". For the log and
    #: the artifact, never for control flow.
    failures: list[str] = field(default_factory=list)

    @property
    def complete(self) -> bool:
        return self.windows_failed == 0

    @property
    def coverage(self) -> float:
        """Fraction of windows that answered. 1.0 when nothing failed."""
        return (
            1.0
            if not self.windows_total
            else (self.windows_total - self.windows_failed) / self.windows_total
        )


def windows(transcript: Transcript, config: Config | None = None) -> list[Window]:
    """Fixed-size windows, stepped so the overlap holds its length in *seconds*.

    The window is sized in sentences because what it bounds is the state Jev reads. The
    step is measured in seconds because what the overlap insures against is a moment
    straddling a boundary, and a moment's length is seconds -- 20 to 90 of them.

    Counted in sentences, the overlap's real length swings with delivery: the same ten
    sentences are a minute of a measured talk and twenty seconds of rapid dialogue. On
    fast speech the insurance silently falls below a clip's length and a straddling
    moment is seen only in halves by both neighbours, nominated by neither -- a recall
    hole that reads as a model error in the traces.
    """
    config = config or Config()
    size = config.window_sentences
    sentences = transcript.sentences
    if not sentences:
        return []

    out: list[Window] = []
    cursor = 0
    while cursor < len(sentences):
        chunk = sentences[cursor : cursor + size]
        out.append(Window(id=len(out), sentences=chunk))
        if cursor + size >= len(sentences):
            break

        # Step back from this window's end by the overlap, in seconds, then convert that
        # instant back to a sentence index. Capped at half the window's own span so a
        # mis-set overlap cannot collapse the step and cost a request per sentence, and
        # floored at one sentence so the loop always advances.
        span = chunk[-1].t1 - chunk[0].t0
        overlap_s = min(config.window_overlap_s, span / 2)
        cursor = max(
            cursor + 1, _first_ending_after(sentences, chunk[-1].t1 - overlap_s, cursor + 1)
        )

    # A short trailing window costs a whole request -- ~250 tokens of fixed overhead
    # before any content -- for a handful of sentences the previous window already
    # overlaps. Fold it back in rather than paying for it.
    if len(out) > 1 and len(out[-1].sentences) < config.min_tail_window:
        tail = out.pop()
        merged = out[-1].sentences + [
            s for s in tail.sentences if s.id not in {x.id for x in out[-1].sentences}
        ]
        out[-1] = Window(id=out[-1].id, sentences=merged)
    return out


def _first_ending_after(sentences: list[Sentence], t: float, lo: int) -> int:
    """Index of the first sentence at or after ``lo`` with any content past ``t``.

    Takes the sentence that straddles ``t`` rather than the one after it: erring wide
    costs a sentence of tokens, erring narrow costs the overlap it was chosen for.
    """
    for i in range(lo, len(sentences)):
        if sentences[i].t1 > t:
            return i
    return len(sentences)


def scan_window(client: JevClient, window: Window, config: Config | None = None) -> list[Anchor]:
    """Ask one window, then repeat with the winner's neighbourhood removed.

    Up to ``max_anchors_per_window``, stopping as soon as ``contains_moment`` says there
    is nothing left worth quoting -- which is what keeps a flat window from costing three
    requests.
    """
    config = config or Config()
    excluded: set[str] = set()
    anchors: list[Anchor] = []

    for _ in range(config.max_anchors_per_window):
        remaining = [s for s in window.sentences if s.id not in excluded]
        if len(remaining) < 2:
            break

        response = client.ask(
            {"window": {"lines": render_lines(remaining).splitlines()}},
            scan_questions([s.id for s in remaining]),
            pass_name="scan",
            meta={"window_id": window.id, "round": len(anchors)},
        )

        answers = response.answers
        if "contains_moment" not in answers or answers["contains_moment"].noul is None:
            # A missing answer is a service or schema problem, not a flat window. Saying
            # so is the difference between "nothing here" and "we never found out".
            log.warning(
                "window %s round %s: no contains_moment in the response (keys: %s)",
                window.id,
                len(anchors),
                sorted(answers),
            )
            break

        p_moment = answers["contains_moment"].noul
        if p_moment < config.contains_moment_threshold:
            break

        choice = answers["anchor"].choice
        if choice == NO_ANCHOR or choice is None:
            break

        sentence = next((s for s in remaining if s.id == choice), None)
        if sentence is None:
            # Jev returned an option we never offered. Issue 010's triage exists to tell
            # this apart from an ordinary miss, which it cannot do if we stay quiet.
            log.warning(
                "window %s round %s: anchor %r is not one of the %s options offered",
                window.id,
                len(anchors),
                choice,
                len(remaining),
            )
            break

        probabilities = answers["anchor"].probabilities or {}
        anchors.append(
            Anchor(
                sentence_id=sentence.id,
                window_id=window.id,
                kind=answers["kind"].choice or "none",
                t0=sentence.t0,
                t1=sentence.t1,
                p_moment=p_moment,
                anchor_confidence=answers["anchor"].confidence or 0.0,
                anchor_probability=probabilities.get(choice, 0.0),
            )
        )

        # Remove the winner's neighbourhood before re-asking, so round two finds a
        # different moment rather than re-electing the same one.
        excluded |= {
            s.id
            for s in window.sentences
            if s.t1 >= sentence.t0 - config.anchor_removal_s
            and s.t0 <= sentence.t1 + config.anchor_removal_s
        }

    return anchors


def dedupe(anchors: list[Anchor], config: Config | None = None) -> list[Anchor]:
    """Collapse anchors the overlap region found twice, keeping the stronger."""
    config = config or Config()
    ordered = sorted(anchors, key=lambda a: (-a.p_moment, -a.anchor_probability))
    kept: list[Anchor] = []
    for a in ordered:
        clash = any(
            a.sentence_id == k.sentence_id or abs(a.t0 - k.t0) < config.anchor_dedupe_s
            for k in kept
        )
        if not clash:
            kept.append(a)
    return sorted(kept, key=lambda a: a.t0)


def scan(client: JevClient, transcript: Transcript, config: Config | None = None) -> ScanResult:
    """Every window in parallel, bounded by the account's request budget.

    Windows are independent, so one failing must not discard the others. ``pool.map``
    re-raises the first worker exception and throws away every result behind it, which
    on a long video means paying for twenty windows and writing no ``anchors.json`` at
    all because the twenty-first hit a 5xx that outlived its retries. Failures are
    collected instead, and returned with the anchors so the caller can actually decide
    whether a partial scan is usable -- a log line alone left that promise unkeepable.
    """
    config = config or Config()
    found = windows(transcript, config)

    anchors: list[Anchor] = []
    failures: list[tuple[int, Exception]] = []

    with ThreadPoolExecutor(max_workers=config.scan_concurrency) as pool:
        futures = {pool.submit(scan_window, client, w, config): w for w in found}
        for future in as_completed(futures):
            window = futures[future]
            try:
                anchors.extend(future.result())
            except Exception as exc:  # noqa: BLE001 - one window must not sink the scan
                failures.append((window.id, exc))
                log.warning("window %s failed: %s: %s", window.id, type(exc).__name__, exc)

    if failures:
        log.warning(
            "%s of %s windows failed; %s anchors kept from the rest",
            len(failures),
            len(found),
            len(anchors),
        )
    return ScanResult(
        anchors=dedupe(anchors, config),
        windows_total=len(found),
        windows_failed=len(failures),
        failures=[f"window {wid}: {type(exc).__name__}: {exc}" for wid, exc in failures],
    )


def write_scan(result: ScanResult, path: str | Path) -> None:
    """Persist a scan. The `scan` header is the point: a bare anchor list on disk
    cannot say whether the video was fully looked at."""
    Path(path).write_text(
        json.dumps(
            {
                "scan": {
                    "windows_total": result.windows_total,
                    "windows_failed": result.windows_failed,
                    "coverage": round(result.coverage, 4),
                    "failures": result.failures,
                },
                "anchors": [a.to_dict() for a in result.anchors],
            },
            indent=2,
        )
    )


def read_scan(path: str | Path) -> ScanResult:
    data = json.loads(Path(path).read_text())
    if isinstance(data, list):
        raise ValueError(
            f"{path} is a bare anchor list with no scan header, so its coverage is "
            "unknown. Re-run the scan rather than assuming it was complete."
        )
    head = data.get("scan", {})
    return ScanResult(
        anchors=[Anchor(**d) for d in data["anchors"]],
        windows_total=head["windows_total"],
        windows_failed=head.get("windows_failed", 0),
        failures=head.get("failures", []),
    )
