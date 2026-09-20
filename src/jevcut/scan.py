"""Issue 005 -- Pass C: the coarse scan for anchors.

The cheap half of the cascade. One request per 80-sentence window finds the lines worth
spending real money on; everything downstream costs two more requests per survivor, so
this gate's threshold *is* the cost model.
"""

from __future__ import annotations

import json
import threading
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass
from pathlib import Path

from jevcut.client import JevClient
from jevcut.config import Config
from jevcut.models import Sentence, Transcript
from jevcut.questions import NO_ANCHOR, scan_questions
from jevcut.render import render_lines


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
        p_moment = answers["contains_moment"].noul or 0.0
        if p_moment < config.contains_moment_threshold:
            break

        choice = answers["anchor"].choice
        if choice == NO_ANCHOR or choice is None:
            break

        sentence = next((s for s in remaining if s.id == choice), None)
        if sentence is None:  # option outside the list we offered; log and stop
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
            or abs(a.t0 - k.t0) < config.anchor_removal_s
            for k in kept
        )
        if not clash:
            kept.append(a)
    return sorted(kept, key=lambda a: a.t0)


def scan(
    client: JevClient, transcript: Transcript, config: Config | None = None
) -> list[Anchor]:
    """Every window in parallel, bounded by the account's request budget."""
    config = config or Config()
    found = windows(transcript, config)

    with ThreadPoolExecutor(max_workers=config.scan_concurrency) as pool:
        results = list(pool.map(lambda w: scan_window(client, w, config), found))

    return dedupe([a for group in results for a in group], config)


def write_anchors(anchors: list[Anchor], path: str | Path) -> None:
    Path(path).write_text(json.dumps([a.to_dict() for a in anchors], indent=2))


def read_anchors(path: str | Path) -> list[Anchor]:
    return [Anchor(**d) for d in json.loads(Path(path).read_text())]
