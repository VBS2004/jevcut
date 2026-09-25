"""Choose the opening from the ending, not from the anchor.

On 38 videos about one found clip in four starts 10s+ from the labeled start. Of those 48,
31 open early -- the labeled clip starts 1-26s *after* the scan's anchor line, which
belonged to the tail of the thought before -- and 17 skip a long setup
(eval/experiments/opening_misses.py). Both fixes tried so far still chose the opening
relative to the anchor: offering openings after it, and telling the Choice the anchor only
points near the moment. Neither moved the tail (RESEARCH.md).

By the time the search has its ending it knows where the payoff lands. So ask, once the
end is fixed: where should a clip that ends *here* begin? The state is the transcript from
as far back as the band allows up to the chosen end, every real opening marked, and no
anchor at all.

For every clip the current version shipped, this asks that one Choice and re-scores the
clips with the new starts against both labelers. The ending and selection are unchanged,
and the finished clip is not re-gated, so this measures the opening decision alone.

    uv run python eval/experiments/reopen_from_end.py
"""

from __future__ import annotations

import statistics as st
import sys
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path

from typesafe_sdk import Choice

from jevcut import cuts as cuts_mod
from jevcut import evaluate
from jevcut import search as search_mod
from jevcut.backends import load_env
from jevcut.client import JevClient
from jevcut.config import Config
from jevcut.edl import read_edl, write_edl
from jevcut.models import Transcript
from jevcut.render import cut_id, render_markers

RUN, OUT = "-lemonfox-r6", "-lemonfox-reopen"
LABELS = ("eval/labels-v2", "eval/labels-v2-b")
INSTRUCTIONS = (
    "`region.text` is a stretch of transcript with candidate start points marked «C00», "
    "«C01», and so on. It ends exactly where a short clip for a social feed ends: on the "
    "point that clip lands. At which mark should that clip begin, so that someone who has "
    "seen nothing before it follows the whole way to that ending? Come in on the line that "
    "grabs attention -- the claim, the question, the image, the surprising fact -- not on "
    "the run-up to it, and not on the end of a different thought before it. But keep any "
    "setup the ending needs."
)


def reopen(client, transcript, real, t_end, config):
    """One Choice over the openings a clip ending at ``t_end`` could have. None on failure."""
    low, high = config.duration_band_s
    starts = [c for c in real if low <= t_end - c.t_start <= high]
    if not starts:
        return None
    marks = {cut_id(i): s for i, s in enumerate(starts)}
    shown = [replace(s, id=m) for m, s in marks.items()]
    sentences = transcript.between(starts[0].t_start - 0.01, t_end)
    try:
        answer = client.ask(
            {"region": {"text": render_markers(sentences, shown)}},
            {"opening": Choice(instructions=INSTRUCTIONS, criteria=dict.fromkeys(marks))},
            pass_name="reopen",
        ).answers["opening"]
    except Exception as exc:  # noqa: BLE001 - rerun to fill gaps; answers are cached
        print(f"  failed: {str(exc)[:60]}", file=sys.stderr)
        return None
    return marks.get(answer.choice)


def main() -> None:
    load_env()
    config = replace(Config(), cache_mode="live")
    with JevClient(
        replace(config, max_requests_per_video=100_000, max_tokens_per_video=10**9)
    ) as c:
        for run in sorted(Path("eval/media").glob(f"*{RUN}")):
            stem = run.name.removesuffix(RUN)
            t = Transcript.from_json(f"eval/media/asr-lemonfox/{stem}.json")
            real = search_mod._real(cuts_mod.extract(t, config))
            source, clips = read_edl(run / "edl.json")

            def one(clip, t=t, real=real):
                start = reopen(c, t, real, clip.t1, config)
                return replace(clip, t0=start.t_start) if start else clip

            with ThreadPoolExecutor(config.scan_concurrency) as pool:
                moved = list(pool.map(one, clips))
            out = Path("eval/media") / f"{stem}{OUT}"
            out.mkdir(exist_ok=True)
            write_edl(moved, out / "edl.json", source=source)

    for lab in LABELS:
        for name, suffix in (("anchor-relative (current)", RUN), ("reopened from the end", OUT)):
            scores, _ = evaluate.score_set(lab, suffix=suffix)
            s = evaluate.summary(scores)
            e = sorted(x for v in scores for x in v.start_errors)
            q = st.quantiles(e, n=10)
            print(
                f"{lab:17} {name:26} found {s['matched']:3} right "
                f"{sum(v.in_range for v in scores):2} P {s['precision']:.2f} R {s['recall']:.2f} "
                f"start p50 {s['start_err_median']:.1f}s p80 {q[7]:.1f}s p90 {q[8]:.1f}s "
                f"10s+ {sum(x >= 10 for x in e):2}/{len(e)} len {s['duration_median']:.0f}s"
            )


if __name__ == "__main__":
    main()
