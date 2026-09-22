"""Boundaries are set in code now -- see src/jevcut/boundaries.py and RESEARCH.md."""

import pytest

from conftest import speech
from jevcut import boundaries
from jevcut import cuts as cuts_mod
from jevcut.config import Config
from jevcut.models import CutPoint, Transcript
from jevcut.transcript import segment_words


def _transcript(n_sentences: int = 120, word_s: float = 0.35) -> Transcript:
    text = " ".join(f"this is sentence number {i} and it ends here." for i in range(n_sentences))
    sentences = segment_words(speech(text, 0.0, word_s=word_s, gap_s=0.05))
    return Transcript(sentences=sentences, duration=sentences[-1].t1)


def _placed(config: Config | None = None, at: int = 60):
    config = config or Config()
    t = _transcript()
    cuts = cuts_mod.extract(t, config)
    return t, boundaries.place(t, cuts, t.sentences[at].id, config)


# --- placement ----------------------------------------------------------------


def test_a_clip_lands_inside_the_duration_band():
    config = Config()
    _, b = _placed(config)
    assert b is not None
    low, high = config.duration_band_s
    assert low <= b.duration <= high


def test_the_anchor_sits_inside_the_clip_with_a_run_up():
    t, b = _placed()
    anchor = t.sentences[60]
    assert b.t0 < anchor.t0, "the clip must start before the anchor, not on it"
    assert b.t1 > anchor.t1, "and end after it"
    lead = (anchor.t0 - b.t0) / b.duration
    assert 0.1 < lead < 0.6, f"anchor {lead:.0%} in; should be roughly a third"


def test_an_impossible_band_drops_the_candidate_rather_than_butchering_it():
    """Returning None is a real answer -- a clip that cannot fit is not shipped short."""
    t = _transcript(n_sentences=6)
    cuts = cuts_mod.extract(t, Config())
    assert (
        boundaries.place(t, cuts, t.sentences[3].id, Config(duration_band_s=(600.0, 900.0))) is None
    )


def test_boundaries_are_cut_points_not_arbitrary_times():
    config = Config()
    t = _transcript()
    cuts = cuts_mod.extract(t, config)
    b = boundaries.place(t, cuts, t.sentences[60].id, config)
    by_id = {c.id: c for c in cuts}
    assert b.start_cut in by_id and b.end_cut in by_id
    assert b.t0 == pytest.approx(by_id[b.start_cut].t_start)
    assert b.t1 == pytest.approx(by_id[b.end_cut].t_end)


def test_a_better_kind_wins_over_a_slightly_nearer_pause():
    """A `pause` can fall inside a sentence, so it is the worst clip boundary going."""
    target = 100.0
    near_pause = CutPoint(id="C01", t=100.0, kind="pause", gap_ms=400)
    further_sentence = CutPoint(id="C02", t=101.0, kind="sentence_end", gap_ms=400)
    pick = boundaries._snap([near_pause, further_sentence], target, as_start=True)
    assert pick.id == "C02"


def test_distance_decides_once_nothing_is_near():
    far_sentence = CutPoint(id="C01", t=200.0, kind="sentence_end", gap_ms=400)
    nearer_pause = CutPoint(id="C02", t=105.0, kind="pause", gap_ms=400)
    assert boundaries._snap([far_sentence, nearer_pause], 100.0, as_start=True).id == "C02"


# --- render alignment ---------------------------------------------------------


def test_the_rendered_start_sits_in_the_silence_before_the_first_word():
    cut = CutPoint(id="C01", t=50.0, kind="sentence_end", gap_ms=2000)  # gap 49.0-51.0
    r = boundaries.align_start(cut)
    assert r == pytest.approx(cut.t_start - boundaries.SILENCE_LEAD_S)
    assert cut.t_end < r < cut.t_start, "must stay inside the gap"


def test_the_rendered_end_holds_after_the_last_word():
    cut = CutPoint(id="C01", t=50.0, kind="sentence_end", gap_ms=2000)
    r = boundaries.align_end(cut)
    assert r == pytest.approx(cut.t_end + boundaries.SILENCE_TAIL_S)
    assert cut.t_end < r < cut.t_start


def test_a_gap_too_small_to_hold_the_offset_still_never_eats_a_word():
    """The reason a constant pad is wrong: on a tight entry it clips the plosive."""
    cut = CutPoint(id="C01", t=50.0, kind="sentence_end", gap_ms=50)  # 25ms either side
    assert cut.t_end <= boundaries.align_start(cut) <= cut.t_start
    assert cut.t_end <= boundaries.align_end(cut) <= cut.t_start


def test_a_cut_with_no_gap_falls_back_to_a_constant():
    cut = CutPoint(id="C01", t=50.0, kind="shot", gap_ms=0)
    assert boundaries.align_start(cut) == pytest.approx(50.0 - boundaries.FALLBACK_LEAD_S)
    assert boundaries.align_end(cut) == pytest.approx(50.0 + boundaries.FALLBACK_TAIL_S)


def test_rendered_edges_are_never_tighter_than_the_measured_ones():
    """Alignment may only widen. 012 scores t0/t1; ffmpeg cuts the rendered pair."""
    _, b = _placed()
    assert b.render_t0 <= b.t0 and b.render_t1 >= b.t1


def test_widening_steps_to_a_real_boundary_not_just_the_nearest_cut():
    """A repair must not damage what it is fixing. Reaching back to a `pause` inside a
    sentence turns a clip that merely started early into one starting on a fragment."""
    config = Config()
    t = _transcript()
    cuts = cuts_mod.extract(t, config)
    b = boundaries.place(t, cuts, t.sentences[60].id, config)
    by_id = {c.id: c for c in cuts}

    wider = boundaries.widen(cuts, b, start=True, config=config)
    assert wider is not None
    assert by_id[wider.start_cut].kind != "pause", "widened onto a mid-sentence pause"
