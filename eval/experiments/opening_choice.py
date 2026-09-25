"""Does one Choice over the openings find the labeled start better than scoring each alone?

The search judges every candidate opening on its own and keeps the strongest `hook` among
the clean ones. Replayed against both rubric-v2 labelers, that lands 3-6 of ~22 matched
starts in range, and no other rule over the same judgments does better (RESEARCH.md,
"Shortest clean ending"). The judgments carry the signal -- the labeled start is usually
top three on `hook`, within 0.1-0.15 of the best -- but each is scored alone, so noise of
that size decides the pick, and the cleanliness filter discards the right start about
half the time.

A Choice is relative by construction: one request sees every candidate at once, marked
in the transcript, and puts its weight on one. That is the Pass D shape. On the AMI proxy
it lost to a tuned constant (`pick_vs_snap.py`), but that proxy was topic starts in
meetings with no noise floor; this is clip starts, labeled twice, with a floor of 0.0s.

Both methods see the same candidates (`search.openings`) around the same anchors. Only
anchors inside a labeled clip or also_ok count. The current rule is replayed from the
response cache; the Choice costs one request per anchor.

    uv run python eval/experiments/opening_choice.py [--b] [label dirs...]
"""

from __future__ import annotations

import json
import statistics as st
import sys
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path

from typesafe_sdk import Choice

from jevcut import cuts as cuts_mod
from jevcut import search as search_mod
from jevcut.backends import load_env
from jevcut.client import JevClient
from jevcut.config import Config
from jevcut.models import Transcript
from jevcut.render import cut_id, render_markers
from jevcut.scan import read_scan

INSTRUCTIONS = (
    "`region.text` is a stretch of transcript with candidate start points marked "
    "«C00», «C01», and so on. A short clip for a social feed is being cut around the "
    "line `region.moment`. At which mark should the clip start? Come in on the line "
    "that grabs attention -- the claim, the question, the image, the surprising fact -- "
    "not on the run-up to it. But keep any setup the moment needs: someone who has seen "
    "nothing before the cut must still follow it. Of two marks that work equally well, "
    "prefer the later one."
)
# Variant b: the same without the tiebreak, after variant a came out late 26 to 6.
INSTRUCTIONS_B = INSTRUCTIONS.rsplit(" Of two marks", 1)[0]
# Variant c: the flagged line is a pointer, not a line the clip must contain. With openings
# offered after the anchor, b still put 1% on the right start in 12 of 15 far-off misses:
# told to cut "around" the line, it kept a line that closed the previous thought.
INSTRUCTIONS_C = (
    "`region.text` is a stretch of transcript with candidate start points marked "
    "«C00», «C01», and so on. The line `region.moment` was flagged as part of a moment "
    "worth clipping for a social feed, but it only points near the moment: the moment "
    "may begin before it, at it, or after it, and the flagged line may even be the end "
    "of the thought before. At which mark does that moment begin? Come in on the line "
    "that grabs attention -- the claim, the question, the image, the surprising fact -- "
    "not on the run-up to it. But keep any setup the moment needs: someone who has seen "
    "nothing before the cut must still follow it."
)
AFTER_S = 20.0  # context past the anchor, so the moment's point is readable


def region(transcript, spans, anchor):
    """Candidates renumbered locally from C00, rendered in their transcript."""
    marks = [replace(s, id=cut_id(i)) for i, (s, _) in enumerate(spans)]
    t0 = spans[0][0].t_start - 0.01
    # As the pipeline does: read on past the last candidate, which may be after the anchor.
    last = max(anchor.t1, spans[-1][0].t_start)
    sentences = transcript.between(t0, last + AFTER_S)
    return render_markers(sentences, marks), {m.id: s for m, (s, _) in zip(marks, spans)}


def main(label_dirs: list[str], instructions: str = INSTRUCTIONS) -> None:
    load_env()
    config = replace(Config(), cache_mode="live")  # answers are kept, so a rerun is free
    by_media = {}
    for d in label_dirs:
        for f in sorted(Path(d).glob("*.json")):
            label = json.loads(f.read_text())
            by_media.setdefault(label["video"]["local_path"], {})[d] = label

    # The current rule is replayed exactly as it was scored: a miss (a candidate whose
    # request failed in that run) stays skipped rather than being asked again now.
    replay = replace(config, cache_mode="replay")
    rows = []  # (label_dir, current_t, choice_t, label)
    for media, labels in sorted(by_media.items()):
        with JevClient(replay) as cached, JevClient(config) as client:
            run = Path(media).with_name(Path(media).stem + "-clips")
            transcript = Transcript.from_json(run / "transcript.json")
            real = search_mod._real(cuts_mod.extract(transcript, config))
            anchors = read_scan(run / "anchors.json").anchors

            def one(a, transcript=transcript, real=real):
                anchor = transcript.by_id(a.sentence_id)
                spans = search_mod.openings(real, anchor, config)
                if not spans:
                    return None
                current = search_mod.search(cached, transcript, real, a.sentence_id, replay)
                text, marks = region(transcript, spans, anchor)
                try:
                    result = client.ask(
                        {"region": {"text": text, "moment": anchor.text}},
                        {
                            "opening": Choice(
                                instructions=instructions, criteria=dict.fromkeys(marks)
                            )
                        },
                        pass_name="opening_choice",
                    )
                except Exception as exc:  # noqa: BLE001 - rerun to fill gaps; answers are cached
                    print(f"  {a.sentence_id}: {str(exc)[:60]}", file=sys.stderr)
                    return None
                pick = result.answers["opening"].choice
                if current.boundary is None or pick not in marks:
                    return None
                return anchor, current.boundary.t0, marks[pick].t_start

            with ThreadPoolExecutor(config.scan_concurrency) as pool:
                done = [r for r in pool.map(one, anchors) if r]
            for d, label in labels.items():
                gold = label["clips"] + label.get("also_ok", [])
                for anchor, cur, pick in done:
                    hit = [g for g in gold if g["start"] - 1 <= anchor.t0 <= g["end"]]
                    if hit:
                        rows.append((d, cur, pick, min(hit, key=lambda g: g["end"] - g["start"])))
            print(f"{run.name}: {len(done)} anchors", file=sys.stderr)

    def inside(t, g):
        return g["start_range"][0] - 0.5 <= t <= g["start_range"][1] + 0.5

    print(
        f"{'labels':18} {'n':>3}  {'rule':8} {'in range':>9} {'|err| p50':>9} "
        f"{'late':>5} {'early':>5}"
    )
    for d in label_dirs:
        mine = [r for r in rows if r[0] == d]
        for name, k in (("current", 1), ("choice", 2)):
            errs = [r[k] - r[3]["start"] for r in mine]
            print(
                f"{d:18} {len(mine):3}  {name:8} {sum(inside(r[k], r[3]) for r in mine):9} "
                f"{st.median(abs(e) for e in errs):8.1f}s {sum(e > 1 for e in errs):5} "
                f"{sum(e < -1 for e in errs):5}"
            )


if __name__ == "__main__":
    args = sys.argv[1:]
    variants = {"--b": INSTRUCTIONS_B, "--c": INSTRUCTIONS_C}
    variant = variants.get(args[0], INSTRUCTIONS) if args else INSTRUCTIONS
    main([a for a in args if a not in variants] or ["eval/labels-v2", "eval/labels-v2-b"], variant)
