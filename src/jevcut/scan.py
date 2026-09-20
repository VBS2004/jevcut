"""Issue 005 -- Pass C: the coarse scan for anchors.

The cheap half of the cascade. One request per 80-sentence window finds the lines worth
spending real money on; everything downstream costs two more requests per survivor, so
this gate's threshold *is* the cost model.
"""

from __future__ import annotations

import json
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass
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


def windows(transcript: Transcript, config: Config | None = None) -> list[Window]:
    """Fixed-size windows with overlap, so a moment straddling a boundary isn't lost
    by both sides."""
    config = config or Config()
    size, overlap = config.window_sentences, config.window_overlap
    step = max(size - overlap, 1)
    sentences = transcript.sentences

    out: list[Window] = []
    for i, start in enumerate(range(0, max(len(sentences), 1), step)):
        chunk = sentences[start : start + size]
        if not chunk:
            break
        out.append(Window(id=i, sentences=chunk))
        if start + size >= len(sentences):
            break

    # A short trailing window costs a whole request -- ~250 tokens of fixed overhead
    # before any content -- for a handful of sentences the previous window already
    # overlaps. Fold it back in rather than paying for it.
    if len(out) > 1 and len(out[-1].sentences) < config.min_tail_window:
        tail = out.pop()
        merged = out[-1].sentences + [s for s in tail.sentences if s.id not in {x.id for x in out[-1].sentences}]
        out[-1] = Window(id=out[-1].id, sentences=merged)
    return out


def scan_window(
    client: JevClient, window: Window, config: Config | None = None
) -> list[Anchor]:
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
                window.id, len(anchors), sorted(answers),
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
                window.id, len(anchors), choice, len(remaining),
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
            a.sentence_id == k.sentence_id
            or abs(a.t0 - k.t0) < config.anchor_dedupe_s
            for k in kept
        )
        if not clash:
            kept.append(a)
    return sorted(kept, key=lambda a: a.t0)


def scan(
    client: JevClient, transcript: Transcript, config: Config | None = None
) -> list[Anchor]:
    """Every window in parallel, bounded by the account's request budget.

    Windows are independent, so one failing must not discard the others. ``pool.map``
    re-raises the first worker exception and throws away every result behind it, which
    on a long video means paying for twenty windows and writing no ``anchors.json`` at
    all because the twenty-first hit a 5xx that outlived its retries. Failures are
    collected and logged instead; the caller decides whether a partial scan is usable.
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
            len(failures), len(found), len(anchors),
        )
    return dedupe(anchors, config)


def write_anchors(anchors: list[Anchor], path: str | Path) -> None:
    Path(path).write_text(json.dumps([a.to_dict() for a in anchors], indent=2))


def read_anchors(path: str | Path) -> list[Anchor]:
    return [Anchor(**d) for d in json.loads(Path(path).read_text())]
