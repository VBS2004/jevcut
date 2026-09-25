"""Does the ad check need the transcript around a clip, not just the clip?

A 97-minute Dwarkesh run shipped three pieces of sponsor reads (Jane Street twice,
Antithesis) with `promotion` at 0.08-0.26. The question had separated whole reads from
content perfectly (promotion_question.py), but jevcut cuts clips from the middle of a
segment: without "this episode is brought to you by" and the link, a read sounds like a
company describing an interesting problem. Whether something is an ad is a property of the
segment, and the evidence sits just outside the clip.

Three kinds of text, from all 38 labeled videos:

* **promotion, whole** -- every labeled negative whose `why` is a sponsor read or mention,
  a subscribe or bell ask, or a call to action (PROMO below, audited in the output);
* **promotion, middle** -- the middle MIDDLE_S of each of those, with the intro and the
  link cut away: the shape that slipped through;
* **content** -- every labeled clip and also_ok, both labelers: plenty of them name, praise
  or review a product without being an ad, and the fix must not flag them.

Each is asked two ways: the current question on the clip text alone, and a context
question that also sees CONTEXT_S of transcript either side.

    uv run python eval/experiments/promotion_context.py
"""

from __future__ import annotations

import json
import re
import sys
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path

from typesafe_sdk import Noul, NoulCriteria

from jevcut.backends import load_env
from jevcut.client import JevClient
from jevcut.config import Config
from jevcut.models import Transcript
from jevcut.questions import promotion_questions

LABELS = ("eval/labels-v2", "eval/labels-v2-b")
MIDDLE_S = 30.0
CONTEXT_S = 60.0
#: Promotion, read off each negative's `why`: sponsor reads, subscribe or bell asks,
#: calls to action. Game deals on a deals channel are the content, not an ad.
PROMO = re.compile(r"sponsor|subscribe|bell|call to action|repo plug|self-promotion", re.I)
#: Matched by PROMO but not promotion, on reading: a teaser answered *after* the sponsor.
NOT_PROMO = {("eval/labels-v2", "gQmPD4I62rU", 1)}

CONTEXT_QUESTION = {
    "promotion": Noul(
        instructions=(
            "Is `clip.text` promotion -- part of a sponsor read, an ad, or the speaker "
            "plugging something of their own -- rather than the discussion itself? Judge "
            "by the clip together with the transcript just before it (`around.before`) "
            "and just after it (`around.after`): a piece cut from the middle of a sponsor "
            "read is promotion even when it never names the offer or gives the link."
        ),
        criteria=NoulCriteria(
            true=(
                "The clip belongs to a stretch whose purpose is to get the viewer to buy, "
                "sign up for, install, subscribe to, follow or visit something"
            ),
            false=(
                "The clip is the discussion itself, even when it names, praises or reviews "
                "a product, and even when an ad starts or ends right next to it"
            ),
        ),
    )
}


def words(t: Transcript, t0: float, t1: float) -> str:
    return " ".join(
        w.text for s in t.sentences for w in s.words if w.t0 >= t0 - 0.05 and w.t1 <= t1 + 0.05
    )


def items() -> list[dict]:
    out = []
    for d in LABELS:
        for f in sorted(Path(d).glob("*.json")):
            label = json.loads(f.read_text())
            stem = Path(label["video"]["local_path"]).stem
            lemon = Path(f"eval/media/asr-lemonfox/{stem}.json")
            t = Transcript.from_json(
                lemon if lemon.exists() else f"eval/media/{stem}-clips/transcript.json"
            )

            def add(group, t0, t1, name, t=t, stem=stem):
                out.append(
                    {
                        "group": group,
                        "video": stem,
                        "name": name,
                        "text": words(t, t0, t1),
                        "before": words(t, t0 - CONTEXT_S, t0),
                        "after": words(t, t1, t1 + CONTEXT_S),
                    }
                )

            for g in label["clips"] + label.get("also_ok", []):
                add("content", g["start"], g["end"], g["id"])
            for i, n in enumerate(label.get("negatives", [])):
                if not PROMO.search(n["why"]) or (d, f.stem, i) in NOT_PROMO:
                    continue
                add("promotion, whole", n["start"], n["end"], n["why"][:60])
                if n["end"] - n["start"] >= MIDDLE_S + 6:
                    mid = (n["start"] + n["end"]) / 2
                    add("promotion, middle", mid - MIDDLE_S / 2, mid + MIDDLE_S / 2, n["why"][:60])
    # The three pieces of sponsor reads a real run shipped.
    t = Transcript.from_json("eval/media/asr-lemonfox/dwarkesh-rsi-debate.json")
    edl = Path("clips/dwarkesh-rsi-debate/edl.json")
    if edl.exists():
        for c in json.loads(edl.read_text())["clips"]:
            if c["id"] in ("clip002", "clip012", "clip013"):
                out.append(
                    {
                        "group": "shipped ad",
                        "video": "dwarkesh",
                        "name": c["id"],
                        "text": words(t, c["t0"], c["t1"]),
                        "before": words(t, c["t0"] - CONTEXT_S, c["t0"]),
                        "after": words(t, c["t1"], c["t1"] + CONTEXT_S),
                    }
                )
    return out


def main() -> None:
    load_env()
    config = replace(Config(), cache_mode="live")
    rows = items()
    budget = {"max_requests_per_video": 100_000, "max_tokens_per_video": 10**9}
    with JevClient(replace(config, **budget)) as client:

        def ask(item):
            try:
                alone = (
                    client.ask(
                        {"clip": {"text": item["text"]}},
                        promotion_questions(),
                        pass_name="promotion",
                    )
                    .answers["promotion"]
                    .noul
                )
                context = (
                    client.ask(
                        {
                            "clip": {"text": item["text"]},
                            "around": {"before": item["before"], "after": item["after"]},
                        },
                        CONTEXT_QUESTION,
                        pass_name="promotion",
                    )
                    .answers["promotion"]
                    .noul
                )
                return alone, context
            except Exception as exc:  # noqa: BLE001 - rerun to fill gaps; answers are cached
                print(f"  failed: {str(exc)[:60]}", file=sys.stderr)
                return None

        with ThreadPoolExecutor(config.scan_concurrency) as pool:
            answers = list(pool.map(ask, rows))

    scored = [(r, a) for r, a in zip(rows, answers, strict=True) if a is not None]
    print(f"judged {len(scored)} of {len(rows)}\n")
    print(f"{'':20} {'n':>4}   {'clip alone fires':>17}   {'with context fires':>19}")
    for group in ("promotion, whole", "promotion, middle", "content", "shipped ad"):
        g = [(r, a) for r, a in scored if r["group"] == group]
        if not g:
            continue
        alone = sum(a[0] >= 0.5 for _, a in g)
        ctx = sum(a[1] >= 0.5 for _, a in g)
        print(
            f"{group:20} {len(g):4}   {alone:10} ({alone / len(g):4.0%})   "
            f"{ctx:11} ({ctx / len(g):4.0%})"
        )
    print("\ncontent the context question flags:")
    for r, a in scored:
        if r["group"] == "content" and a[1] >= 0.5:
            print(f"  {a[1]:.2f} {r['video']:24} {r['name']}")
    print("promotion middles it still misses:")
    for r, a in scored:
        if r["group"] == "promotion, middle" and a[1] < 0.5:
            print(f"  {a[1]:.2f} {r['video']:24} {r['name']}")
    print(
        "shipped ads:",
        [
            (r["name"], round(a[0], 2), round(a[1], 2))
            for r, a in scored
            if r["group"] == "shipped ad"
        ],
    )


if __name__ == "__main__":
    main()
