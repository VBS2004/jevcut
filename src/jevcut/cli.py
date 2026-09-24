"""Command line entry points:

run (transcribe + clip in one), and the stages one at a time: transcribe, cuts, region,
scan, clip, smoke. The live (015-017) and eval (012) commands are not built yet.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

from jevcut import cuts as cuts_mod
from jevcut import search as search_mod
from jevcut.backends import load_env
from jevcut.client import JevClient
from jevcut.config import Config
from jevcut.edl import Clip, composite, render_clip, write_edl
from jevcut.models import Transcript
from jevcut.render import render_lines
from jevcut.scan import read_scan, scan, windows, write_scan
from jevcut.sheet import write_sheet
from jevcut.transcript import ingest, sanity_check


def _config(args: argparse.Namespace) -> Config:
    return Config.from_json(args.config) if getattr(args, "config", None) else Config()


def cmd_transcribe(args: argparse.Namespace) -> int:
    config = _config(args)
    transcript = ingest(
        args.input,
        config,
        from_json=args.from_json,
        reference=args.reference,
        model_size=args.model,
        language=args.language,
    )
    out = Path(args.out or "transcript.json")
    transcript.to_json(out)

    problems = sanity_check(transcript)
    print(f"{len(transcript)} sentences, {transcript.duration:.1f}s -> {out}")
    for p in problems:
        print(f"  warn: {p}", file=sys.stderr)
    if args.preview:
        print(render_lines(transcript.sentences[: args.preview]))
    return 0


def cmd_cuts(args: argparse.Namespace) -> int:
    config = _config(args)
    transcript = Transcript.from_json(args.transcript)
    shots = json.loads(Path(args.shots).read_text()) if args.shots else None
    found = cuts_mod.extract(transcript, config, shots=shots)

    out = Path(args.out or "cuts.json")
    out.write_text(
        json.dumps(
            [
                {
                    "id": c.id,
                    "t": c.t,
                    "t_start": round(c.t_start, 3),
                    "t_end": round(c.t_end, 3),
                    "kind": c.kind,
                    "gap_ms": c.gap_ms,
                }
                for c in found
            ],
            indent=2,
        )
    )
    stats = cuts_mod.stats(found, transcript.duration)
    print(f"{stats['count']} cut points -> {out}")
    print(
        f"  median spacing {stats['median_spacing_s']:.2f}s (target 2-4s), "
        f"max {stats['max_spacing_s']:.1f}s"
    )
    print(f"  by kind: {stats['by_kind']}")
    return 0


def cmd_region(args: argparse.Namespace) -> int:
    """Print the transcript around one anchor with every cut point it could use."""
    config = _config(args)
    transcript = Transcript.from_json(args.transcript)
    found = (
        [cuts_mod.CutPoint(**c) for c in json.loads(Path(args.cuts).read_text())]
        if args.cuts
        else cuts_mod.extract(transcript, config)
    )
    region = cuts_mod.build_region(transcript, found, args.anchor, config)
    print(f"# region {region.t0:.1f}s-{region.t1:.1f}s, {len(region.cuts)} cut options")
    print(region.text)
    return 0


def cmd_scan(args: argparse.Namespace) -> int:
    """Pass C: transcript -> anchors.json (005). Costs real requests."""
    load_env()
    config = _config(args)
    transcript = Transcript.from_json(args.transcript)
    print(f"backend: {config.backend} / {config.model}")
    print(f"{len(transcript)} sentences -> {len(windows(transcript, config))} windows")

    with JevClient(config) as client:
        result = scan(client, transcript, config)
        out = Path(args.out or "anchors.json")
        write_scan(result, out)

        summary = client.summary()
        print(f"{len(result.anchors)} anchors -> {out}")
        for a in result.anchors:
            print(
                f"  {a.sentence_id} {a.t0:7.1f}s {a.kind:12} "
                f"moment={a.p_moment:.2f} conf={a.anchor_confidence:.2f}"
            )
        print(
            f"{summary['requests']} requests, {summary['input_tokens']} tokens, "
            f"${summary['cost_usd']:.6f}"
            f"{' (reported)' if summary['cost_is_reported'] else ' (estimated)'}"
        )
        # Loud, on stdout with everything else: "0 anchors" from a dead API and
        # "0 anchors" from a boring video must not read the same.
        if not result.complete:
            print(
                f"\nINCOMPLETE: {result.windows_failed} of {result.windows_total} "
                f"windows failed ({result.coverage:.0%} covered). The anchors above "
                f"are from the rest, so treat them as a floor, not a result."
            )
            for line in result.failures:
                print(f"  {line}")
    return 0 if result.coverage else 1


def _overlap(a: Clip, b: Clip) -> float:
    inter = max(0.0, min(a.t1, b.t1) - max(a.t0, b.t0))
    union = max(a.t1, b.t1) - min(a.t0, b.t0)
    return inter / union if union > 0 else 0.0


def cmd_clip(args: argparse.Namespace) -> int:
    """transcript.json -> edl.json -> mp4s. Boundaries are set in code (see RESEARCH.md)."""
    load_env()
    config = _config(args)
    config.cache_mode = args.cache
    transcript = Transcript.from_json(args.transcript)
    found = cuts_mod.extract(transcript, config)
    print(f"{len(transcript)} sentences, {len(found)} cut points")

    if args.anchors:
        result = read_scan(args.anchors)
        print(f"{len(result.anchors)} anchors from {args.anchors}")
    else:
        with JevClient(config) as client:
            result = scan(client, transcript, config)
            print(f"{len(result.anchors)} anchors, {client.summary()['requests']} requests")
    if not result.complete:
        print(
            f"INCOMPLETE SCAN: {result.windows_failed}/{result.windows_total} windows failed "
            f"({result.coverage:.0%} covered). Clips below are a floor, not a result."
        )

    def clip_text(b) -> str:
        return " ".join(sent.text for sent in transcript.between(b.t0, b.t1))

    clips: list[Clip] = []
    requests = failed = 0
    with JevClient(config) as client:
        for anchor in result.anchors:
            # Code lists the openings and endings at real sentence boundaries; Jev judges
            # each as a clip; code keeps the best. See search.py for why this replaced
            # placing the clip by rule and repairing it by widening.
            found_clip = search_mod.search(client, transcript, found, anchor.sentence_id, config)
            requests += found_clip.requests
            failed += found_clip.failed
            if not found_clip.ok:
                print(f"  {anchor.sentence_id}: dropped -- {', '.join(found_clip.verdict.reasons)}")
                continue
            b, judgment = found_clip.boundary, found_clip.judgment

            clips.append(
                Clip(
                    id=f"clip{len(clips) + 1:03d}",
                    anchor_id=anchor.sentence_id,
                    kind=anchor.kind,
                    t0=b.t0,
                    t1=b.t1,
                    render_t0=b.render_t0,
                    render_t1=b.render_t1,
                    start_cut=b.start_cut,
                    end_cut=b.end_cut,
                    text=clip_text(b),
                    scores={
                        "p_moment": anchor.p_moment,
                        "anchor_confidence": anchor.anchor_confidence,
                        **judgment.nouls,
                        **judgment.scores,
                    },
                )
            )
            print(f"  {anchor.sentence_id}: kept ({b.duration:.0f}s)")

    print(f"gate: {requests} requests" + (f", {failed} failed and skipped" if failed else ""))

    # Boundaries move, so two anchors that were distinct can now cover the same ground.
    # This is the second dedupe; scan.dedupe already ran on the anchors themselves.
    kept: list[Clip] = []
    for c in sorted(clips, key=lambda c: -c.scores.get("p_moment", 0.0)):
        if not any(_overlap(c, k) > 0.4 for k in kept):
            kept.append(c)
    # Ranked best-first, not in time order: the point of a ranking is that the top of
    # the list is where a human should start watching.
    kept.sort(key=lambda c: -composite(c.scores))
    for i, c in enumerate(kept, start=1):
        c.id, c.rank = f"clip{i:03d}", i
        c.scores["composite"] = round(composite(c.scores), 3)

    out_dir = Path(args.out or "clips")
    out_dir.mkdir(parents=True, exist_ok=True)
    if not args.anchors:
        # So a re-run can pass --anchors and pay nothing for the scan again.
        write_scan(result, out_dir / "anchors.json")
    edl_path = out_dir / "edl.json"
    write_edl(kept, edl_path, source=args.media or "")
    print(f"\n{len(kept)} clips -> {edl_path}")
    for c in kept:
        sc = c.scores
        print(
            f"  {c.id}  {sc['composite']:.2f}  {c.t0:7.1f}-{c.t1:7.1f}s ({c.duration:4.1f}s) "
            f"hook {sc.get('hook', 0):.1f} payoff {sc.get('payoff', 0):.1f}  {c.text[:44]}"
        )

    if args.media:
        for c in kept:
            render_clip(
                args.media,
                c,
                out_dir / f"{c.id}.mp4",
                vertical=args.vertical,
                captions=transcript if args.captions else None,
            )
        print(f"rendered {len(kept)} mp4s into {out_dir}/")
    else:
        print("no --media, so nothing rendered; the EDL is enough to re-render later")
    sheet = write_sheet(kept, out_dir / "index.html", source=args.media or "")
    print(f"contact sheet -> {sheet}")
    return 0


def cmd_run(args: argparse.Namespace) -> int:
    """media -> clips in one command: transcribe, then clip, all into one directory."""
    out_dir = Path(args.out or "clips")
    out_dir.mkdir(parents=True, exist_ok=True)
    transcript = out_dir / "transcript.json"

    # ASR is the slow step and the transcript does not depend on anything downstream, so
    # an existing one is reused. Jev answers are not: those come from --cache, which keys
    # on the exact questions, so a changed question is asked again rather than replayed.
    if transcript.exists() and not args.retranscribe:
        print(f"reusing {transcript} (--retranscribe to run ASR again)")
    else:
        status = cmd_transcribe(
            argparse.Namespace(
                config=args.config,
                input=args.input,
                from_json=None,
                reference=None,
                model=args.model,
                language=args.language,
                out=str(transcript),
                preview=0,
            )
        )
        if status:
            return status

    return cmd_clip(
        argparse.Namespace(
            config=args.config,
            cache=args.cache,
            transcript=str(transcript),
            media=args.input,
            anchors=None,
            out=str(out_dir),
            vertical=args.vertical,
            captions=args.captions,
        )
    )


def cmd_eval(args: argparse.Namespace) -> int:
    """Score each labeled video's run against its labels (012). No API calls."""
    import csv
    import subprocess
    import time

    from jevcut import evaluate

    scores, skipped = evaluate.score_set(args.labels, suffix=args.suffix)
    for line in skipped:
        print(f"  skip {line}")
    if not scores:
        print("nothing to score: run `jevcut run` on the labeled videos first")
        return 1

    def row(name: str, s: dict) -> str:
        err = s["start_err_median"]
        dur, lab_dur = s["duration_median"], s["label_duration_median"]
        return (
            f"{name[:34]:34} {s['predicted']:>4} {s['labeled']:>4} "
            f"{s['matched']:>4} {s['acceptable']:>3}  "
            f"P {s['precision']:.2f}  R {s['recall']:.2f} (chance {s['chance_recall']:.2f})  "
            f"in-range {s['in_range_rate']:.2f}  on-negative {s['negative_rate']:.2f}  "
            f"start-err {'-' if err is None else f'{err:.1f}s'}  "
            f"length {'-' if dur is None else f'{dur:.0f}s'}"
            f"/{'-' if lab_dur is None else f'{lab_dur:.0f}s'}"
        )

    print(f"{'':34} pred  lab  hit  ok")
    for s in scores:
        print(row(s.video.rsplit("=", 1)[-1] + " " + s.genre, evaluate.summary([s])))
        if s.missed:
            print(f"{'':36}missed: {', '.join(s.missed)}")
    print()
    for genre in sorted({s.genre for s in scores}):
        print(row(genre, evaluate.summary([s for s in scores if s.genre == genre])))
    total = evaluate.summary(scores)
    print(row("ALL", total))

    # One row per scoring run, so a change is compared against the last one by number.
    sha = subprocess.run(
        ["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True
    ).stdout.strip()
    out = Path("eval/results/results.csv")
    out.parent.mkdir(parents=True, exist_ok=True)
    fields = ["time", "git", "note", *total]
    rows = []
    if out.exists():
        with out.open(newline="") as f:
            reader = csv.DictReader(f)
            rows = list(reader)
            # Keep any column an older version wrote, so no past number is dropped.
            fields = list(dict.fromkeys([*(reader.fieldnames or []), *fields]))
    rows.append({"time": time.strftime("%Y-%m-%d %H:%M"), "git": sha, "note": args.note, **total})
    # Rewritten whole rather than appended, so a column added later lines up with the
    # rows written before it (left blank there) instead of shifting them.
    with out.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields, restval="")
        w.writeheader()
        w.writerows(rows)
    print(f"\nappended to {out}")
    return 0


def cmd_agree(args: argparse.Namespace) -> int:
    """Two labelers of the same videos, compared: the noise floor (011). No API calls."""
    import statistics

    from jevcut import evaluate

    rows, starts, ends = [], [], []
    for path_a in sorted(Path(args.a).glob("*.json")):
        path_b = Path(args.b) / path_a.name
        if not path_b.exists():
            print(f"  skip {path_a.name}: no second label")
            continue
        la, lb = json.loads(path_a.read_text()), json.loads(path_b.read_text())
        r = evaluate.agreement(la, lb)
        starts += r["start_deltas"]
        ends += r["end_deltas"]
        rows.append(r)
        med = f"{statistics.median(r['start_deltas']):.1f}s" if r["start_deltas"] else "-"
        print(
            f"{path_a.stem:12} {la['video'].get('genre', '')[:30]:30} "
            f"A {r['a']:>2} B {r['b']:>2} "
            f"both {r['matched']:>2}  A-in-B {r['agree_a']:.2f}  B-in-A {r['agree_b']:.2f}  "
            f"start-delta {med}"
        )
    if not rows:
        return 1

    def q(xs: list[float], p: float) -> str:
        return f"{sorted(xs)[min(len(xs) - 1, int(p * len(xs)))]:.1f}s" if xs else "-"

    a_total, b_total = sum(r["a"] for r in rows), sum(r["b"] for r in rows)
    both = sum(r["matched"] for r in rows)
    print(
        f"\nALL  A {a_total}  B {b_total}  both {both}  "
        f"A-in-B {both / a_total:.2f}  B-in-A {both / b_total:.2f}"
    )
    print(f"start delta: median {q(starts, 0.5)}  p90 {q(starts, 0.9)}")
    print(f"end delta:   median {q(ends, 0.5)}  p90 {q(ends, 0.9)}")
    return 0


def cmd_smoke(args: argparse.Namespace) -> int:
    """One live Noul against the API. Confirms key, model pinning and tracing."""
    from typesafe_sdk import Noul, NoulCriteria

    load_env()
    config = _config(args)
    print(f"backend: {config.backend} / {config.model}")
    with JevClient(config) as client:
        response = client.ask(
            {"clip": {"text": args.text}},
            {
                "starts_mid_thought": Noul(
                    instructions=(
                        "Does the first sentence of `clip.text` begin in the middle of a "
                        "thought -- continuing a sentence that started earlier, or "
                        "answering a question that is not in `clip.text`?"
                    ),
                    criteria=NoulCriteria(
                        true="Opens on 'and so', 'but then', 'yeah exactly', or an answer with no question",
                        false="Opens on a complete thought of its own",
                    ),
                )
            },
            pass_name="smoke",
        )
        print(f"starts_mid_thought = {response.answers['starts_mid_thought'].noul:.3f}")
        print(f"answered by: {response.model}")
        summary = client.summary()
        print(
            f"{summary['requests']} request(s), {summary['input_tokens']} input tokens, "
            f"${summary['cost_usd']:.6f}"
        )
    return 0


def _render_flags(p: argparse.ArgumentParser) -> None:
    """Render options shared by clip and run. Both off by default, so a plain run renders
    the source frame as it is."""
    p.add_argument(
        "--vertical",
        action="store_true",
        help="centre-crop to 9:16 at 1080x1920 (no face tracking yet)",
    )
    p.add_argument(
        "--captions",
        action="store_true",
        help="burn in word-level captions from the transcript's word timings",
    )


def main(argv: list[str] | None = None) -> int:
    # Without this, library warnings reach the user through logging's fallback
    # handler as bare unlabelled lines on stderr, while the CLI prints to stdout.
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s: %(message)s")
    parser = argparse.ArgumentParser(prog="jevcut", description=__doc__)
    parser.add_argument("--config", help="path to a config JSON")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("transcribe", help="media -> transcript.json (002)")
    p.add_argument("input")
    p.add_argument("--from-json", help="use a pre-computed word list instead of ASR")
    p.add_argument("--reference", help="platform transcript to align wording to")
    p.add_argument(
        "--language",
        help="ISO code, e.g. en. Pin it: auto-detection samples the opening only, and a "
        "talk that starts on applause can be transcribed as the wrong language throughout.",
    )
    p.add_argument(
        "--model",
        default="base",
        help="whisper size: base is fast and error-prone, small/medium are better on "
        "noisy stream audio. Cached per size, so changing it re-transcribes.",
    )
    p.add_argument("--out")
    p.add_argument("--preview", type=int, default=0, help="print the first N rendered lines")
    p.set_defaults(func=cmd_transcribe)

    p = sub.add_parser("cuts", help="transcript.json -> cuts.json (003)")
    p.add_argument("transcript")
    p.add_argument("--shots", help="JSON list of shot-change times")
    p.add_argument("--out")
    p.set_defaults(func=cmd_cuts)

    p = sub.add_parser(
        "region", help="print the transcript around one anchor, cut points marked (003)"
    )
    p.add_argument("transcript")
    p.add_argument("anchor", help="sentence id, e.g. L042")
    p.add_argument("--cuts")
    p.set_defaults(func=cmd_region)

    p = sub.add_parser("scan", help="transcript.json -> anchors.json (005)")
    p.add_argument("transcript")
    p.add_argument("--out")
    p.set_defaults(func=cmd_scan)

    p = sub.add_parser("clip", help="transcript.json -> edl.json + mp4s")
    p.add_argument(
        "--cache",
        default="live",
        choices=["live", "replay", "refresh", "off"],
        help="live: call on a miss and store. replay: fail on a miss, so comparing two "
        "configs measures the change rather than answer variance. refresh: overwrite.",
    )
    p.add_argument("transcript")
    p.add_argument("--media", help="source video; without it only the EDL is written")
    p.add_argument("--anchors", help="reuse an anchors.json instead of scanning again")
    p.add_argument("--out", help="output directory (default: clips/)")
    _render_flags(p)
    p.set_defaults(func=cmd_clip)

    p = sub.add_parser("run", help="media -> ranked mp4s in one command (transcribe + clip)")
    p.add_argument("input")
    p.add_argument("--out", help="output directory (default: clips/)")
    p.add_argument("--language", help="ISO code, e.g. en; see transcribe --help")
    p.add_argument("--model", default="small", help="whisper size; see transcribe --help")
    p.add_argument(
        "--retranscribe", action="store_true", help="run ASR even if the transcript exists"
    )
    p.add_argument(
        "--cache",
        default="live",
        choices=["live", "replay", "refresh", "off"],
        help="as for clip",
    )
    _render_flags(p)
    p.set_defaults(func=cmd_run)

    p = sub.add_parser("eval", help="score runs against eval/labels-v2 (012); no API calls")
    p.add_argument("labels", nargs="?", default="eval/labels-v2")
    p.add_argument(
        "--suffix", default="-clips", help="run dir is <media stem><suffix> (default -clips)"
    )
    p.add_argument("--note", default="", help="what changed, recorded in results.csv")
    p.set_defaults(func=cmd_eval)

    p = sub.add_parser("agree", help="compare two labelers of the same videos: the noise floor")
    p.add_argument("a", nargs="?", default="eval/labels-v2")
    p.add_argument("b", nargs="?", default="eval/labels-v2-b")
    p.set_defaults(func=cmd_agree)

    p = sub.add_parser("smoke", help="one live Noul against the API (001)")
    p.add_argument("--text", default="And that's exactly why he refused to sign it.")
    p.set_defaults(func=cmd_smoke)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
