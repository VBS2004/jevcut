"""Core data types.

Everything the model ever sees is text addressed by an ID: sentences are ``L042``,
cut points are ``C07``. Jev returns an ID, code maps it back to a timestamp. Jev never
sees a number it would have to reason about.
"""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field
from pathlib import Path

# Which kind label survives when two candidates land within the merge window. This is
# about naming the strongest physical signal present, not about which cut to prefer --
# see CUT_THIN_WEIGHT in cuts.py, which orders them differently and for a different reason.
# "edge" is the very start and end of the transcript: not a physical signal, but a
# boundary that must always be offered, so it outranks everything for labelling too.
CUT_KIND_PRIORITY = {"edge": 4, "shot": 3, "speaker_change": 2, "sentence_end": 1, "pause": 0}


@dataclass(frozen=True, slots=True)
class Word:
    text: str
    t0: float
    t1: float
    speaker: str | None = None


@dataclass(slots=True)
class Sentence:
    id: str
    text: str
    t0: float
    t1: float
    words: list[Word] = field(default_factory=list)
    speaker: str | None = None

    @property
    def duration(self) -> float:
        return self.t1 - self.t0


@dataclass(frozen=True, slots=True)
class CutPoint:
    """A candidate boundary -- a *gap* between speech, not an instant.

    ``t`` is the midpoint of that gap: one representative number for ordering,
    merging, thinning and spacing, which is all those need.

    Every other consumer wants the gap's edge, chosen by the role the cut ends up
    playing, because a midpoint reports a *correct* choice as wrong by half the gap.
    Humans label a clip start just before the first word, so on a 2s pause a perfect
    pick measures 1.0s early -- systematically, always in the same direction, and worst
    at the long gaps where clip boundaries actually sit. That error lands straight on
    ``start_err_p90`` (issue 013's ship criterion) and on ``cuts.coverage``.

    A cut with no measurable gap (``shot``, ``edge``) is already word-anchored, and all
    three values collapse to ``t``.
    """

    id: str
    t: float
    kind: str
    gap_ms: float = 0.0

    @property
    def t_start(self) -> float:
        """Used as a clip START: where the next word begins."""
        return self.t + self.gap_ms / 2000.0

    @property
    def t_end(self) -> float:
        """Used as a clip END: where the previous word ended."""
        return self.t - self.gap_ms / 2000.0


@dataclass(slots=True)
class Transcript:
    sentences: list[Sentence]
    source: str = ""
    duration: float = 0.0

    def __len__(self) -> int:
        return len(self.sentences)

    def by_id(self, sentence_id: str) -> Sentence:
        for s in self.sentences:
            if s.id == sentence_id:
                return s
        raise KeyError(sentence_id)

    def between(self, t0: float, t1: float) -> list[Sentence]:
        """Sentences overlapping [t0, t1]."""
        return [s for s in self.sentences if s.t1 >= t0 and s.t0 <= t1]

    def to_json(self, path: str | Path) -> None:
        """Written to a temporary file and renamed into place: a run killed mid-write leaves
        the old transcript or none, never an empty file a later run would try to reuse."""
        path = Path(path)
        tmp = path.with_name(path.name + ".tmp")
        tmp.write_text(json.dumps(self.to_dict(), indent=2, ensure_ascii=False))
        os.replace(tmp, path)

    def to_dict(self) -> dict:
        return {
            "source": self.source,
            "duration": self.duration,
            "sentences": [asdict(s) for s in self.sentences],
        }

    @classmethod
    def from_dict(cls, d: dict) -> Transcript:
        sentences = [
            Sentence(
                id=s["id"],
                text=s["text"],
                t0=s["t0"],
                t1=s["t1"],
                words=[Word(**w) for w in s.get("words", [])],
                speaker=s.get("speaker"),
            )
            for s in d["sentences"]
        ]
        return cls(sentences=sentences, source=d.get("source", ""), duration=d.get("duration", 0.0))

    @classmethod
    def from_json(cls, path: str | Path) -> Transcript:
        return cls.from_dict(json.loads(Path(path).read_text()))


@dataclass(slots=True)
class Region:
    """A window around an anchor, with its own locally-numbered cut points.

    Cut IDs are local to the region so the option list Jev sees is short and starts at
    C01. ``cuts_by_id`` is how code maps an answer back to a real timestamp.
    """

    anchor_id: str
    t0: float
    t1: float
    sentences: list[Sentence]
    cuts: list[CutPoint]
    text: str = ""

    @property
    def cuts_by_id(self) -> dict[str, CutPoint]:
        return {c.id: c for c in self.cuts}

    def cuts_before(self, t: float) -> list[CutPoint]:
        return [c for c in self.cuts if c.t < t]

    def cuts_after(self, t: float) -> list[CutPoint]:
        return [c for c in self.cuts if c.t > t]
