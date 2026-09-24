"""Boundaries are set in code now -- see src/jevcut/boundaries.py and RESEARCH.md."""

import pytest

from conftest import speech
from jevcut import boundaries, search
from jevcut import cuts as cuts_mod
from jevcut.config import Config
from jevcut.models import CutPoint, Transcript
from jevcut.transcript import segment_words


def _transcript(n_sentences: int = 120, word_s: float = 0.35) -> Transcript:
    text = " ".join(f"this is sentence number {i} and it ends here." for i in range(n_sentences))
    sentences = segment_words(speech(text, 0.0, word_s=word_s, gap_s=0.05))
    return Transcript(sentences=sentences, duration=sentences[-1].t1)


# --- which cuts count as clip boundaries -----------------------------------------


def test_a_pause_is_never_a_clip_boundary():
    """A pause can fall mid-sentence; only kinds at or above sentence_end bound a clip."""
    good = {k for k, v in boundaries.CUT_PREFERENCE.items() if v >= 2}
    assert good == {"edge", "speaker_change", "sentence_end"}


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
    t = _transcript()
    real = search._real(cuts_mod.extract(t, Config()))
    b = search._boundary(real[10], real[20])
    assert b.render_t0 <= b.t0 and b.render_t1 >= b.t1
