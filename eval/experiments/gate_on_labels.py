"""Do the gate's questions pass what labelers ship and fail what they reject?

Every clip the rubric-v2 labelers marked -- required, also_ok, and hard negatives -- is
cut from the transcript at the labeled edges and judged exactly as the search judges a
finished clip (`gate.verify`, `gate.verdict`). A labeled clip is the best cut two blind
labelers found, so the gate should pass it; a hard negative sounds clippable and is not,
so the gate should fail it. The gap between the two, per question, is how much each
question actually tells them apart.

Why now: after the opening Choice, 35 of 47 drops are the gate calling the chosen
opening mid-thought, and recall fell. If the gate also fails labeled clips, the veto is
costing real moments and the question -- not the opening -- is what to fix.

The text is cut on word times, not sentences: labels may start or end inside an ASR line.

    uv run python eval/experiments/gate_on_labels.py [label dirs...]
"""

from __future__ import annotations

import json
import statistics as st
import sys
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path

from jevcut import gate as gate_mod
from jevcut.backends import load_env
from jevcut.client import JevClient
from jevcut.config import Config
from jevcut.models import Transcript

KINDS = (("clip", "clips"), ("also_ok", "also_ok"), ("negative", "negatives"))
NOULS = ("needs_the_room", "starts_mid_thought", "dangling_reference", "ends_mid_thought")
POSITIVE = ("standalone", "hook", "payoff")  # high is good


def words_between(transcript: Transcript, t0: float, t1: float) -> str:
    words = [
        w.text
        for s in transcript.sentences
        for w in s.words
        if w.t0 >= t0 - 0.05 and w.t1 <= t1 + 0.05
    ]
    return " ".join(words)


def auc(pos: list[float], neg: list[float]) -> float:
    """P(a random labeled clip scores above a random negative); 0.5 is no separation."""
    if not pos or not neg:
        return float("nan")
    wins = sum((p > n) + 0.5 * (p == n) for p in pos for n in neg)
    return wins / (len(pos) * len(neg))


def main(label_dirs: list[str]) -> None:
    load_env()
    config = replace(Config(), cache_mode="live")
    items = []  # (label_dir, kind, video, id, text)
    for d in label_dirs:
        for f in sorted(Path(d).glob("*.json")):
            label = json.loads(f.read_text())
            media = Path(label["video"]["local_path"])
            transcript = Transcript.from_json(
                media.with_name(media.stem + "-clips") / "transcript.json"
            )
            for kind, key in KINDS:
                for i, g in enumerate(label.get(key, [])):
                    text = words_between(transcript, g["start"], g["end"])
                    items.append((d, kind, media.stem, g.get("id", f"neg{i}"), text))

    with JevClient(replace(config, max_requests_per_video=10_000)) as client:

        def one(item):
            try:
                return gate_mod.verify(client, item[4], config)
            except Exception as exc:  # noqa: BLE001 - rerun to fill gaps; answers are cached
                print(f"  {item[2]} {item[3]}: {str(exc)[:60]}", file=sys.stderr)
                return None

        with ThreadPoolExecutor(config.scan_concurrency) as pool:
            judged = list(pool.map(one, items))

    rows = [(it, j) for it, j in zip(items, judged, strict=True) if j is not None]
    print(f"judged {len(rows)} of {len(items)}\n")
    for d in label_dirs:
        mine = [(it, j) for it, j in rows if it[0] == d]
        print(f"== {d}")
        by_kind = {k: [j for it, j in mine if it[1] == k] for k, _ in KINDS}
        for kind, js in by_kind.items():
            verdicts = [gate_mod.verdict(j, config) for j in js]
            passed = sum(v.ok for v in verdicts)
            reasons = Counter(r for v in verdicts for r in v.reasons)
            top = ", ".join(f"{r} {n}" for r, n in reasons.most_common(4))
            print(
                f"  {kind:9} n={len(js):3}  gate passes {passed:3} ({passed / len(js):.0%})"
                f"  fails on: {top}"
            )

        def value(j, q):
            return j.nouls.get(q) if q in j.nouls else j.scores.get(q)

        print(f"  {'question':20} {'clips p50':>9} {'negatives p50':>13} {'AUC clip>neg':>13}")
        for q in (*NOULS, *POSITIVE):
            pos = [value(j, q) for j in by_kind["clip"] if value(j, q) is not None]
            neg = [value(j, q) for j in by_kind["negative"] if value(j, q) is not None]
            sep = auc(pos, neg) if q in POSITIVE else auc([-x for x in pos], [-x for x in neg])
            print(f"  {q:20} {st.median(pos):9.2f} {st.median(neg):13.2f} {sep:13.2f}")
        print()


if __name__ == "__main__":
    main(sys.argv[1:] or ["eval/labels-v2", "eval/labels-v2-b"])
