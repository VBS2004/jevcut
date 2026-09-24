"""Issue 003's coverage gate, against human topic boundaries in real speech.

Run 2026-09-22. Result and caveats in docs/PRIOR-ART.md and issue 003.

The AMI Meeting Corpus carries manual topic segmentation over 139 meetings, with
word-level timings and punctuation. Boundaries are stand-off references to word
ID ranges, so they resolve to seconds exactly. That makes it the only human
boundary set in *speech* available before issue 011 produces one.

**What it can and cannot answer.** A topic boundary is "the subject changed",
not "this self-contained thought starts here". So this measures whether the
candidate list *contains* the right cut -- 003's gate -- and nothing about
whether a moment was worth clipping. It is a proxy, and it does not replace 011.

Annotations only, no media (22 MB), CC BY 4.0:

    curl -sLO https://groups.inf.ed.ac.uk/ami/AMICorpusAnnotations/ami_public_manual_1.6.2.zip
    mkdir -p ami && unzip -q ami_public_manual_1.6.2.zip -d ami
    python eval/experiments/ami_coverage.py ./ami
"""

from __future__ import annotations

import glob
import re
import statistics as st
import sys
from xml.etree import ElementTree as ET

from jevcut import cuts as cuts_mod
from jevcut.models import Transcript, Word
from jevcut.transcript import segment_words

NITE = "{http://nite.sourceforge.net/}"
TOLERANCES = [0.5, 1.0, 2.0, 2.5, 5.0]
#: The tolerance 003 gates on, and the band the kind breakdown is taken at.
GATE_S = 2.0


def words_of(root: str, meeting: str) -> tuple[list[Word], dict[str, float]]:
    """Every speaker merged into one time-ordered stream, plus an id -> start map.

    The map has to include untimed-in-text entries like punctuation, because a
    topic's first child can point at one.
    """
    words: list[Word] = []
    times: dict[str, float] = {}
    for path in glob.glob(f"{root}/words/{meeting}.*.words.xml"):
        speaker = path.split("/")[-1].split(".")[1]
        for w in ET.parse(path).getroot():
            start, end = w.get("starttime"), w.get("endtime")
            if start is None or end is None:
                continue  # <vocalsound>, <gap> and friends carry no time
            t0, t1 = float(start), float(end)
            times[w.get(f"{NITE}id")] = t0
            if w.tag == "w" and w.text:
                words.append(Word(text=w.text, t0=t0, t1=max(t1, t0), speaker=speaker))
    words.sort(key=lambda w: w.t0)
    return words, times


def topic_starts(root: str, meeting: str, times: dict[str, float]) -> list[float]:
    """Top-level topic start times. Subtopics are skipped: they are a finer
    decomposition of the same segment, not additional boundaries."""
    starts = []
    for topic in ET.parse(f"{root}/topics/{meeting}.topic.xml").getroot():
        if topic.tag != "topic":
            continue
        seen = [
            times[wid]
            for child in topic.iter(f"{NITE}child")
            for wid in re.findall(r"id\(([^)]+)\)", child.get("href") or "")
            if wid in times
        ]
        if seen:
            starts.append(min(seen))
    return sorted(starts)


def main() -> None:
    root = sys.argv[1] if len(sys.argv) > 1 else "./ami"
    meetings = sorted(
        f.split("/")[-1].split(".")[0] for f in glob.glob(f"{root}/topics/*.topic.xml")
    )
    if not meetings:
        sys.exit(f"no topics/*.topic.xml under {root}; see this file's docstring")

    hits = {t: 0 for t in TOLERANCES}
    by_kind: dict[str, int] = {}
    deltas: list[float] = []
    n = candidates = scored = 0
    hours = 0.0

    for meeting in meetings:
        words, times = words_of(root, meeting)
        if len(words) < 50:
            continue
        starts = topic_starts(root, meeting, times)
        if len(starts) < 2:
            continue
        sentences = segment_words(words)
        transcript = Transcript(sentences=sentences, duration=sentences[-1].t1)
        cuts = cuts_mod.extract(transcript)

        scored += 1
        candidates += len(cuts)
        hours += transcript.duration
        # The first topic is the meeting opening at t~0, which every system gets free.
        for target in starts[1:]:
            n += 1
            nearest = min(cuts, key=lambda c: abs(target - c.t_start))
            delta = abs(target - nearest.t_start)
            deltas.append(delta)
            if delta <= GATE_S:
                by_kind[nearest.kind] = by_kind.get(nearest.kind, 0) + 1
            for tol in TOLERANCES:
                hits[tol] += delta <= tol

    print(f"\n{scored} meetings, {hours / 3600:.1f} h, {n} human topic boundaries")
    print(f"candidates: {candidates} ({candidates / (hours / 60):.1f}/min)\n")
    print(f"{'tolerance':>10}{'covered':>10}")
    for tol in TOLERANCES:
        print(f"{tol:9.1f}s{hits[tol] / n * 100:9.0f}%")

    print(f"\nwhich kind covered the boundary (within {GATE_S}s):")
    for kind, count in sorted(by_kind.items(), key=lambda kv: -kv[1]):
        print(f"   {kind:16}{count:6}{count / n * 100:6.0f}%")
    print("\nA kind at 0% is out-ranked, not useless: merging keeps the strongest kind")
    print("within 200ms, so a pause on a speaker change is relabelled as one.")

    ordered = sorted(deltas)
    print(
        f"\nmedian {st.median(ordered):.2f}s  "
        f"p90 {ordered[int(len(ordered) * 0.9)]:.2f}s  max {ordered[-1]:.0f}s"
    )


if __name__ == "__main__":
    main()
