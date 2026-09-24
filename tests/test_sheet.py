"""The contact sheet: order, escaping, and a player only where there is a file to play."""

from __future__ import annotations

from jevcut.edl import Clip
from jevcut.sheet import write_sheet


def _clip(rank: int, text: str = "Three characters of config.", **scores) -> Clip:
    return Clip(
        id=f"clip{rank:03d}",
        anchor_id="L018",
        kind="story",
        t0=67.7,
        t1=104.8,
        render_t0=67.5,
        render_t1=105.0,
        start_cut="C03",
        end_cut="C09",
        text=text,
        scores={"composite": 0.88, "hook": 2.6, "payoff": 1.8, "standalone": 0.73, **scores},
        rank=rank,
    )


def test_clips_are_listed_by_rank(tmp_path):
    html = write_sheet([_clip(2), _clip(1)], tmp_path / "index.html").read_text()
    assert html.index('id="clip001"') < html.index('id="clip002"')
    assert "2 clips, best first" in html


def test_a_player_only_when_the_mp4_exists(tmp_path):
    (tmp_path / "clip001.mp4").write_bytes(b"")
    html = write_sheet([_clip(1), _clip(2)], tmp_path / "index.html").read_text()
    assert '<video src="clip001.mp4"' in html
    assert 'src="clip002.mp4"' not in html
    assert "not rendered" in html


def test_transcript_text_is_escaped(tmp_path):
    # Transcripts are whatever was said; a speaker can say "<script>".
    html = write_sheet([_clip(1, text='He typed <script> & "quit"')], tmp_path / "i.html")
    body = html.read_text()
    assert "<script>" not in body
    assert "&lt;script&gt; &amp; &quot;quit&quot;" in body


def test_scores_and_gate_are_shown(tmp_path):
    html = write_sheet([_clip(1, needs_the_room=0.1)], tmp_path / "index.html").read_text()
    assert "composite <b>0.88</b>" in html
    assert "hook <b>2.6</b>/3" in html
    assert "<td>needs_the_room</td><td>0.10</td>" in html
    assert "1:08&ndash;1:45 in the source" in html


def test_an_empty_run_says_so(tmp_path):
    html = write_sheet([], tmp_path / "index.html").read_text()
    assert "No clip passed the gate." in html
    assert "0 clips" in html
