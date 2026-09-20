"""Command line entry points for the M0 subset.

Available now: transcribe (002), cuts (003), region (003), smoke (001).
The run/live/eval commands arrive with M1-M3.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from jevcut import cuts as cuts_mod
from jevcut.backends import load_env
from jevcut.client import JevClient
from jevcut.config import Config
from jevcut.models import Transcript
from jevcut.render import render_lines
from jevcut.transcript import ingest, sanity_check


def _config(args: argparse.Namespace) -> Config:
    return Config.from_json(args.config) if getattr(args, "config", None) else Config()


def cmd_transcribe(args: argparse.Namespace) -> int:
    config = _config(args)
    transcript = ingest(
        args.input, config, from_json=args.from_json, reference=args.reference
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
        json.dumps([{"id": c.id, "t": c.t, "kind": c.kind, "gap_ms": c.gap_ms} for c in found], indent=2)
    )
    stats = cuts_mod.stats(found, transcript.duration)
    print(f"{stats['count']} cut points -> {out}")
    print(f"  median spacing {stats['median_spacing_s']:.2f}s (target 2-4s), "
          f"max {stats['max_spacing_s']:.1f}s")
    print(f"  by kind: {stats['by_kind']}")
    return 0


def cmd_region(args: argparse.Namespace) -> int:
    """Print the exact Pass D state for one anchor. Useful for eyeballing wording."""
    config = _config(args)
    transcript = Transcript.from_json(args.transcript)
    found = [
        cuts_mod.CutPoint(**c) for c in json.loads(Path(args.cuts).read_text())
    ] if args.cuts else cuts_mod.extract(transcript, config)
    region = cuts_mod.build_region(transcript, found, args.anchor, config)
    print(f"# region {region.t0:.1f}s-{region.t1:.1f}s, {len(region.cuts)} cut options")
    print(region.text)
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
        print(f"{summary['requests']} request(s), {summary['input_tokens']} input tokens, "
              f"${summary['cost_usd']:.6f}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="jevcut", description=__doc__)
    parser.add_argument("--config", help="path to a config JSON")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("transcribe", help="media -> transcript.json (002)")
    p.add_argument("input")
    p.add_argument("--from-json", help="use a pre-computed word list instead of ASR")
    p.add_argument("--reference", help="platform transcript to align wording to")
    p.add_argument("--out")
    p.add_argument("--preview", type=int, default=0, help="print the first N rendered lines")
    p.set_defaults(func=cmd_transcribe)

    p = sub.add_parser("cuts", help="transcript.json -> cuts.json (003)")
    p.add_argument("transcript")
    p.add_argument("--shots", help="JSON list of shot-change times")
    p.add_argument("--out")
    p.set_defaults(func=cmd_cuts)

    p = sub.add_parser("region", help="print the Pass D state for one anchor (003)")
    p.add_argument("transcript")
    p.add_argument("anchor", help="sentence id, e.g. L042")
    p.add_argument("--cuts")
    p.set_defaults(func=cmd_region)

    p = sub.add_parser("smoke", help="one live Noul against the API (001)")
    p.add_argument("--text", default="And that's exactly why he refused to sign it.")
    p.set_defaults(func=cmd_smoke)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
