"""`jevcut run` wiring: which stages it calls, with what, and when it skips ASR."""

from __future__ import annotations

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


def test_run_reuses_an_existing_transcript(tmp_path, monkeypatch):
    calls = _record(monkeypatch)
    (tmp_path / "transcript.json").write_text("{}")

    assert cli.main(["run", "talk.mp4", "--out", str(tmp_path)]) == 0
    assert "transcribe" not in calls
    assert "clip" in calls


def test_run_retranscribe_forces_asr(tmp_path, monkeypatch):
    calls = _record(monkeypatch)
    (tmp_path / "transcript.json").write_text("{}")

    assert cli.main(["run", "talk.mp4", "--out", str(tmp_path), "--retranscribe"]) == 0
    assert "transcribe" in calls


def test_run_stops_when_transcription_fails(tmp_path, monkeypatch):
    calls = _record(monkeypatch)
    monkeypatch.setattr(cli, "cmd_transcribe", lambda args: 3)

    assert cli.main(["run", "talk.mp4", "--out", str(tmp_path)]) == 3
    assert "clip" not in calls
