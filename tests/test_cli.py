"""`jevcut run` wiring: which stages it calls, with what, and when it skips ASR."""

from __future__ import annotations

import json
from pathlib import Path

from jevcut import cli


def _record(monkeypatch):
    calls: dict[str, object] = {}

    def transcribe(args):
        calls["transcribe"] = args
        return 0

    def clip(args):
        calls["clip"] = args
        return 0

    monkeypatch.setattr(cli, "cmd_transcribe", transcribe)
    monkeypatch.setattr(cli, "cmd_clip", clip)
    return calls


def test_run_transcribes_then_clips_into_one_directory(tmp_path, monkeypatch):
    calls = _record(monkeypatch)
    out = tmp_path / "out"

    assert cli.main(["run", "talk.mp4", "--out", str(out), "--language", "en"]) == 0

    t = calls["transcribe"]
    assert (t.input, t.language, t.out) == ("talk.mp4", "en", str(out / "transcript.json"))
    c = calls["clip"]
    assert (c.transcript, c.media, c.out) == (str(out / "transcript.json"), "talk.mp4", str(out))
    assert c.anchors is None  # a stale scan must not be replayed; --cache handles reuse


def test_run_reuses_this_videos_transcript(tmp_path, monkeypatch):
    calls = _record(monkeypatch)
    (tmp_path / "transcript.json").write_text('{"source": "talk.mp4"}')

    assert cli.main(["run", "talk.mp4", "--out", str(tmp_path)]) == 0
    assert "transcribe" not in calls
    assert "clip" in calls


def test_run_never_cuts_one_video_on_another_videos_transcript(tmp_path, monkeypatch, capsys):
    calls = _record(monkeypatch)
    (tmp_path / "transcript.json").write_text('{"source": "other-talk.mp4"}')

    assert cli.main(["run", "talk.mp4", "--out", str(tmp_path)]) == 0
    assert "transcribe" in calls
    assert "is for other-talk.mp4, not talk.mp4" in capsys.readouterr().out


def test_run_transcribes_again_over_an_empty_transcript(tmp_path, monkeypatch, capsys):
    calls = _record(monkeypatch)
    (tmp_path / "transcript.json").write_text("")  # a run killed mid-write, before the fix

    assert cli.main(["run", "talk.mp4", "--out", str(tmp_path)]) == 0
    assert "transcribe" in calls
    assert "empty or unreadable" in capsys.readouterr().out


def test_each_video_gets_its_own_folder_by_default(tmp_path, monkeypatch):
    calls = _record(monkeypatch)
    monkeypatch.chdir(tmp_path)

    assert cli.main(["run", "media/talk.mp4"]) == 0
    assert calls["clip"].out == str(Path("clips") / "talk")


def test_run_retranscribe_forces_asr(tmp_path, monkeypatch):
    calls = _record(monkeypatch)
    (tmp_path / "transcript.json").write_text('{"source": "talk.mp4"}')

    assert cli.main(["run", "talk.mp4", "--out", str(tmp_path), "--retranscribe"]) == 0
    assert "transcribe" in calls


def test_run_stops_when_transcription_fails(tmp_path, monkeypatch):
    calls = _record(monkeypatch)
    monkeypatch.setattr(cli, "cmd_transcribe", lambda args: 3)

    assert cli.main(["run", "talk.mp4", "--out", str(tmp_path)]) == 3
    assert "clip" not in calls


def test_render_options_default_off_so_output_is_unchanged(tmp_path, monkeypatch):
    calls = _record(monkeypatch)

    assert cli.main(["clip", "t.json"]) == 0
    assert (calls["clip"].vertical, calls["clip"].captions) == (False, False)
    assert cli.main(["run", "talk.mp4", "--out", str(tmp_path)]) == 0
    assert (calls["clip"].vertical, calls["clip"].captions) == (False, False)


def test_clip_takes_the_render_options(monkeypatch):
    calls = _record(monkeypatch)

    assert cli.main(["clip", "t.json", "--media", "talk.mp4", "--vertical", "--captions"]) == 0
    assert (calls["clip"].vertical, calls["clip"].captions) == (True, True)


def test_run_passes_the_render_options_through_to_clip(tmp_path, monkeypatch):
    calls = _record(monkeypatch)

    assert cli.main(["run", "talk.mp4", "--out", str(tmp_path), "--vertical"]) == 0
    assert (calls["clip"].vertical, calls["clip"].captions) == (True, False)
    assert cli.main(["run", "talk.mp4", "--out", str(tmp_path), "--captions"]) == 0
    assert (calls["clip"].vertical, calls["clip"].captions) == (False, True)


def test_all_endings_is_off_by_default_and_run_passes_it_to_clip(tmp_path, monkeypatch):
    calls = _record(monkeypatch)

    assert cli.main(["clip", "t.json"]) == 0
    assert calls["clip"].all_endings is False  # the early stop: same clips, fewer requests
    assert cli.main(["run", "talk.mp4", "--out", str(tmp_path), "--all-endings"]) == 0
    assert calls["clip"].all_endings is True


def test_bench_reports_how_many_videos_each_version_was_scored_on(tmp_path, monkeypatch):
    from jevcut.edl import Clip, write_edl

    monkeypatch.chdir(tmp_path)

    def clip(n, t0, t1):
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
            text="hi",
            scores={"composite": 0.5},
            rank=n,
        )

    def label(stem):
        return {
            "video": {
                "url": f"u?v={stem}",
                "genre": "talk",
                "duration_s": 600.0,
                "local_path": f"media/{stem}.mp4",
            },
            "clips": [
                {
                    "id": "a",
                    "start": 100,
                    "start_range": [98, 104],
                    "end": 150,
                    "end_range": [148, 155],
                }
            ],
            "negatives": [],
        }

    (tmp_path / "eval" / "labels-v2").mkdir(parents=True)
    for stem in ("one", "two"):
        (tmp_path / "eval" / "labels-v2" / f"{stem}.json").write_text(json.dumps(label(stem)))
        run = tmp_path / "eval" / "media" / f"{stem}-clips"
        run.mkdir(parents=True)
        write_edl([clip(1, 101, 151)], run / "edl.json")

    assert cli.main(["bench", "--snapshot", "v1", "--out", "BENCHMARKS.md"]) == 0
    doc = (tmp_path / "BENCHMARKS.md").read_text()
    assert "| version | videos | clips |" in doc
    assert "| v1 | 2 | " in doc  # both labeled videos found a run
