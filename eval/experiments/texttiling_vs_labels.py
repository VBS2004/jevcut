"""Does classical topic segmentation put a boundary where a human did?

Run once, 2026-09-21, to answer RESEARCH.md failure mode 4 ("classical methods
already solve it"). Answer: not at clip granularity. See docs/PRIOR-ART.md.

Ground truth is SponsorBlock's labels on 20 real YouTube transcripts -- 336
minutes of speech, 48 human-placed boundaries. A sponsor read starts where the
creator leaves the subject of the video, so its start is a topic boundary a
person chose and timestamped. It is the only such corpus available before 011.

**The control that matters.** Recall alone tells you nothing about a segmenter:
a method that emits enough boundaries hits every label by luck. Every recall
number here is paired with the rate achieved by scattering the SAME NUMBER of
boundaries at random over the same video. That pairing is the whole experiment
-- without it TextTiling looks like it works.

Needs a corpus and two packages this project does not depend on:

    git clone https://github.com/trungdq88/youtube-sponsor-detection
    pip install nltk numpy
    python -c "import nltk; nltk.download('stopwords')"
    python eval/experiments/texttiling_vs_labels.py <path-to-that-repo>
"""

from __future__ import annotations

import glob
import json
import os
import random
import statistics as st
import sys

from nltk.tokenize.texttiling import TextTilingTokenizer

TOLERANCES = [1, 2, 5, 10, 15, 30]
#: (pseudosentence size, block size). The first is TextTiling's default.
PARAMS = [(20, 10), (10, 6), (30, 15), (50, 20)]
CHANCE_TRIALS = 200
SEED = 7


def load_labels(repo: str) -> dict:
    out: dict = {}
    for name in ("eval/videos.seed.json", "eval/videos.json"):
        path = os.path.join(repo, name)
        if os.path.exists(path):
            for v in json.load(open(path))["videos"]:
                out.setdefault(v["videoID"], v)
    return out


def build_text(cues: list[dict]) -> tuple[str, list[tuple[int, float]]]:
    """Cues joined with blank lines, plus a char-offset -> seconds map.

    TextTiling snaps every boundary to the nearest paragraph break and a
    transcript has none, so one is synthesised per caption cue. Without this it
    returns the whole video as a single segment. It is also the experiment's
    biggest caveat: different paragraphing would move the results.
    """
    parts: list[str] = []
    offsets: list[tuple[int, float]] = []
    pos = 0
    for cue in cues:
        text = " ".join(cue["text"].split())
        if not text:
            continue
        parts.append(text)
        offsets.append((pos, cue["startMs"] / 1000))
        pos += len(text) + 2  # the "\n\n" joiner
    return "\n\n".join(parts), offsets


def offset_to_time(offset: int, offsets: list[tuple[int, float]]) -> float:
    best = offsets[0][1]
    for at, t in offsets:
        if at > offset:
            break
        best = t
    return best


def nearest(targets: list[float], marks: list[float]) -> list[float]:
    return [min((abs(t - m) for m in marks), default=float("inf")) for t in targets]


def load_docs(repo: str):
    labels = load_labels(repo)
    for path in sorted(glob.glob(os.path.join(repo, "eval/transcripts/*.json"))):
        data = json.load(open(path))
        vid = data["videoID"]
        if vid not in labels:
            continue
        cues = [c for c in data["cues"] if c["text"].strip()]
        if not cues:
            continue
        text, offsets = build_text(cues)
        truth = [s["start"] for s in labels[vid]["segments"]]
        yield vid, cues, text, offsets, cues[-1]["endMs"] / 1000, truth


def texttiling(docs) -> None:
    """Recall against chance at the same boundary density, per parameter set."""
    print("TextTiling vs 48 human-placed boundaries\n")
    header = "".join(f"{'@' + str(t) + 's':>16}" for t in TOLERANCES)
    print(f"{'params':>12}{'bounds':>8}{'/min':>7}   {header}")
    print(f"{'':>27}   " + "".join(f"{'recall / chance':>16}" for _ in TOLERANCES))

    for w, k in PARAMS:
        rng = random.Random(SEED)
        tt = TextTilingTokenizer(w=w, k=k)
        hits = {t: 0 for t in TOLERANCES}
        chance = {t: 0.0 for t in TOLERANCES}
        n_truth = n_bounds = 0
        duration = 0.0
        deltas: list[float] = []

        for _vid, _cues, text, offsets, dur, truth in docs:
            try:
                segments = tt.tokenize(text)
            except Exception as exc:  # noqa: BLE001 - one video must not sink the run
                print(f"  skipped a video: {exc}")
                continue
            bounds, pos = [], 0
            for seg in segments[:-1]:
                pos += len(seg)
                bounds.append(offset_to_time(pos, offsets))

            n_bounds += len(bounds)
            n_truth += len(truth)
            duration += dur

            for delta in nearest(truth, bounds):
                deltas.append(delta)
                for tol in TOLERANCES:
                    hits[tol] += delta <= tol
            for _ in range(CHANCE_TRIALS):
                shuffled = [rng.uniform(0, dur) for _ in range(max(len(bounds), 1))]
                for delta in nearest(truth, shuffled):
                    for tol in TOLERANCES:
                        chance[tol] += (delta <= tol) / CHANCE_TRIALS

        cells = "".join(
            f"{hits[t] / n_truth * 100:6.0f}% /{chance[t] / n_truth * 100:5.0f}%"
            for t in TOLERANCES
        )
        print(f"  w={w:<3} k={k:<3}{n_bounds:8}{n_bounds / (duration / 60):7.2f}   {cells}")
        if (w, k) == PARAMS[0]:
            print(
                f"{'':>27}   median |delta| {st.median(deltas):.1f}s, "
                f"precision <= {n_truth}/{n_bounds} = {n_truth / n_bounds * 100:.1f}%"
            )


def candidate_recall(docs) -> None:
    """The other classical method: snap to a fine-grained boundary.

    This is what autoclip and Baseline 4 (issue 013) do, and it is issue 003's
    coverage criterion measured on real speech for the first time.
    """
    tols = [0.5, 1.0, 2.0, 5.0]
    hits = {t: 0 for t in tols}
    deltas: list[float] = []
    n = count = 0
    duration = 0.0

    for _vid, cues, _text, _offsets, dur, truth in docs:
        marks = [c["startMs"] / 1000 for c in cues]
        count += len(marks)
        duration += dur
        for t0 in truth:
            n += 1
            delta = min((abs(t0 - m) for m in marks), default=float("inf"))
            deltas.append(delta)
            for tol in tols:
                hits[tol] += delta <= tol

    print("\n\nCaption-cue boundaries vs the same 48 labels\n")
    head = "".join(f"{'within ' + str(t) + 's':>14}" for t in tols)
    print(f"{'count':>8}{'/min':>7}{'median':>9}   {head}")
    cells = "".join(f"{hits[t] / n * 100:13.0f}%" for t in tols)
    print(f"{count:8}{count / (duration / 60):7.1f}{st.median(deltas):8.1f}s   {cells}")
    print("\nIssue 003 requires a candidate within 1.0s of >=95% of human starts.")


def main() -> None:
    repo = sys.argv[1] if len(sys.argv) > 1 else os.path.expanduser("~/youtube-sponsor-detection")
    if not os.path.isdir(os.path.join(repo, "eval/transcripts")):
        sys.exit(f"no eval/transcripts under {repo}; see this file's docstring")
    docs = list(load_docs(repo))
    print(
        f"{len(docs)} videos, {sum(d[4] for d in docs) / 60:.0f} min, "
        f"{sum(len(d[5]) for d in docs)} labels\n"
    )
    texttiling(docs)
    candidate_recall(docs)


if __name__ == "__main__":
    main()
