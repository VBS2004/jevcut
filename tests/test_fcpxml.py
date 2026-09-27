"""The FCPXML export: the EDL as a timeline Premiere, Resolve or Final Cut can open.

Everything here drives `to_fcpxml`, which takes the media's facts as arguments, so the
whole document is checkable without a video file. The one test that needs ffmpeg reads a
frame rate back off a real one.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from fractions import Fraction
from pathlib import Path

import pytest

from jevcut.edl import Clip, have_ffmpeg
from jevcut.fcpxml import (
    DEFAULT_FPS,
    FCPXML_VERSION,
    NAME_CHARS,
    _timecode,
    clip_name,
    probe_frame_rate,
    to_fcpxml,
)

needs_ffmpeg = pytest.mark.skipif(not have_ffmpeg(), reason="ffmpeg/ffprobe not on PATH")

NTSC = Fraction(30000, 1001)  # 29.97: the rate that punishes anyone who rounds it
PAL = Fraction(25)


def _clip(**kw) -> Clip:
    base = dict(
        id="clip001",
        anchor_id="L042",
        kind="story",
        t0=10.0,
        t1=40.0,
        render_t0=9.88,
        render_t1=40.28,
        start_cut="sentence",
        end_cut="sentence",
        text="A claim worth clipping.",
        scores={"hook": 3.0, "payoff": 2.0},
        rank=1,
    )
    return Clip(**{**base, **kw})


def _document(clips: list[Clip], **kw) -> ET.Element:
    defaults = dict(fps=PAL, size=(1920, 1080), duration=600.0)
    xml = to_fcpxml(clips, "/media/talk.mp4", **{**defaults, **kw})
    return ET.fromstring(xml)


# -- times on the frame grid ----------------------------------------------------------


def test_a_time_is_a_rational_on_the_frame_grid() -> None:
    # 12.0s is not a whole number of 29.97 frames: frame 360 is 12.012s, and that is
    # what the file must say. A decimal "12s" is what importers reject or silently move.
    assert _timecode(12.0, 1 / NTSC) == "3003/250s"
    assert Fraction(3003, 250) == 360 * (1 / NTSC)


def test_a_whole_second_on_a_whole_rate_has_no_denominator() -> None:
    assert _timecode(12.0, 1 / PAL) == "12s"
    assert _timecode(0.0, 1 / PAL) == "0s"


def test_times_round_to_the_nearest_frame_not_toward_zero() -> None:
    frame = 1 / PAL  # 0.04s
    assert _timecode(0.039, frame) == "1/25s"  # 0.975 frames rounds up to 1
    assert _timecode(0.019, frame) == "0s"  # 0.475 frames rounds down to 0


def test_the_declared_frame_duration_matches_the_rate() -> None:
    root = _document([_clip()], fps=NTSC)
    assert root.find(".//format").get("frameDuration") == "1001/30000s"


# -- document shape -------------------------------------------------------------------


def test_the_document_is_well_formed_fcpxml() -> None:
    xml = to_fcpxml([_clip()], "/media/talk.mp4", fps=PAL, size=(1920, 1080), duration=600.0)
    assert xml.startswith('<?xml version="1.0" encoding="UTF-8"?>\n<!DOCTYPE fcpxml>')
    root = ET.fromstring(xml)
    assert root.tag == "fcpxml" and root.get("version") == FCPXML_VERSION
    assert root.find("resources/format") is not None
    assert root.find("resources/asset/media-rep") is not None


def test_each_clip_becomes_its_own_project() -> None:
    # One clip, one sequence: each ships as its own Short, so a single timeline holding
    # all of them would just be something to cut apart again.
    clips = [_clip(id="a", rank=1), _clip(id="b", rank=2), _clip(id="c", rank=3)]
    projects = _document(clips).findall(".//project")
    assert len(projects) == 3
    assert [p.get("name")[:2] for p in projects] == ["01", "02", "03"]
    for project in projects:
        assert len(project.findall("sequence/spine/asset-clip")) == 1


def test_the_timeline_points_at_the_source_not_the_rendered_clip() -> None:
    # The whole reason to emit this: an editor who wants two more seconds at the head
    # drags for them. A timeline built from the mp4s has no handles to drag.
    root = _document([_clip()])
    src = root.find("resources/media-rep") or root.find(".//media-rep")
    assert src.get("src").endswith("/talk.mp4")
    assert len(root.findall("resources/asset")) == 1
    assert root.find(".//asset-clip").get("ref") == root.find("resources/asset").get("id")


def test_a_clip_spans_its_render_times_not_its_measured_ones() -> None:
    # render_* is what ffmpeg cuts, so the timeline and the mp4s agree.
    clip = _clip(t0=10.0, t1=40.0, render_t0=9.88, render_t1=40.28)
    asset_clip = _document([clip], fps=PAL).find(".//asset-clip")
    assert asset_clip.get("start") == _timecode(9.88, 1 / PAL)
    assert asset_clip.get("duration") == _timecode(40.28 - 9.88, 1 / PAL)


def test_the_measured_boundary_rides_along_as_a_marker() -> None:
    clip = _clip(t0=10.0, render_t0=9.88, start_cut="pause")
    marker = _document([clip], fps=PAL).find(".//marker")
    assert marker.get("start") == _timecode(10.0 - 9.88, 1 / PAL)
    assert "pause" in marker.get("value")


def test_no_marker_when_the_measured_edge_is_the_render_edge() -> None:
    # A marker at 0s on every clip is noise, not information.
    clip = _clip(t0=9.88, render_t0=9.88)
    assert _document([clip], fps=PAL).find(".//marker") is None


def test_the_clip_text_rides_along_as_a_note() -> None:
    clip = _clip(text="  The thing   nobody tells you.  ")
    assert _document([clip]).find(".//note").text == "The thing nobody tells you."


def test_an_empty_text_writes_no_note() -> None:
    assert _document([_clip(text="   ")]).find(".//note") is None


# -- staying inside the media ----------------------------------------------------------


def test_a_clip_nudged_past_the_end_is_clamped_to_the_asset() -> None:
    # A clip on the last sentence has its tail nudged past the final word. An asset-clip
    # claiming media the asset does not have is the one error importers cannot recover.
    clip = _clip(render_t0=595.0, render_t1=640.0)
    asset_clip = _document([clip], duration=600.0, fps=PAL).find(".//asset-clip")
    assert asset_clip.get("duration") == _timecode(5.0, 1 / PAL)


def test_a_clip_starting_past_the_end_collapses_rather_than_going_negative() -> None:
    clip = _clip(render_t0=700.0, render_t1=760.0)
    asset_clip = _document([clip], duration=600.0, fps=PAL).find(".//asset-clip")
    assert asset_clip.get("duration") == "0s"


# -- names and paths --------------------------------------------------------------------


def test_a_name_leads_with_the_rank_then_the_clip_s_own_words() -> None:
    assert clip_name(_clip(rank=3, text="Compilers are mostly bookkeeping.")).startswith(
        "03 Compilers are mostly"
    )


def test_a_long_name_is_truncated_for_the_bin_column() -> None:
    name = clip_name(_clip(text="word " * 60))
    assert len(name) <= NAME_CHARS + 3 and name.endswith("…")


def test_a_clip_with_no_text_falls_back_to_its_id() -> None:
    assert clip_name(_clip(id="clip042", text="", rank=7)) == "07 clip042"


def test_a_path_with_spaces_becomes_a_valid_file_url() -> None:
    # A hand-built "file://" + path gets Windows drive letters and spaces wrong.
    xml = to_fcpxml(
        [_clip()], Path("/media/a talk.mp4"), fps=PAL, size=(1920, 1080), duration=600.0
    )
    src = ET.fromstring(xml).find(".//media-rep").get("src")
    assert src.startswith("file:///") and "%20" in src and " " not in src


def test_an_audioless_source_does_not_promise_an_audio_stream() -> None:
    root = _document([_clip()], has_audio=False)
    assert root.find("resources/asset").get("hasAudio") is None


# -- probing a real file -------------------------------------------------------------


@needs_ffmpeg
def test_the_frame_rate_comes_back_exact(tmp_path: Path) -> None:
    import subprocess

    media = tmp_path / "clip.mp4"
    subprocess.run(
        ["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "testsrc=size=320x240:rate=30000/1001",
         "-t", "1", "-pix_fmt", "yuv420p", str(media)],
        check=True,
    )
    # Exact, not 29.97: rounding here puts every later timecode a frame further out.
    assert probe_frame_rate(media) == Fraction(30000, 1001)


@needs_ffmpeg
def test_an_unreadable_rate_falls_back_rather_than_crashing(tmp_path: Path) -> None:
    silent = tmp_path / "audio.m4a"
    import subprocess

    subprocess.run(
        ["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo",
         "-t", "1", str(silent)],
        check=True,
    )
    # ffprobe exits 0 with empty output when there is no video stream, so there is
    # nothing to parse. A usable grid beats a crash: the caller still gets a document.
    assert probe_frame_rate(silent) == DEFAULT_FPS
