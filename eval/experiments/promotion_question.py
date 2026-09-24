"""Can one Noul tell promotion from content, before it is wired into the gate?

`gate_on_labels.py` found the gate passes half the hard negatives, and a third of those
are sponsor reads and plugs that open like part of the argument. No question asks about
them. This spread-tests one against every rubric-v2 text -- required clips, also_ok, and
negatives -- asked alone, so the gate's own cache is untouched until the wording is known
to work.

What "promotion" is here was read off the labelers' own `why` for each negative (sponsor
reads, self-plugs, like-and-subscribe asks), listed in PROMOTION below. Every labeled clip
is content by construction -- including product reviews, which the question must not
confuse with an ad: several of the Theo clips praise or pan a model.

    PYTHONPATH=eval/experiments uv run python eval/experiments/promotion_question.py
"""

from __future__ import annotations

import json
import sys
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path

from gate_on_labels import auc, words_between

from jevcut.backends import load_env
from jevcut.client import JevClient
from jevcut.config import Config
from jevcut.models import Transcript
from jevcut.questions import promotion_questions

#: (label dir, video id, negative index) of every negative whose `why` is promotion.
PROMOTION = {
    ("eval/labels-v2", "072eNztI06k", 0),  # repo plug, pip install
    ("eval/labels-v2", "NbM3dGrVPXo", 2),  # Superhuman sponsor read
    ("eval/labels-v2", "PrSf7IOYu-I", 1),  # Antithesis sponsor read
    ("eval/labels-v2", "PrSf7IOYu-I", 3),  # GrokBot sponsor read
    ("eval/labels-v2", "jgGyX7MPPVg", 0),  # WorkOS sponsor read
    ("eval/labels-v2", "jgGyX7MPPVg", 3),  # Parallel sponsor read
    ("eval/labels-v2", "uw61C_qbgNg", 3),  # like/share/subscribe ask
    ("eval/labels-v2-b", "072eNztI06k", 0),  # repo plug
    ("eval/labels-v2-b", "NbM3dGrVPXo", 1),  # Superhuman sponsor read
    ("eval/labels-v2-b", "NbM3dGrVPXo", 4),  # outro and subscribe ask
    ("eval/labels-v2-b", "PrSf7IOYu-I", 1),  # Antithesis sponsor read
    ("eval/labels-v2-b", "PrSf7IOYu-I", 2),  # Jane Street sponsor read
    ("eval/labels-v2-b", "PrSf7IOYu-I", 3),  # GrokBot sponsor read
    ("eval/labels-v2-b", "jgGyX7MPPVg", 0),  # WorkOS sponsor read
    ("eval/labels-v2-b", "jgGyX7MPPVg", 1),  # Parallel sponsor read
    ("eval/labels-v2-b", "jgGyX7MPPVg", 5),  # subscribe plea
    ("eval/labels-v2-b", "uw61C_qbgNg", 4),  # like/share/subscribe outro
}
GROUPS = ("clip", "also_ok", "promotion", "other negative")


def main(label_dirs: list[str]) -> None:
    load_env()
    config = replace(Config(), cache_mode="live")
    items = []  # (group, video, id, text)
    for d in label_dirs:
        for f in sorted(Path(d).glob("*.json")):
            label = json.loads(f.read_text())
            media = Path(label["video"]["local_path"])
            transcript = Transcript.from_json(
                media.with_name(media.stem + "-clips") / "transcript.json"
            )
            for g in label["clips"]:
                items.append(
                    ("clip", f.stem, g["id"], words_between(transcript, g["start"], g["end"]))
                )
            for g in label.get("also_ok", []):
                items.append(
                    ("also_ok", f.stem, g["id"], words_between(transcript, g["start"], g["end"]))
                )
            for i, g in enumerate(label.get("negatives", [])):
                group = "promotion" if (d, f.stem, i) in PROMOTION else "other negative"
                items.append(
                    (group, f.stem, g["why"][:50], words_between(transcript, g["start"], g["end"]))
                )

    with JevClient(replace(config, max_requests_per_video=10_000)) as client:

        def one(item):
            try:
                result = client.ask(
                    {"clip": {"text": item[3]}}, promotion_questions(), pass_name="promotion"
                )
                return result.answers["promotion"].noul
            except Exception as exc:  # noqa: BLE001 - rerun to fill gaps; answers are cached
                print(f"  {item[1]} {item[2]}: {str(exc)[:60]}", file=sys.stderr)
                return None

        with ThreadPoolExecutor(config.scan_concurrency) as pool:
            scored = list(pool.map(one, items))

    rows = [(it, p) for it, p in zip(items, scored, strict=True) if p is not None]
    print(f"judged {len(rows)} of {len(items)}\n")
    print(f"{'group':15} {'n':>4} {'fires (>= 0.5)':>15} {'p50':>6}")
    by = {g: sorted(p for it, p in rows if it[0] == g) for g in GROUPS}
    for g, ps in by.items():
        print(f"{g:15} {len(ps):4} {sum(p >= 0.5 for p in ps):15} {ps[len(ps) // 2]:6.2f}")
    print(f"\nAUC promotion over clips: {auc(by['promotion'], by['clip']):.2f}")
    print("\nfires on content (clip / also_ok / other negative):")
    for it, p in sorted(rows, key=lambda r: -r[1]):
        if p >= 0.5 and it[0] != "promotion":
            print(f"  {p:.2f} {it[0]:14} {it[1]} {it[2]}")
    print("misses promotion:")
    for it, p in rows:
        if p < 0.5 and it[0] == "promotion":
            print(f"  {p:.2f} {it[1]} {it[2]}")


if __name__ == "__main__":
    main(sys.argv[1:] or ["eval/labels-v2", "eval/labels-v2-b"])
