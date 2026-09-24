"""Why does the opening Choice sometimes start a clip 10-30s from where it should?

On the six-round run, about two-thirds of found clips start within 3s of the labeled start
and about one in five start 10s or more away -- the tail that fails 013's p90 bar
(RESEARCH.md, "Baselines (013)"). For every found clip this replays its opening Choice from
the response cache (no requests) and asks, of the far-off ones:

* **offered?** was there a candidate opening within 1s of the labeled start at all, or was
  the right answer never on the list;
* **sure?** how much weight the pick got, against the near picks;
* **where was the right one?** its rank among the marks, and the weight it got;
* **which way?** early (opening on the previous topic) or late (skipping the setup).

    uv run python eval/experiments/opening_misses.py
"""

from __future__ import annotations

import json
import statistics as st
from dataclasses import replace
from pathlib import Path

from jevcut import cuts as cuts_mod
from jevcut import evaluate
from jevcut import search as search_mod
from jevcut.backends import load_env
from jevcut.client import JevClient
from jevcut.config import Config
from jevcut.edl import read_edl
from jevcut.models import Transcript
from jevcut.questions import opening_questions
from jevcut.render import cut_id, render_markers

RUN = "-lemonfox-r6"
FAR_S = 10.0
LABELS = ("eval/labels-v2", "eval/labels-v2-b")


def opening_answer(client, transcript, real, anchor, config):
    """The cached Choice for this anchor: marks -> (start time, weight), and the pick."""
    spans = search_mod.openings(real, anchor, config)
    marks = {cut_id(i): start for i, (start, _) in enumerate(spans)}
    shown = [replace(start, id=m) for m, start in marks.items()]
    sentences = transcript.between(
        spans[0][0].t_start - 0.01, anchor.t1 + search_mod.OPENING_CONTEXT_AFTER_S
    )
    answer = client.ask(
        {"region": {"text": render_markers(sentences, shown), "moment": anchor.text}},
        opening_questions(list(marks)),
        pass_name="opening",
    ).answers["opening"]
    weights = answer.probabilities or {}
    return {m: (s.t_start, weights.get(m, 0.0)) for m, s in marks.items()}, answer.choice


def main() -> None:
    load_env()
    config = replace(Config(), cache_mode="replay")
    rows = []
    with JevClient(replace(config, max_requests_per_video=100_000)) as client:
        for d in LABELS:
            for f in sorted(Path(d).glob("*.json")):
                label = json.loads(f.read_text())
                stem = Path(label["video"]["local_path"]).stem
                t = Transcript.from_json(f"eval/media/asr-lemonfox/{stem}.json")
                real = search_mod._real(cuts_mod.extract(t, config))
                _, clips = read_edl(Path("eval/media") / f"{stem}{RUN}" / "edl.json")
                gold = label["clips"]
                pairs = evaluate.match(
                    [(c.t0, c.t1) for c in clips], [(g["start"], g["end"]) for g in gold]
                )
                for i, j in pairs:
                    c, g = clips[i], gold[j]
                    anchor = t.by_id(c.anchor_id)
                    marks, pick = opening_answer(client, t, real, anchor, config)
                    order = sorted(marks, key=lambda m: -marks[m][1])
                    right = [m for m in marks if abs(marks[m][0] - g["start"]) <= 1.0]
                    rows.append(
                        {
                            "err": c.t0 - g["start"],
                            "offered": bool(right),
                            "pick_weight": marks[pick][1] if pick in marks else 0.0,
                            "right_rank": min((order.index(m) + 1 for m in right), default=None),
                            "right_weight": max((marks[m][1] for m in right), default=0.0),
                            "n_marks": len(marks),
                            "anchor_to_label": anchor.t0 - g["start"],
                        }
                    )

    far = [r for r in rows if abs(r["err"]) >= FAR_S]
    near = [r for r in rows if abs(r["err"]) < 3.0]
    print(
        f"{len(rows)} found clips (both labelers): {len(near)} within 3s, "
        f"{len(far)} off by {FAR_S:.0f}s+\n"
    )
    for name, group in (("within 3s", near), (f"{FAR_S:.0f}s+ off", far)):
        offered = [r for r in group if r["offered"]]
        print(f"{name}:")
        print(f"  right start on offer: {len(offered)} of {len(group)}")
        print(f"  weight on the pick: median {st.median(r['pick_weight'] for r in group):.2f}")
        if offered:
            print(
                f"  right start's rank among ~{st.median(r['n_marks'] for r in group):.0f} marks: "
                f"median {st.median(r['right_rank'] for r in offered):.0f}, "
                f"weight median {st.median(r['right_weight'] for r in offered):.2f}"
            )
        if group is far:
            late = sum(r["err"] > 0 for r in group)
            print(
                f"  late (skipped the setup) {late}, "
                f"early (opened on what came before) {len(group) - late}"
            )
            print(
                "  labeled start before the anchor: "
                + ", ".join(
                    f"{r['anchor_to_label']:.0f}s" for r in sorted(group, key=lambda r: r["err"])
                )
            )


if __name__ == "__main__":
    main()
