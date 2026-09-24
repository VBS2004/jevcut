"""Does Jev PICK the right cut point better than a code rule chooses one?

Run 2026-09-22, 900 requests, $0.078. Results and caveats in RESEARCH.md.

`ami_coverage.py` established that the right answer is *on the sheet* 95% of the
time. This asks the other half, which is the actual thesis: given a region with
the cut points enumerated, does a Choice land closer to a human boundary than a
rule does? Nothing in jevcut had ever been measured on that.

Ground truth is AMI human topic starts, because they are the only human
boundaries in speech available before issue 011.

**Read the caveats before quoting any number from this.**

1. A topic boundary is not a clip boundary. Meeting subjects change gradually and
   by negotiation; a clip's "where does this thought start" may be far better
   defined. This is a proxy and it can only produce a warning, never a verdict.
2. **There is no noise floor.** AMI has zero double-annotated meetings (ES2008a
   looks like two annotators but is one segmentation split between them, numbered
   1-14 continuously). If two people would disagree by 10s here, every row in the
   table is inside the noise and none of them differ.
3. The wording is untuned -- that is issue 014's job. Two variants were tried.
4. The anchor is synthesised, so a swept constant offset partly inverts this
   script's own sampling. It is still a fair competitor in kind, because Pass C
   anchors will have their own distribution for a constant to exploit; but the
   specific number does not transfer.

    python eval/experiments/pick_vs_snap.py ./ami [n] [a|b]
"""

from __future__ import annotations

import glob
import random
import statistics as st
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed

from typesafe_sdk import Choice

from jevcut import cuts as cuts_mod
from jevcut.backends import load_env
from jevcut.client import JevClient
from jevcut.config import Config
from jevcut.models import Transcript
from jevcut.transcript import segment_words

BEFORE_REGION = "before_this_region"
SEED = 23
#: Anchor placed anywhere in the topic, so no single constant inverts the construction.
ANCHOR_WINDOW = (10.0, 85.0)

WORDINGS = {
    "a": (
        "The subject being discussed at `region.anchor_line` started somewhere earlier in "
        "`region.text`. Which mark is the point where it starts -- where the previous "
        "subject finishes and this one begins? Do not choose a mark that sits in the "
        "middle of the previous subject, and do not choose one after this subject is "
        "already under way."
    ),
    "b": (
        "`region.text` is a transcript with marks between sentences. Reading BACKWARDS "
        "from `region.anchor_line`: the speakers are on one subject there, and before that "
        "they were on a different one. Which mark is the LAST one at which they were still "
        "on the earlier subject, so that everything after it belongs to the subject at "
        "`region.anchor_line`?"
    ),
}


def build_cases(ami_root: str, helpers, cfg: Config, rng: random.Random) -> list:
    words_of, topic_starts = helpers
    cases = []
    for path in sorted(glob.glob(f"{ami_root}/topics/*.topic.xml")):
        meeting = path.split("/")[-1].split(".")[0]
        words, times = words_of(ami_root, meeting)
        if len(words) < 50:
            continue
        starts = topic_starts(ami_root, meeting, times)
        if len(starts) < 3:
            continue
        sentences = segment_words(words)
        transcript = Transcript(sentences=sentences, duration=sentences[-1].t1)
        cuts = cuts_mod.extract(transcript, cfg)
        for i, true_start in enumerate(starts[1:], start=1):
            topic_end = starts[i + 1] if i + 1 < len(starts) else transcript.duration
            lo = true_start + ANCHOR_WINDOW[0]
            hi = min(topic_end - 5.0, true_start + ANCHOR_WINDOW[1])
            if hi <= lo:
                continue
            want = rng.uniform(lo, hi)
            anchor = min((s for s in sentences if s.t0 >= want), key=lambda s: s.t0, default=None)
            if anchor is None:
                continue
            try:
                region = cuts_mod.build_region(transcript, cuts, anchor.id, cfg)
            except ValueError:
                continue
            before = [c for c in region.cuts if c.t_start < anchor.t0]
            # The answer must be IN the option list, or this measures coverage again.
            if len(before) < 4 or not any(abs(c.t_start - true_start) <= 2.0 for c in before):
                continue
            cases.append((true_start, anchor, region, before))
    return cases


def report(name: str, errors: list[float]) -> None:
    e = sorted(errors)
    n = len(e)
    within2 = sum(1 for x in e if x <= 2) / n * 100
    within5 = sum(1 for x in e if x <= 5) / n * 100
    print(f"{name:>22}{st.median(e):8.1f}s{e[int(n * 0.9)]:7.1f}s{within2:6.0f}%{within5:6.0f}%")


def main() -> None:
    ami_root = sys.argv[1] if len(sys.argv) > 1 else "./ami"
    n_cases = int(sys.argv[2]) if len(sys.argv) > 2 else 300
    wording = sys.argv[3] if len(sys.argv) > 3 else "a"

    helper_src = open(__file__.replace("pick_vs_snap", "ami_coverage")).read().split("def main(")[0]
    ns: dict = {}
    exec(compile(helper_src, "ami_coverage", "exec"), ns)  # our own file, shares its parsers

    load_env()
    rng = random.Random(SEED)
    cfg = Config()
    cases = build_cases(ami_root, (ns["words_of"], ns["topic_starts"]), cfg, rng)
    rng.shuffle(cases)
    cases = cases[:n_cases]
    print(f"{len(cases)} cases, wording '{wording}', anchor placed uniformly inside the topic\n")

    def ask(client: JevClient, case) -> tuple:
        true_start, anchor, region, before = case
        result = client.ask(
            {"region": {"anchor_line": anchor.id, "text": region.text}},
            {
                "start_cut": Choice(
                    instructions=WORDINGS[wording],
                    criteria={
                        **{c.id: None for c in before},
                        BEFORE_REGION: "This subject started before anything shown here",
                    },
                )
            },
            pass_name=f"pick_vs_snap_{wording}",
        )
        answer = result.answers["start_cut"]
        picked = {c.id: c.t_start for c in before}.get(answer.choice)
        return true_start, picked, answer.confidence, before, anchor

    rows = []
    with JevClient(cfg, run_dir=f"{ami_root}/run_{wording}") as client:
        with ThreadPoolExecutor(max_workers=cfg.scan_concurrency) as pool:
            for fut in as_completed([pool.submit(ask, client, c) for c in cases]):
                try:
                    row = fut.result()
                except Exception as exc:  # noqa: BLE001 - one case must not sink the run
                    print(f"  case failed: {type(exc).__name__}: {exc}")
                    continue
                if row[1] is not None:
                    rows.append(row)
        print(client.summary())

    # Sweep the constant and keep its best setting: 013 says give a baseline its best shot.
    best_k, best_med = 0, float("inf")
    for k in range(0, 95, 5):
        med = st.median(
            [
                abs(min(b, key=lambda c: abs(c.t_start - (a.t0 - k))).t_start - t)
                for t, _, _, b, a in rows
            ]
        )
        if med < best_med:
            best_k, best_med = k, med

    print(f"\nscored {len(rows)}   (best constant found by sweep: anchor-{best_k}s)\n")
    print(f"{'method':>22}{'median':>9}{'p90':>8}{'<=2s':>7}{'<=5s':>7}")
    report("jev", [abs(p - t) for t, p, _, _, _ in rows])
    report(
        f"snap to anchor-{best_k}s",
        [
            abs(min(b, key=lambda c: abs(c.t_start - (a.t0 - best_k))).t_start - t)
            for t, _, _, b, a in rows
        ],
    )
    report(
        "biggest pause", [abs(max(b, key=lambda c: c.gap_ms).t_start - t) for t, _, _, b, _ in rows]
    )
    report("random cut", [abs(rng.choice(b).t_start - t) for t, _, _, b, _ in rows])
    report(
        "earliest cut", [abs(min(b, key=lambda c: c.t_start).t_start - t) for t, _, _, b, _ in rows]
    )

    print("\njev by confidence (flat here -- no threshold rescues it):")
    for lo, hi in ((0.0, 0.3), (0.3, 0.5), (0.5, 0.7), (0.7, 1.01)):
        sel = [abs(p - t) for t, p, c, _, _ in rows if lo <= c < hi]
        if len(sel) >= 10:
            print(
                f"   conf {lo:.1f}-{hi:.1f}  n={len(sel):3}  median {st.median(sel):6.1f}s  "
                f"<=5s {sum(1 for x in sel if x <= 5) / len(sel) * 100:3.0f}%"
            )


if __name__ == "__main__":
    main()
