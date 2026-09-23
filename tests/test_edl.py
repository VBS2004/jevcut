"""The EDL and the render. The ffmpeg tests cut a real file and measure the result."""

import json
import subprocess

import pytest

from jevcut.edl import (
    VERTICAL_CROP,
    Clip,
    have_ffmpeg,
    probe_duration,
    probe_size,
    read_edl,
    render_clip,
    render_command,
    video_filter,
    write_edl,
)

needs_ffmpeg = pytest.mark.skipif(not have_ffmpeg(), reason="ffmpeg/ffprobe not on PATH")


def _clip(**kw) -> Clip:
    base = dict(
        id="clip001",
        anchor_id="L042",
        kind="story",
        t0=10.0,
        t1=40.0,
        render_t0=9.88,
        render_t1=40.28,
        start_cut="C05",
        end_cut="C19",
        text="a moment",
        rank=1,
    )
    return Clip(**{**base, **kw})


@pytest.fixture(scope="module")
def media(tmp_path_factory):
    """A synthetic 30s clip, so the render is tested against real frames."""
    path = tmp_path_factory.mktemp("media") / "src.mp4"
    subprocess.run(
        [
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "testsrc=duration=30:size=320x240:rate=15",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=440:duration=30",
            "-c:v",
            "libx264",
            "-preset",
            "ultrafast",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            "-shortest",
            str(path),
        ],
        check=True,
        capture_output=True,
    )
    return path


# --- the EDL ------------------------------------------------------------------


def test_an_edl_round_trips(tmp_path):
    path = tmp_path / "edl.json"
    write_edl([_clip()], path, source="video.mp4")
    source, clips = read_edl(path)
    assert source == "video.mp4"
    assert clips == [_clip()]


def test_a_hand_edited_edl_reads_back(tmp_path):
    """The point of the format: a human fixes a timestamp, a re-render obeys it."""
    path = tmp_path / "edl.json"
    write_edl([_clip()], path, source="video.mp4")
    data = json.loads(path.read_text())
    data["clips"][0]["render_t0"] = 12.5
    path.write_text(json.dumps(data))
    _, clips = read_edl(path)
    assert clips[0].render_t0 == 12.5


def test_measured_and_rendered_edges_are_both_kept(tmp_path):
    """Folding the render nudge into the measurement would flatter every eval number."""
    path = tmp_path / "edl.json"
    write_edl([_clip()], path)
    row = json.loads(path.read_text())["clips"][0]
    assert {"t0", "t1", "render_t0", "render_t1"} <= set(row)
    assert row["render_t0"] < row["t0"] and row["render_t1"] > row["t1"]


# --- the ffmpeg arguments -----------------------------------------------------


def _cmd(**kw) -> list[str]:
    return render_command("src.mp4", "out.mp4", render_t0=12.0, pre=5.0, duration=30.0, **kw)


def test_a_plain_render_has_no_filter():
    """Both options default off, so the output is what it was before they existed."""
    assert video_filter() is None
    assert "-vf" not in _cmd()


def test_the_seek_is_fast_then_accurate_whatever_the_filter():
    for vf in (None, video_filter(vertical=True)):
        cmd = _cmd(vf=vf)
        assert cmd[cmd.index("-i") - 1] == "7.000"  # fast seek, before the input
        assert cmd[cmd.index("-i") + 3] == "5.000"  # accurate seek, after it
        assert cmd[cmd.index("-t") + 1] == "30.000"


def test_vertical_crops_then_scales_to_1080x1920():
    vf = video_filter(vertical=True)
    assert vf == f"{VERTICAL_CROP},scale=1080:1920,setsar=1"
    cmd = _cmd(vf=vf)
    assert cmd[cmd.index("-vf") + 1] == vf
    assert cmd[-1] == "out.mp4"


def test_the_crop_commas_are_escaped_for_the_filtergraph():
    """An unescaped comma inside min() would split the chain into two broken filters."""
    body = VERTICAL_CROP.replace("\\,", "")
    assert "," not in body


# --- the render ---------------------------------------------------------------


@needs_ffmpeg
def test_a_rendered_clip_matches_the_edl_within_100ms(media, tmp_path):
    """009's acceptance criterion, measured rather than asserted."""
    clip = _clip(t0=8.0, t1=20.0, render_t0=7.9, render_t1=20.3)
    out = render_clip(media, clip, tmp_path / "clip001.mp4")
    assert out.exists()
    want = clip.render_t1 - clip.render_t0
    assert abs(probe_duration(out) - want) <= 0.1, "render drifted from the EDL"


@needs_ffmpeg
def test_a_clip_starting_at_zero_does_not_seek_before_the_file(media, tmp_path):
    clip = _clip(t0=0.0, t1=6.0, render_t0=0.0, render_t1=6.0)
    out = render_clip(media, clip, tmp_path / "clip000.mp4")
    assert abs(probe_duration(out) - 6.0) <= 0.1


@needs_ffmpeg
def test_a_zero_length_clip_is_refused_before_ffmpeg_runs(media, tmp_path):
    with pytest.raises(ValueError, match="no duration"):
        render_clip(media, _clip(render_t0=5.0, render_t1=5.0), tmp_path / "x.mp4")


@needs_ffmpeg
def test_a_clip_running_past_the_end_of_the_media_is_clamped(media, tmp_path):
    """Found by running the pipeline: the tail nudge on a final clip can exceed the file,
    and ffmpeg silently returns a short one, which reads downstream as a boundary error."""
    clip = _clip(t0=25.0, t1=30.0, render_t0=24.9, render_t1=31.5)  # media is 30s
    out = render_clip(media, clip, tmp_path / "tail.mp4")
    assert abs(probe_duration(out) - (30.0 - 24.9)) <= 0.1


@needs_ffmpeg
def test_a_clip_starting_past_the_end_is_refused(media, tmp_path):
    with pytest.raises(ValueError, match="no duration"):
        render_clip(media, _clip(render_t0=45.0, render_t1=50.0), tmp_path / "x.mp4")


@needs_ffmpeg
def test_a_vertical_render_is_1080x1920_and_keeps_its_length(media, tmp_path):
    clip = _clip(t0=8.0, t1=20.0, render_t0=7.9, render_t1=20.3)
    out = render_clip(media, clip, tmp_path / "v.mp4", vertical=True)
    assert probe_size(out) == (1080, 1920)
    assert abs(probe_duration(out) - (clip.render_t1 - clip.render_t0)) <= 0.1
