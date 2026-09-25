def test_a_transcript_is_written_whole_or_not_at_all(tmp_path, monkeypatch):
    from pathlib import Path

    from jevcut.models import Transcript

    path = tmp_path / "transcript.json"
    Transcript(sentences=[], source="talk.mp4", duration=1.0).to_json(path)
    before = path.read_text()

    def killed_mid_write(self, *args, **kwargs):
        self.open("w").close()  # opening truncates, as write_text does...
        raise KeyboardInterrupt  # ...and the run dies before a byte is written

    monkeypatch.setattr(Path, "write_text", killed_mid_write)
    try:
        Transcript(sentences=[], source="other.mp4", duration=2.0).to_json(path)
    except KeyboardInterrupt:
        pass
    assert path.read_text() == before  # the old transcript survives; never an empty file
