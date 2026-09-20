from jevcut import cuts as cuts_mod
from jevcut.models import CutPoint, Transcript
from jevcut.render import id_width, render_lines, render_markers
from jevcut.transcript import segment_words
from conftest import speech


def test_id_width_grows_past_a_thousand():
    assert id_width(10) == 3
    assert id_width(999) == 3
    assert id_width(1500) == 4


def test_render_lines_is_the_cookbook_form(two_sentences):
    out = render_lines(segment_words(two_sentences))
    assert out.splitlines()[0].startswith("L000| ")


def test_markers_do_not_break_sentence_ids(two_sentences):
    sentences = segment_words(two_sentences)
    t = Transcript(sentences=sentences, duration=sentences[-1].t1)
    out = render_markers(sentences, cuts_mod.extract(t))
    for s in sentences:
        assert f"{s.id}|" in out
    assert "«C00»" in out


def test_marker_lands_mid_sentence_for_an_internal_pause():
    words = speech("we paused right about here for a while", 0.0, gap_s=0.05)
    # widen the gap after the third word
    words = list(words)
    shift = 0.45  # a pause, not a sentence break
    words[3:] = [type(w)(text=w.text, t0=w.t0 + shift, t1=w.t1 + shift) for w in words[3:]]
    sentences = segment_words(words)
    cut = CutPoint(id="C00", t=(words[2].t1 + words[3].t0) / 2, kind="pause", gap_ms=2000)
    rendered = render_markers(sentences, [cut])
    line = [l for l in rendered.splitlines() if "«C00»" in l][0]
    # the marker is inside the line, not at either edge
    assert not line.endswith("«C00»")
    assert line.index("«C00»") > line.index("|")


def test_every_cut_appears_exactly_once(long_talk):
    sentences = segment_words(long_talk)
    t = Transcript(sentences=sentences, duration=sentences[-1].t1)
    found = cuts_mod.extract(t)
    out = render_markers(sentences, found)
    for c in found:
        assert out.count(f"«{c.id}»") == 1
