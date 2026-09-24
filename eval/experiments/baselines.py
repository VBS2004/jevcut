"""Issue 013: does jevcut beat simpler ways of cutting the same videos?

Five baselines, built on exactly what jevcut uses -- the same Lemonfox transcripts, the
same cut points, the same labels and scorer -- so only selection and boundaries differ.
Each writes an ordinary EDL to ``eval/media/<stem>-base-<name>/``, scored by
`jevcut eval --suffix` and `jevcut bench` like any version. jevcut is the six-round run
(``<stem>-lemonfox-r6``).

1. **dense** (jevmeter-shaped): every sentence judged with the gate's own questions and
   ranked by the same composite jevcut ranks by; clips are cut around the peaks of a
   12s rolling average.
2. **windows** (jev-skip-shaped): the transcript tiled into 30s windows ending on
   sentence ends, capped at 45s; each judged once, the best kept.
3. **naive**: the top-scoring sentence +/- 15s. Reuses dense's sentence scores.
4. **offset**: jevcut's own shipped anchors, edges at a constant offset from the anchor
   line, snapped to the nearest cut. The offsets are fitted leave-one-video-out on
   labeler A, so a video is never scored with offsets learned from it.
5. **snap**: jevcut's own shipped anchors, grown a sentence at a time on alternating
   sides to TARGET_S. No model call for boundaries at all.

4 and 5 hold jevcut's selection fixed and swap only how the edges are set: they test
whether Jev earns its place at the boundary, which 1-3 (selection and edges together)
cannot. Every baseline ships as many clips per video as jevcut did, so no system wins
recall by shipping more.

Given their best shot: dense, naive and snap aim at TARGET_S, the labels' median length;
offset learns from labels. Measured on 8 pilot videos, not 013's 40.

    uv run python eval/experiments/baselines.py build     # EDLs, ~5k requests, cached
    uv run python eval/experiments/baselines.py report    # the table, no new requests
"""

from __future__ import annotations

import json
import statistics as st
import sys
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
from jevcut.edl import Clip, composite, read_edl, write_edl
from jevcut.models import Transcript

MEDIA = Path("eval/media")
JEVCUT = "-lemonfox-r6"
SYSTEMS = ("dense", "windows", "naive", "offset", "snap")
TARGET_S = 40.0  # the rubric-v2 labels' median length (40-42s)
ROLLING_S = 12.0
NAIVE_PAD_S = 15.0
WINDOW_S, WINDOW_CAP_S = 30.0, 45.0
LABELS = (("v2 A", "eval/labels-v2"), ("v2 B", "eval/labels-v2-b"))


def stems() -> list[str]:
    return sorted(p.name.removesuffix(JEVCUT) for p in MEDIA.glob(f"*{JEVCUT}"))


def transcript_of(stem: str) -> Transcript:
    return Transcript.from_json(f"eval/media/asr-lemonfox/{stem}.json")


def text(t: Transcript, t0: float, t1: float) -> str:
    return " ".join(s.text for s in t.between(t0, t1))


class Snap:
    """Edges land on real boundaries, as every jevcut edge does."""

    def __init__(self, t: Transcript, config: Config):
        self.real = search_mod._real(cuts_mod.extract(t, config))
        low, high = config.duration_band_s
        self.low, self.high = low, high

    def start(self, t: float) -> float:
        return min(self.real, key=lambda c: abs(c.t_start - t)).t_start

    def end(self, t: float, after: float) -> float:
        """The real end nearest ``t`` that keeps the clip from ``after`` inside the band."""
        fits = [c.t_end for c in self.real if self.low <= c.t_end - after <= self.high]
        return min(fits, key=lambda e: abs(e - t)) if fits else t

    def around(self, t0: float, t1: float, length: float = TARGET_S) -> tuple[float, float]:
        mid = (t0 + t1) / 2
        start = self.start(mid - length / 2)
        return start, self.end(start + length, start)


def top(cands: list[tuple[float, float, float, str]], n: int) -> list[tuple]:
    """Best first, skipping any that overlaps a kept one by IoU > 0.4 (jevcut's dedupe)."""
    kept = []
    for c in sorted(cands, key=lambda c: -c[0]):
        if all(evaluate.iou((c[1], c[2]), (k[1], k[2])) <= 0.4 for k in kept):
            kept.append(c)
        if len(kept) == n:
            break
    return kept


def write(stem: str, name: str, picks: list[tuple]) -> None:
    clips = [
        Clip(
            id=f"clip{i + 1:03d}",
            anchor_id=aid,
            kind="baseline",
            t0=t0,
            t1=t1,
            render_t0=t0,
            render_t1=t1,
            start_cut="",
            end_cut="",
            scores={"composite": round(score, 3)},
            rank=i + 1,
        )
        for i, (score, t0, t1, aid) in enumerate(picks)
    ]
    out = MEDIA / f"{stem}-base-{name}"
    out.mkdir(exist_ok=True)
    write_edl(clips, out / "edl.json", source=f"baseline {name}")


def judge_all(client: JevClient, texts: list[str], config: Config) -> list[float | None]:
    def one(s: str) -> float | None:
        try:
            return composite(gate_mod.verify(client, s, config).scores)
        except Exception as exc:  # noqa: BLE001 - rerun to fill gaps; answers are cached
            print(f"  failed: {str(exc)[:60]}", file=sys.stderr)
            return None

    with ThreadPoolExecutor(config.scan_concurrency) as pool:
        return list(pool.map(one, texts))


def fit_offsets(held_out: str) -> tuple[float, float]:
    """Median (anchor start - label start) and (label end - anchor end) over the other
    videos' shipped anchors that sit inside a labeler-A clip: the best constant there is."""
    lead, tail = [], []
    for f in Path("eval/labels-v2").glob("*.json"):
        label = json.loads(f.read_text())
        stem = Path(label["video"]["local_path"]).stem
        if stem == held_out:
            continue
        t = transcript_of(stem)
        _, clips = read_edl(MEDIA / f"{stem}{JEVCUT}" / "edl.json")
        for c in clips:
            a = t.by_id(c.anchor_id)
            for g in label["clips"]:
                if g["start"] - 1 <= a.t0 <= g["end"]:
                    lead.append(a.t0 - g["start"])
                    tail.append(g["end"] - a.t1)
    return st.median(lead), st.median(tail)


def build() -> None:
    load_env()
    config = replace(Config(), cache_mode="live")
    requests = {"dense": 0, "windows": 0}
    with JevClient(
        replace(config, max_requests_per_video=100_000, max_tokens_per_video=100_000_000)
    ) as client:
        for stem in stems():
            t = transcript_of(stem)
            snap = Snap(t, config)
            _, jev = read_edl(MEDIA / f"{stem}{JEVCUT}" / "edl.json")
            n = len(jev)
            sentences = t.sentences

            scores = judge_all(client, [s.text for s in sentences], config)
            requests["dense"] += len(sentences)
            scored = [(s, v) for s, v in zip(sentences, scores, strict=True) if v is not None]

            dense = []
            for s, _ in scored:
                inside = [v for u, v in scored if s.t0 <= u.t0 <= s.t0 + ROLLING_S]
                t0, t1 = snap.around(s.t0, s.t0 + ROLLING_S)
                dense.append((st.mean(inside), t0, t1, s.id))
            write(stem, "dense", top(dense, n))

            naive = []
            for s, v in scored:
                t0 = snap.start(s.t0 - NAIVE_PAD_S)
                naive.append((v, t0, snap.end(s.t1 + NAIVE_PAD_S, t0), s.id))
            write(stem, "naive", top(naive, n))

            tiles, i = [], 0
            while i < len(sentences):
                j = i
                while j + 1 < len(sentences) and sentences[j].t1 - sentences[i].t0 < WINDOW_S:
                    j += 1
                while j > i and sentences[j].t1 - sentences[i].t0 > WINDOW_CAP_S:
                    j -= 1
                tiles.append((sentences[i], sentences[j]))
                i = j + 1
            tile_scores = judge_all(client, [text(t, a.t0, b.t1) for a, b in tiles], config)
            requests["windows"] += len(tiles)
            windows = [
                (v, a.t0, b.t1, a.id)
                for (a, b), v in zip(tiles, tile_scores, strict=True)
                if v is not None
            ]
            write(stem, "windows", top(windows, n))

            lead, tail = fit_offsets(stem)
            offset, grown = [], []
            for c in jev:
                a = t.by_id(c.anchor_id)
                t0 = snap.start(a.t0 - lead)
                offset.append((composite(c.scores), t0, snap.end(a.t1 + tail, t0), a.id))
                k = next(i for i, s in enumerate(sentences) if s.id == a.id)
                lo = hi = k
                while sentences[hi].t1 - sentences[lo].t0 < TARGET_S:
                    before = lo > 0 and sentences[hi].t1 - sentences[lo - 1].t0 <= snap.high
                    after = (
                        hi + 1 < len(sentences)
                        and sentences[hi + 1].t1 - sentences[lo].t0 <= snap.high
                    )
                    if not (before or after):
                        break
                    if before and (not after or (hi - k) >= (k - lo)):
                        lo -= 1
                    else:
                        hi += 1
                grown.append((composite(c.scores), sentences[lo].t0, sentences[hi].t1, a.id))
            write(stem, "offset", offset)
            write(stem, "snap", grown)
            print(
                f"{stem}: {n} clips each, offset lead {lead:.1f}s tail {tail:.1f}s", file=sys.stderr
            )
    (MEDIA / "baseline-requests.json").write_text(json.dumps(requests))


def report() -> None:
    """Scores on both labelers, the judged mid-thought rate, and the offset spread."""
    load_env()
    config = replace(Config(), cache_mode="live")
    suffixes = {"jevcut": JEVCUT, **{name: f"-base-{name}" for name in SYSTEMS}}

    # mid_thought_rate: every shipped clip judged with the gate's questions. Flagged: the
    # judge is the one jevcut's search optimises against, which favours jevcut.
    mid = {}
    with JevClient(
        replace(config, max_requests_per_video=100_000, max_tokens_per_video=100_000_000)
    ) as client:
        for name, suffix in suffixes.items():
            flags = []
            for stem in stems():
                t = transcript_of(stem)
                _, clips = read_edl(MEDIA / f"{stem}{suffix}" / "edl.json")

                def one(c, t=t):
                    try:
                        return gate_mod.verify(client, text(t, c.t0, c.t1), config)
                    except Exception:  # noqa: BLE001
                        return None

                with ThreadPoolExecutor(config.scan_concurrency) as pool:
                    for j in pool.map(one, clips):
                        if j is not None:
                            flags.append(
                                j.nouls.get("starts_mid_thought", 0) >= config.repair_threshold
                                or j.nouls.get("ends_mid_thought", 0) >= config.repair_threshold
                            )
            mid[name] = sum(flags) / len(flags) if flags else float("nan")

    rows = []
    for name, suffix in suffixes.items():
        for label_name, labels in LABELS:
            scores, _ = evaluate.score_set(labels, suffix=suffix)
            s = evaluate.summary(scores)
            starts = [e for v in scores for e in v.start_errors]
            p90 = st.quantiles(starts, n=10)[-1] if len(starts) > 1 else float("nan")
            rows.append((name, label_name, s, sum(v.in_range for v in scores), p90))

    print(
        "| system | labels | clips | found | both edges right | P | R (chance) "
        "| start err p50 / p90 | on a negative | length | mid-thought (judged) |"
    )
    print("| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |")
    for name, label_name, s, right, p90 in rows:
        print(
            f"| {name} | {label_name} | {s['predicted']} | {s['matched']} | {right} | "
            f"{s['precision']:.2f} | {s['recall']:.2f} ({s['chance_recall']:.2f}) | "
            f"{s['start_err_median']:.1f}s / {p90:.1f}s | {s['negative_rate']:.2f} | "
            f"{s['duration_median']:.0f}s | {mid[name]:.0%} |"
        )

    # 013's gotcha: if labeled edges sit at a near-constant distance from the anchor, a
    # swept constant is near-optimal by construction and the comparison cannot discriminate.
    for label_name, labels in LABELS:
        lead, tail = [], []
        for f in Path(labels).glob("*.json"):
            label = json.loads(f.read_text())
            stem = Path(label["video"]["local_path"]).stem
            t = transcript_of(stem)
            _, clips = read_edl(MEDIA / f"{stem}{JEVCUT}" / "edl.json")
            for c in clips:
                a = t.by_id(c.anchor_id)
                for g in label["clips"]:
                    if g["start"] - 1 <= a.t0 <= g["end"]:
                        lead.append(a.t0 - g["start"])
                        tail.append(g["end"] - a.t1)
        print(
            f"\nspread, {label_name} ({len(lead)} anchors inside a labeled clip): labeled start "
            f"is {st.median(lead):.1f}s before the anchor (stdev {st.stdev(lead):.1f}s); labeled "
            f"end {st.median(tail):.1f}s after it (stdev {st.stdev(tail):.1f}s)"
        )


if __name__ == "__main__":
    {"build": build, "report": report}[sys.argv[1] if len(sys.argv) > 1 else "report"]()
