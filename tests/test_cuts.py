import pytest

from jevcut import cuts as cuts_mod
from jevcut.config import Config
from jevcut.models import Transcript
from jevcut.transcript import segment_words
from conftest import speech


def _transcript(words) -> Transcript:
    sentences = segment_words(words)
    return Transcript(sentences=sentences, duration=sentences[-1].t1)


def test_sentence_ends_become_cut_points(two_sentences):
    t = _transcript(two_sentences)
    found = cuts_mod.extract(t)
    assert found
    assert all(c.id.startswith("C") for c in found)
    assert found == sorted(found, key=lambda c: c.t)


def test_cut_sits_in_the_middle_of_the_silence():
    words = speech("first part ends here.", 0.0) + speech("second part starts later.", 10.0)
    t = _transcript(words)
    found = cuts_mod.extract(t)
    first_end = t.sentences[0].t1
    second_start = t.sentences[1].t0
    mid = (first_end + second_start) / 2
    assert any(abs(c.t - mid) < 0.01 for c in found)


def test_thinning_respects_minimum_spacing(long_talk):
    config = Config(min_cut_spacing_s=2.0)
    found = cuts_mod.extract(_transcript(long_talk), config)
    spacings = [b.t - a.t for a, b in zip(found, found[1:])]
    assert all(s >= 2.0 - 1e-9 for s in spacings)


def test_speaker_change_survives_thinning(long_talk):
    found = cuts_mod.extract(_transcript(long_talk))
    assert any(c.kind == "speaker_change" for c in found)


def test_shots_are_merged_not_duplicated(two_sentences):
    t = _transcript(two_sentences)
    plain = cuts_mod.extract(t)
    near = plain[0].t + 0.05  # inside the 200ms merge window
    with_shot = cuts_mod.extract(t, shots=[near])
    assert len(with_shot) == len(plain)
    assert with_shot[0].kind == "shot"  # strongest physical signal wins the label


def test_region_numbers_cuts_locally(long_talk):
    t = _transcript(long_talk)
    found = cuts_mod.extract(t)
    region = cuts_mod.build_region(t, found, t.sentences[2].id)
    assert region.cuts[0].id == "C00"
    assert len(region.cuts) < 255
    assert region.anchor_id == t.sentences[2].id


def test_region_rejects_an_oversized_option_list(long_talk):
    t = _transcript(long_talk)
    dense = cuts_mod.extract(t, Config(min_cut_spacing_s=0.0, pause_cut_s=0.001))
    t_long = Transcript(sentences=t.sentences, duration=t.duration)
    if len(dense) > 254:
        with pytest.raises(ValueError, match="Choice option"):
            cuts_mod.build_region(t_long, dense, t.sentences[0].id, Config(region_pad_s=99999))


def test_coverage_reports_misses():
    cuts = [cuts_mod.CutPoint(id="C00", t=10.0, kind="pause")]
    result = cuts_mod.coverage(cuts, targets=[10.4, 55.0], tolerance_s=1.0)
    assert result["recall"] == 0.5
    assert result["misses"] == [55.0]


def test_stats_reports_density(long_talk):
    t = _transcript(long_talk)
    found = cuts_mod.extract(t)
    s = cuts_mod.stats(found, t.duration)
    assert s["count"] == len(found)
    assert s["median_spacing_s"] > 0
