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


def test_shots_are_merged_not_duplicated(long_talk):
    # long_talk, not two_sentences: on a 4-second transcript the two edge candidates sit
    # within the thinning window of the only sentence end and displace it.
    t = _transcript(long_talk)
    plain = cuts_mod.extract(t)
    boundary = next(c for c in plain if c.kind == "sentence_end")
    near = boundary.t + 0.05  # inside the 200ms merge window
    with_shot = cuts_mod.extract(t, shots=[near])
    assert len(with_shot) == len(plain)
    merged = next(c for c in with_shot if abs(c.t - near) < 0.2)
    assert merged.kind == "shot"  # strongest physical signal wins the label


def test_the_transcript_edges_are_always_candidates(long_talk):
    """Without these, a clip that opens on the first line is unrecoverable -- and it
    looks like a model error rather than a missing option."""
    t = _transcript(long_talk)
    found = cuts_mod.extract(t)
    assert any(abs(c.t - t.sentences[0].t0) < 1e-6 for c in found)
    assert any(abs(c.t - t.sentences[-1].t1) < 1e-6 for c in found)


def test_edges_survive_aggressive_thinning(long_talk):
    t = _transcript(long_talk)
    found = cuts_mod.extract(t, Config(min_cut_spacing_s=15.0))
    assert [c.kind for c in found].count("edge") == 2


def test_edge_coverage_lifts_recall_on_an_opening_clip(long_talk):
    """003's gating metric, on the case the edges fix."""
    t = _transcript(long_talk)
    targets = [t.sentences[0].t0, t.sentences[-1].t1]
    assert cuts_mod.coverage(cuts_mod.extract(t), targets)["recall"] == 1.0


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


def test_a_long_gap_resolves_to_the_word_not_the_midpoint():
    """The regression the gap model exists to prevent (003).

    With 8s of silence between sentences, the midpoint sits 4s from either word. A human
    labels the start at the next word, so scoring against ``t`` would report a correct
    pick as seconds early.
    """
    words = speech("first part ends here.", 0.0) + speech("second part starts later.", 10.0)
    t = _transcript(words)
    found = cuts_mod.extract(t)
    first_end, second_start = t.sentences[0].t1, t.sentences[1].t0
    cut = next(c for c in found if first_end < c.t < second_start)

    assert cut.t_end == pytest.approx(first_end, abs=0.01)
    assert cut.t_start == pytest.approx(second_start, abs=0.01)
    assert abs(cut.t - second_start) > 3.0  # what the midpoint would have cost


def test_a_cut_with_no_gap_is_already_word_anchored():
    cut = cuts_mod.CutPoint(id="C00", t=42.0, kind="shot")
    assert cut.t_start == cut.t_end == cut.t


def test_coverage_matches_the_edge_for_the_role():
    # A 2s gap: this one cut can serve a start at 12.0 or an end at 10.0.
    cut = cuts_mod.CutPoint(id="C00", t=11.0, kind="sentence_end", gap_ms=2000.0)
    assert cuts_mod.coverage([cut], [12.0], role="start")["recall"] == 1.0
    assert cuts_mod.coverage([cut], [12.0], role="end")["recall"] == 0.0
    assert cuts_mod.coverage([cut], [10.0], role="end")["recall"] == 1.0
    assert cuts_mod.coverage([cut], [10.0, 12.0], role="either")["recall"] == 1.0


def test_coverage_rejects_an_unknown_role():
    with pytest.raises(ValueError):
        cuts_mod.coverage([], [1.0], role="middle")


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
