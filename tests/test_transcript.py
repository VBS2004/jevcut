from conftest import speech
from jevcut.config import Config
from jevcut.models import Transcript, Word
from jevcut.transcript import align_to_reference, sanity_check, segment_words


def test_splits_on_punctuation(two_sentences):
    sentences = segment_words(two_sentences)
    assert len(sentences) == 2
    assert sentences[0].text == "The reactor went offline."
    assert sentences[1].text == "Nobody noticed for six hours."


def test_ids_are_zero_padded_and_ordered(two_sentences):
    sentences = segment_words(two_sentences)
    assert [s.id for s in sentences] == ["L000", "L001"]


def test_bounds_match_words_exactly(long_talk):
    for s in segment_words(long_talk):
        assert s.t0 == s.words[0].t0
        assert s.t1 == s.words[-1].t1


def test_silence_forces_a_break():
    words = speech("no terminator here", 0.0) + speech("and this is after a long gap", 20.0)
    sentences = segment_words(words)
    assert len(sentences) >= 2
    assert sentences[0].text == "no terminator here"


def test_speaker_change_forces_a_break():
    words = speech("i disagree with that", 0.0, speaker="A") + speech(
        "why exactly", 2.5, speaker="B"
    )
    sentences = segment_words(words, Config(sentence_gap_s=10.0))
    assert len(sentences) == 2
    assert sentences[0].speaker == "A"
    assert sentences[1].speaker == "B"


def test_long_sentence_is_split_at_its_largest_pause():
    words = speech(" ".join(f"w{i}" for i in range(60)), 0.0, gap_s=0.01)
    # one deliberate hole in the middle
    words[30] = Word(text=words[30].text, t0=words[30].t0 + 1.2, t1=words[30].t1 + 1.2)
    sentences = segment_words(words, Config(max_sentence_words=40, sentence_gap_s=99))
    assert all(len(s.words) <= 40 for s in sentences)
    assert len(sentences) == 2


def test_align_keeps_timings_and_takes_reference_wording():
    words = speech("we use jeb for this", 0.0)
    aligned = align_to_reference(words, "we use Jev for this")
    assert [w.text for w in aligned] == ["we", "use", "Jev", "for", "this"]
    assert [w.t0 for w in aligned] == [w.t0 for w in words]


def test_align_is_a_noop_without_a_reference():
    words = speech("unchanged text here", 0.0)
    assert align_to_reference(words, "") == words


def test_sanity_check_flags_bad_density():
    # 4 sentences stretched over an hour is far below the 400-800/hour band.
    sentences = segment_words(speech("one. two. three. four.", 0.0))
    t = Transcript(sentences=sentences, duration=3600.0)
    assert any("sanity band" in p for p in sanity_check(t))
