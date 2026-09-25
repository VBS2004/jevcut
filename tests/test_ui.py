"""The reporters: plain lines for pipes and scripts, a live display for a terminal."""

from __future__ import annotations

import io
import re
from pathlib import Path
from types import SimpleNamespace

from rich.console import Console
from rich.progress import Progress

from jevcut import ui
from jevcut.edl import Clip


def _clip(n: int, t0: float, t1: float, text: str = "An opening line worth hearing.") -> Clip:
    return Clip(
        id=f"clip{n:03d}",
        anchor_id=f"L{n:03d}",
        kind="story",
        t0=t0,
        t1=t1,
        render_t0=t0,
        render_t1=t1,
        start_cut="C00",
        end_cut="C01",
        text=text,
        scores={"hook": 2.0, "payoff": 1.5, "composite": 0.8},
        rank=n,
    )


def _anchor(n: int, t0: float):
    return SimpleNamespace(sentence_id=f"L{n:03d}", t0=t0)


def test_plain_prints_the_lines_scripts_rely_on(capsys):
    r = ui.Plain()
    r.anchors(6, requests=12)
    r.dropped(_anchor(4, 40.0), ["starts mid-thought", "dangling reference"])
    r.kept(_anchor(1, 10.0), _clip(1, 10.0, 52.0))
    r.gate(38, 2)
    r.render_done(3, Path("clips"))
    r.sheet(Path("clips/index.html"))
    assert capsys.readouterr().out.splitlines() == [
        "6 anchors, 12 requests",
        "  L004: dropped -- starts mid-thought, dangling reference",
        "  L001: kept (42s)",
        "gate: 38 requests, 2 failed and skipped",
        "rendered 3 mp4s into clips/",
        "contact sheet -> clips/index.html",
    ]


def test_off_a_terminal_the_reporter_is_plain():
    # Under pytest stdout is not a terminal, which is also what a pipe or a log file sees.
    assert isinstance(ui.reporter(), ui.Plain)
    assert isinstance(ui.reporter(plain=True), ui.Plain)


def test_the_live_summary_counts_the_clips_that_ship_not_the_ones_merged(tmp_path):
    live = ui.Live()
    buf = io.StringIO()
    live.console = Console(file=buf, width=120, highlight=False)
    live.progress = Progress(console=live.console)

    live.search_begin(3)
    a, b = _clip(1, 10.0, 52.0), _clip(2, 20.0, 50.0)  # b overlaps a and is merged away
    live.kept(_anchor(1, 10.0), a)
    live.kept(_anchor(2, 20.0), b)
    live.dropped(_anchor(3, 90.0), ["promotion"])
    live.clips([a], tmp_path / "edl.json")
    live.finish(requests=40, cost=0.002, out_dir=tmp_path)

    out = buf.getvalue()
    assert re.search(r"clips shipped\s+1\b", out)
    assert re.search(r"overlaps merged\s+1\b", out)
    assert "promotion" in out and "$0.002" in out
    assert "1 clips, best first" in out
