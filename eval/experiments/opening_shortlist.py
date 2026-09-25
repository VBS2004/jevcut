"""Combine the two opening signals: the Choice shortlists, the gate checks each on the clip.

One question about the opening kept failing in different ways (RESEARCH.md, "The
openings' tail on 38 videos"): read by eye, far-off starts open on a channel greeting, a
mid-argument "But you're...", the tail of the previous bit, or skip the hook. The Choice
is good at ranking marks against each other; the gate's per-clip questions are good at
seeing exactly those failures in a finished clip. So: the Choice's top SHORTLIST marks, in
its order, each judged as the finished clip from that mark to the clip's end, and

* **veto** -- the first that is clean (`starts_mid_thought` and `dangling_reference` below
  the repair bar) and has a hook of at least level 1 wins. Level 0 of `hook` is, in its own
  words, "housekeeping, hesitation, or a thought already underway"; level 1 is "states
  plainly what is about to be discussed". With none, the Choice's own pick stays.
* **best hook** -- for comparison: the highest `hook` among the clean ones.

The ending is held fixed (a start that would leave the band is skipped), so this measures
the opening decision alone, on every clip the current version shipped.

    uv run python eval/experiments/opening_shortlist.py
"""

from __future__ import annotations

import statistics as st
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path

from jevcut import cuts as cuts_mod
from jevcut import evaluate
from jevcut import gate as gate_mod
from jevcut import search as search_mod
from jevcut.backends import load_env
from jevcut.client import JevClient
from jevcut.config import Config
from jevcut.edl import read_edl, write_edl
from jevcut.models import Transcript
from jevcut.questions import opening_questions
from jevcut.render import cut_id, render_markers

RUN = "-lemonfox-r6"
SHORTLIST = 3
HOOK_FLOOR = 1.0  # level 1 of `hook`: "states plainly what is about to be discussed"
LABELS = ("eval/labels-v2", "eval/labels-v2-b")
RULES = ("veto", "best-hook")


def ranked_openings(client, transcript, real, anchor, config):
    """The current opening Choice, replayed from cache: its marks, most weight first."""
    spans = search_mod.openings(real, anchor, config)
    if not spans:
        return []
    marks = {cut_id(i): s for i, (s, _) in enumerate(spans)}
    shown = [replace(s, id=m) for m, s in marks.items()]
    sentences = transcript.between(
        spans[0][0].t_start - 0.01, anchor.t1 + search_mod.OPENING_CONTEXT_AFTER_S
    )
    answer = client.ask(
        {"region": {"text": render_markers(sentences, shown), "moment": anchor.text}},
        opening_questions(list(marks)),
        pass_name="opening",
    ).answers["opening"]
    weight = dict(answer.probabilities or {})
    weight[answer.choice] = float("inf")
    return [marks[m] for m in sorted(marks, key=lambda m: -weight.get(m, 0.0))]


def main() -> None:
    load_env()
    config = replace(Config(), cache_mode="live")
    replay = replace(config, cache_mode="replay")
    low, high = config.duration_band_s
    changed = {r: 0 for r in RULES}
    total = 0
    budget = {"max_requests_per_video": 100_000, "max_tokens_per_video": 10**9}
    with (
        JevClient(replace(replay, **budget)) as cached,
        JevClient(replace(config, **budget)) as live,
    ):
        for run in sorted(Path("eval/media").glob(f"*{RUN}")):
            stem = run.name.removesuffix(RUN)
            t = Transcript.from_json(f"eval/media/asr-lemonfox/{stem}.json")
            real = search_mod._real(cuts_mod.extract(t, config))
            source, clips = read_edl(run / "edl.json")

            def one(clip, t=t, real=real):
                anchor = t.by_id(clip.anchor_id)
                ranked = ranked_openings(cached, t, real, anchor, config)[:SHORTLIST]
                ranked = [s for s in ranked if low <= clip.t1 - s.t_start <= high]
                judged = []
                for s in ranked:
                    text = " ".join(x.text for x in t.between(s.t_start, clip.t1))
                    try:
                        judged.append((s, gate_mod.verify(live, text, config)))
                    except Exception:  # noqa: BLE001 - a lost candidate is skipped
                        continue

                def clean(j):
                    return (
                        j.nouls.get("starts_mid_thought", 0) < config.repair_threshold
                        and j.nouls.get("dangling_reference", 0) < config.repair_threshold
                    )

                veto = next(
                    (s for s, j in judged if clean(j) and j.scores.get("hook", 0) >= HOOK_FLOOR),
                    None,
                )
                clean_ones = [(s, j) for s, j in judged if clean(j)]
                best = (
                    max(clean_ones, key=lambda sj: sj[1].scores.get("hook", 0))[0]
                    if clean_ones
                    else None
                )
                return {
                    "veto": replace(clip, t0=veto.t_start) if veto else clip,
                    "best-hook": replace(clip, t0=best.t_start) if best else clip,
                }

            with ThreadPoolExecutor(config.scan_concurrency) as pool:
                results = list(pool.map(one, clips))
            for rule in RULES:
                moved = [r[rule] for r in results]
                changed[rule] += sum(m.t0 != c.t0 for m, c in zip(moved, clips, strict=True))
                out = Path("eval/media") / f"{stem}-lemonfox-{rule}"
                out.mkdir(exist_ok=True)
                write_edl(moved, out / "edl.json", source=source)
            total += len(clips)

    print(f"{total} clips; starts changed: " + ", ".join(f"{r} {n}" for r, n in changed.items()))
    for lab in LABELS:
        for name, suffix in (("current", RUN), *((r, f"-lemonfox-{r}") for r in RULES)):
            scores, _ = evaluate.score_set(lab, suffix=suffix)
            s = evaluate.summary(scores)
            e = sorted(x for v in scores for x in v.start_errors)
            q = st.quantiles(e, n=10)
            print(
                f"{lab:17} {name:10} found {s['matched']:3} right "
                f"{sum(v.in_range for v in scores):2} P {s['precision']:.2f} R {s['recall']:.2f} "
                f"start p50 {s['start_err_median']:.1f}s p80 {q[7]:.1f}s p90 {q[8]:.1f}s "
                f"10s+ {sum(x >= 10 for x in e):2}/{len(e)} len {s['duration_median']:.0f}s"
            )


if __name__ == "__main__":
    main()
