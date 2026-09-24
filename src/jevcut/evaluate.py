"""Issue 012 -- score a run's clips against hand labels.

One label file per video (``eval/labels/<id>.json``, issue 011) against the EDL the run
wrote for it. Everything here is arithmetic on spans; no model is involved, so a score is
reproducible from files on disk.

What a number means:

- A predicted clip *matches* a labeled clip when their spans overlap by more than half
  (IoU > 0.5), one to one, best overlaps first.
- ``precision``: predictions matching a labeled clip *or an ``also_ok`` one* /
  predictions. ``recall``: matched labels / labels. ``also_ok`` holds clips an editor
  would accept but not insist on: a labeler cannot list every good stretch of a dense
  hour without padding the required set, and without this list every unlisted good pick
  would count as a false positive.
  Kept apart on purpose: a system that ships fewer, better clips loses recall and is the
  one we want, which a single blended score would hide.
- ``in_range``: a match whose start and end both fall inside the labeler's acceptable
  ranges -- the boundary claim, measured.
- ``negative_rate``: predictions that sit mostly (> half their length) inside a labeled
  hard negative. The only direct measure of whether the gate refuses what it should.
- ``chance_recall``: the same number of clips, of the same lengths, dropped uniformly at
  random on the same video. Recall is only skill to the extent it beats this.

Scored on the measured ``t0``/``t1``, not the render edges (see edl.py): folding the
silence nudge back in would flatter every boundary number.
"""

from __future__ import annotations

import json
import random
import statistics
from dataclasses import dataclass, field
from pathlib import Path

from jevcut.edl import read_edl

#: Overlap above which a prediction counts as the labeled clip (issue 012).
MATCH_IOU = 0.5
#: Random placements averaged for the chance baseline. Seeded, so reruns agree.
CHANCE_TRIALS = 300


def iou(a: tuple[float, float], b: tuple[float, float]) -> float:
    inter = max(0.0, min(a[1], b[1]) - max(a[0], b[0]))
    union = max(a[1], b[1]) - min(a[0], b[0])
    return inter / union if union > 0 else 0.0


def match(
    predicted: list[tuple[float, float]], labeled: list[tuple[float, float]]
) -> list[tuple[int, int]]:
    """One-to-one ``(pred_index, label_index)`` pairs with IoU > MATCH_IOU, best first."""
    pairs = sorted(
        (
            (iou(p, g), i, j)
            for i, p in enumerate(predicted)
            for j, g in enumerate(labeled)
            if iou(p, g) > MATCH_IOU
        ),
        reverse=True,
    )
    used_p: set[int] = set()
    used_g: set[int] = set()
    out = []
    for _, i, j in pairs:
        if i not in used_p and j not in used_g:
            used_p.add(i)
            used_g.add(j)
            out.append((i, j))
    return out


def chance_recall(
    lengths: list[float], labeled: list[tuple[float, float]], duration: float, seed: int = 0
) -> float:
    """Mean recall of ``len(lengths)`` clips of those lengths placed uniformly at random."""
    if not lengths or not labeled or duration <= 0:
        return 0.0
    rng = random.Random(seed)
    total = 0.0
    for _ in range(CHANCE_TRIALS):
        spans = []
        for length in lengths:
            t0 = rng.uniform(0.0, max(duration - length, 0.0))
            spans.append((t0, t0 + length))
        total += len(match(spans, labeled)) / len(labeled)
    return total / CHANCE_TRIALS


@dataclass
class VideoScore:
    video: str
    genre: str
    predicted: int
    labeled: int
    matched: int
    #: Predictions that missed every required clip but match an ``also_ok`` one.
    acceptable: int
    in_range: int
    on_negative: int
    chance_recall: float
    start_errors: list[float] = field(default_factory=list)
    end_errors: list[float] = field(default_factory=list)
    #: Label ids that no prediction matched, for reading the misses rather than counting.
    missed: list[str] = field(default_factory=list)

    @property
    def precision(self) -> float:
        return (self.matched + self.acceptable) / self.predicted if self.predicted else 0.0

    @property
    def recall(self) -> float:
        return self.matched / self.labeled if self.labeled else 0.0


def _inside(t: float, rng: list[float]) -> bool:
    return rng[0] <= t <= rng[1]


def score_video(label: dict, edl_path: str | Path) -> VideoScore:
    _, clips = read_edl(edl_path)
    predicted = [(c.t0, c.t1) for c in clips]
    gold = label["clips"]
    labeled = [(g["start"], g["end"]) for g in gold]

    pairs = match(predicted, labeled)
    in_range = sum(
        1
        for i, j in pairs
        if _inside(predicted[i][0], gold[j]["start_range"])
        and _inside(predicted[i][1], gold[j]["end_range"])
    )
    on_negative = sum(
        1
        for p in predicted
        if any(
            min(p[1], n["end"]) - max(p[0], n["start"]) > (p[1] - p[0]) / 2
            for n in label.get("negatives", [])
        )
    )
    matched_labels = {j for _, j in pairs}
    rest = [p for i, p in enumerate(predicted) if i not in {i for i, _ in pairs}]
    acceptable = len(match(rest, [(a["start"], a["end"]) for a in label.get("also_ok", [])]))
    return VideoScore(
        video=label["video"]["url"],
        genre=label["video"].get("genre", "unknown"),
        predicted=len(predicted),
        labeled=len(labeled),
        matched=len(pairs),
        acceptable=acceptable,
        in_range=in_range,
        on_negative=on_negative,
        chance_recall=chance_recall(
            [p[1] - p[0] for p in predicted], labeled, label["video"]["duration_s"]
        ),
        start_errors=[abs(predicted[i][0] - labeled[j][0]) for i, j in pairs],
        end_errors=[abs(predicted[i][1] - labeled[j][1]) for i, j in pairs],
        missed=[g["id"] for j, g in enumerate(gold) if j not in matched_labels],
    )


def edl_for(label: dict, suffix: str = "-clips") -> Path:
    """Where a run of ``jevcut run <local_path> --out <stem><suffix>`` left its EDL."""
    media = Path(label["video"]["local_path"])
    return media.with_name(media.stem + suffix) / "edl.json"


def score_set(labels_dir: str | Path, suffix: str = "-clips") -> tuple[list[VideoScore], list[str]]:
    """Score every labeled video that has a run; return the scores and what was skipped."""
    scores, skipped = [], []
    for path in sorted(Path(labels_dir).glob("*.json")):
        label = json.loads(path.read_text())
        edl = edl_for(label, suffix)
        if not edl.exists():
            skipped.append(f"{path.name}: no run at {edl}")
            continue
        scores.append(score_video(label, edl))
    return scores, skipped


def _median(xs: list[float]) -> float | None:
    return statistics.median(xs) if xs else None


def summary(scores: list[VideoScore]) -> dict:
    """Pooled over clips, not averaged over videos: a 97-minute debate with twelve labels
    should weigh more than an 8-minute review with two."""
    pred = sum(s.predicted for s in scores)
    lab = sum(s.labeled for s in scores)
    matched = sum(s.matched for s in scores)
    acceptable = sum(s.acceptable for s in scores)
    starts = [e for s in scores for e in s.start_errors]
    ends = [e for s in scores for e in s.end_errors]
    return {
        "videos": len(scores),
        "predicted": pred,
        "labeled": lab,
        "matched": matched,
        "acceptable": acceptable,
        "precision": (matched + acceptable) / pred if pred else 0.0,
        "recall": matched / lab if lab else 0.0,
        "chance_recall": (sum(s.chance_recall * s.labeled for s in scores) / lab if lab else 0.0),
        "in_range_rate": sum(s.in_range for s in scores) / matched if matched else 0.0,
        "negative_rate": sum(s.on_negative for s in scores) / pred if pred else 0.0,
        "start_err_median": _median(starts),
        "end_err_median": _median(ends),
    }


def agreement(a: dict, b: dict) -> dict:
    """How far two independent labelers of one video agree: the noise floor (issue 011).

    Their required clips are matched one to one like predictions (IoU > 0.5). ``agree_a``
    and ``agree_b`` are the share of each labeler's clips the other also picked, and the
    edge deltas are over matched pairs: a system cannot be asked to put an edge closer to
    a label than a second careful labeler does.
    """
    ga = [(c["start"], c["end"]) for c in a["clips"]]
    gb = [(c["start"], c["end"]) for c in b["clips"]]
    pairs = match(ga, gb)
    return {
        "a": len(ga),
        "b": len(gb),
        "matched": len(pairs),
        "agree_a": len(pairs) / len(ga) if ga else 0.0,
        "agree_b": len(pairs) / len(gb) if gb else 0.0,
        "start_deltas": [abs(ga[i][0] - gb[j][0]) for i, j in pairs],
        "end_deltas": [abs(ga[i][1] - gb[j][1]) for i, j in pairs],
    }
