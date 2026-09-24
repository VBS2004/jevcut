"""Why does the scan never anchor half the labeled moments?

On the rubric-v2 labels the scan puts an anchor inside only 52-58% of labeled clips, on
Whisper small and Lemonfox transcripts alike, and an unanchored moment is a guaranteed
miss (RESEARCH.md, "The gate, judged on the labelers' own clips"). Before changing the
scan, find out which of its stopping rules loses them.

Every window is replayed from the response cache (no requests) with each round recorded,
and every unanchored labeled clip is put in the first bucket that explains it:

* **deduped** -- a window did anchor inside the clip, and the cross-window dedupe dropped it
  for a stronger anchor nearby.
* **near** -- a final anchor sits within NEAR_S of the clip but outside it: the scan found
  the moment and pointed at a line next to it.
* **rounds spent** -- a window covering the clip used all its rounds on other moments.
* **none of these** -- a covering window stopped because "none of these" outweighed the
  strongest stretch.
* **flat** -- every covering window stopped because `contains_moment` fell below the
  threshold before reaching the clip.

For each, the vote the clip's own lines got in the first round of its best covering window
says whether the model saw it at all.

    uv run python eval/experiments/scan_misses.py
"""

from __future__ import annotations

import json
import statistics as st
import sys
from collections import Counter, defaultdict
from dataclasses import replace
from pathlib import Path

from jevcut.backends import load_env
from jevcut.client import JevClient
from jevcut.config import Config
from jevcut.models import Transcript
from jevcut.questions import NO_ANCHOR
from jevcut.scan import dedupe, scan_window, windows

NEAR_S = 15.0
RUNS = (
    ("whisper small", "eval/media/{stem}-clips/transcript.json"),
    ("lemonfox", "eval/media/asr-lemonfox/{stem}.json"),
)
LABELS = ("eval/labels-v2", "eval/labels-v2-b")
ORDER = ("deduped", "near", "rounds spent", "none of these", "flat", "no window")


class Recorder:
    """Passes every request to the cached client and keeps what came back, per window."""

    def __init__(self, client: JevClient):
        self.client, self.rounds = client, defaultdict(list)

    def ask(self, state, questions, *, pass_name, meta=None):
        response = self.client.ask(state, questions, pass_name=pass_name, meta=meta)
        a = response.answers
        self.rounds[meta["window_id"]].append(
            {
                "p_moment": a["contains_moment"].noul,
                "probabilities": a["anchor"].probabilities or {},
            }
        )
        return response


def diagnose(transcript: Transcript, config: Config, client: JevClient):
    """Replay every window; return per-window records and the final anchors."""
    recorder = Recorder(client)
    per_window, raw = [], []
    for w in windows(transcript, config):
        found = scan_window(recorder, w, config)
        raw += found
        rounds = recorder.rounds[w.id]
        last = rounds[-1] if rounds else None
        if len(found) >= config.max_anchors_per_window:
            stop = "rounds spent"
        elif last is None or last["p_moment"] < config.contains_moment_threshold:
            stop = "flat"
        elif last["probabilities"].get(NO_ANCHOR, 0.0) > 0:
            stop = "none of these"
        else:
            stop = "exhausted"
        per_window.append(
            {
                "t0": w.sentences[0].t0,
                "t1": w.sentences[-1].t1,
                "ids": {s.id: s for s in w.sentences},
                "rounds": rounds,
                "anchors": found,
                "stop": stop,
            }
        )
    return per_window, raw, dedupe(raw, config)


def main() -> None:
    load_env()
    config = replace(Config(), cache_mode="replay")
    labels = defaultdict(dict)  # stem -> label dir -> label
    for d in LABELS:
        for f in sorted(Path(d).glob("*.json")):
            label = json.loads(f.read_text())
            labels[Path(label["video"]["local_path"]).stem][d] = label

    for name, pattern in RUNS:
        buckets, votes, stops = Counter(), defaultdict(list), Counter()
        total = unanchored = 0
        with JevClient(replace(config, max_requests_per_video=10_000)) as client:
            for stem, by_dir in sorted(labels.items()):
                transcript = Transcript.from_json(pattern.format(stem=stem))
                per_window, raw, final = diagnose(transcript, config, client)
                stops.update(w["stop"] for w in per_window)
                for label in by_dir.values():
                    for g in label["clips"]:
                        total += 1
                        inside = [a for a in final if g["start"] - 1 <= a.t0 <= g["end"]]
                        if inside:
                            continue
                        unanchored += 1
                        covering = [
                            w for w in per_window if w["t0"] <= g["start"] and g["end"] <= w["t1"]
                        ] or [w for w in per_window if w["t0"] < g["end"] and g["start"] < w["t1"]]
                        if any(g["start"] - 1 <= a.t0 <= g["end"] for a in raw):
                            bucket = "deduped"
                        elif any(g["start"] - NEAR_S <= a.t0 <= g["end"] + NEAR_S for a in final):
                            bucket = "near"
                        elif not covering:
                            bucket = "no window"
                        elif any(w["stop"] == "rounds spent" for w in covering):
                            bucket = "rounds spent"
                        elif any(w["stop"] == "none of these" for w in covering):
                            bucket = "none of these"
                        else:
                            bucket = "flat"
                        buckets[bucket] += 1
                        # The vote the clip's own lines got in round one, best covering window.
                        mass = 0.0
                        for w in covering:
                            if not w["rounds"]:
                                continue
                            p = w["rounds"][0]["probabilities"]
                            mine = [
                                sid
                                for sid, s in w["ids"].items()
                                if g["start"] - 1 <= s.t0 and s.t1 <= g["end"] + 1
                            ]
                            mass = max(mass, sum(p.get(sid, 0.0) for sid in mine))
                        votes[bucket].append(mass)

        print(f"== {name}: {unanchored} of {total} labeled clips (v2 A + B) have no anchor inside")
        for b in ORDER:
            if buckets[b]:
                v = votes[b]
                print(
                    f"  {b:14} {buckets[b]:3}   round-1 vote on the clip's lines: "
                    f"median {st.median(v):.2f}, zero in {sum(x < 0.01 for x in v)}"
                )
        print(f"  windows stopped by: {dict(stops)}\n")


if __name__ == "__main__":
    sys.exit(main())
