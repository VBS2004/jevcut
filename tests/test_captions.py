"""Captions: which words, re-timed how, grouped how, and escaped so libass shows them."""

from __future__ import annotations

import re

from jevcut.captions import (
    HOLD_S,
    WORD_JOINER,
    clip_words,
    escape_filter_path,
    escape_text,
    group_lines,
    layout_for,
    to_ass,
)
from jevcut.models import Sentence, Transcript, Word


def _words(*spec: tuple[str, float, float], speaker: str = "A") -> list[Word]:
    return [Word(text, t0, t1, speaker) for text, t0, t1 in spec]


def _transcript(*sentences: list[Word]) -> Transcript:
    return Transcript(
        sentences=[
            Sentence(
                id=f"L{i:03d}",
                text=" ".join(w.text for w in ws),
                t0=ws[0].t0,
                t1=ws[-1].t1,
                words=ws,
            )
            for i, ws in enumerate(sentences)
        ]
    )


def _events(ass: str) -> list[tuple[str, str, str]]:
    """(start, end, text) for every Dialogue line."""
    return [
        (m[1], m[2], m[3])
        for m in re.finditer(r"^Dialogue: 0,([^,]+),([^,]+),Default,,0,0,0,,(.*)$", ass, re.M)
    ]


# --- which words --------------------------------------------------------------


def test_words_are_rebased_to_the_clip_start():
    t = _transcript(_words(("one", 10.0, 10.4), ("two", 10.5, 10.9)))
    words = clip_words(t, 9.9, 12.0)
    assert [(w.text, round(w.t0, 3), round(w.t1, 3)) for w in words] == [
        ("one", 0.1, 0.5),
        ("two", 0.6, 1.0),
    ]


def test_words_outside_the_span_are_left_out():
    t = _transcript(
        _words(("before.", 5.0, 5.5)),
        _words(("inside", 10.0, 10.4), ("too.", 10.5, 10.9)),
        _words(("after", 13.0, 13.4)),
    )
    assert [w.text for w in clip_words(t, 9.9, 12.0)] == ["inside", "too."]


def test_a_word_cut_through_at_the_edge_goes_with_its_midpoint():
    """Mostly outside the clip means mostly unheard; mostly inside is kept, clamped."""
    t = _transcript(_words(("gone", 9.0, 10.2), ("kept", 10.4, 11.0), ("half", 11.8, 12.4)))
    words = clip_words(t, 10.0, 12.2)
    assert [w.text for w in words] == ["kept", "half"]
    assert round(words[-1].t1, 3) == 2.2  # clamped to the end of the span


def test_asr_whitespace_is_stripped_and_empty_words_dropped():
    t = _transcript(_words((" hello", 1.0, 1.2), ("  ", 1.3, 1.4), ("there\n", 1.5, 1.7)))
    assert [w.text for w in clip_words(t, 0.0, 5.0)] == ["hello", "there"]


# --- grouping -----------------------------------------------------------------


def _texts(lines: list[list[Word]]) -> list[str]:
    return [" ".join(w.text for w in line) for line in lines]


def test_lines_hold_a_few_words_and_fewer_on_a_vertical_frame():
    words = _words(*[(f"w{i}", i * 0.3, i * 0.3 + 0.25) for i in range(12)])
    landscape = group_lines(words, layout_for(1920, 1080))
    vertical = group_lines(words, layout_for(1080, 1920))
    assert [len(line) for line in landscape] == [6, 6]
    assert [len(line) for line in vertical] == [3, 3, 3, 3]


def test_a_line_ends_at_a_sentence_end_a_pause_or_a_new_speaker():
    words = [
        *_words(("Done.", 0.0, 0.3), ("Next", 0.4, 0.6), ("thing", 0.7, 0.9)),
        *_words(("later", 2.0, 2.3)),  # 1.1s pause
        *_words(("yes", 2.4, 2.6), speaker="B"),
    ]
    assert _texts(group_lines(words, layout_for(1920, 1080))) == [
        "Done.",
        "Next thing",
        "later",
        "yes",
    ]


def test_a_line_of_long_words_breaks_on_width_before_word_count():
    words = _words(("extraordinarily", 0.0, 0.5), ("complicated", 0.6, 1.0), ("x", 1.1, 1.2))
    assert _texts(group_lines(words, layout_for(1080, 1920))) == [
        "extraordinarily",
        "complicated x",
    ]


def test_the_layout_follows_the_frame():
    wide, tall = layout_for(1920, 1080), layout_for(1080, 1920)
    assert wide.font_size == round(1080 * 0.06)
    assert tall.font_size == round(1920 * 0.042)
    # Vertical sits well up the frame, clear of the platform overlay at the bottom.
    assert tall.margin_v / tall.height > wide.margin_v / wide.height


# --- the ASS file -------------------------------------------------------------


def test_the_ass_frame_matches_the_output():
    ass = to_ass([], 1080, 1920)
    assert "PlayResX: 1080\nPlayResY: 1920" in ass
    assert f"Style: Default,Arial,{round(1920 * 0.042)}," in ass
    assert _events(ass) == []


def test_one_event_per_word_with_that_word_highlighted():
    words = _words(("walk", 0.10, 0.40), ("me", 0.50, 0.70), ("through.", 0.80, 1.20))
    events = _events(to_ass(words, 1920, 1080))
    assert [(start, end) for start, end, _ in events] == [
        ("0:00:00.10", "0:00:00.50"),
        ("0:00:00.50", "0:00:00.80"),
        ("0:00:00.80", "0:00:01.70"),  # the last word holds for HOLD_S
    ]
    assert HOLD_S == 0.5
    hl = "{\\c&H00FFFF&}"
    assert events[0][2] == f"{hl}walk{{\\r}} me through."
    assert events[2][2] == f"walk me {hl}through.{{\\r}}"


def test_a_line_gives_way_to_the_next_rather_than_overlapping_it():
    words = _words(("One.", 0.0, 0.3), ("Two.", 0.5, 0.8))
    events = _events(to_ass(words, 1920, 1080))
    assert events[0][1] == events[1][0] == "0:00:00.50"


def test_shift_moves_every_event_later():
    """The render passes its pre-seek: filters see the clip start at `pre`, not zero."""
    words = _words(("hi", 0.25, 0.5))
    assert _events(to_ass(words, 1920, 1080, shift=5.0))[0][:2] == ("0:00:05.25", "0:00:06.00")


def test_timestamps_roll_over_into_minutes_and_hours():
    words = _words(("late", 3725.5, 3726.0))
    assert _events(to_ass(words, 1920, 1080))[0][0] == "1:02:05.50"


# --- escaping -----------------------------------------------------------------


def test_braces_are_escaped_so_they_are_not_an_override_block():
    assert escape_text("{laughs}") == "\\{laughs\\}"


def test_a_backslash_cannot_become_a_line_break():
    """`\\N` is a hard line break in ASS; a word joiner after the backslash defuses it."""
    assert escape_text("a\\Nb") == f"a\\{WORD_JOINER}Nb"
    assert escape_text("\\{") == f"\\{WORD_JOINER}\\{{"


def test_commas_in_words_survive_in_the_text_field():
    """Text is the last field, so commas in it are not field separators."""
    words = _words(("well,", 0.0, 0.3), ("yes", 0.4, 0.6))
    assert _events(to_ass(words, 1920, 1080))[1][2].endswith("well, {\\c&H00FFFF&}yes{\\r}")


def test_a_filter_path_is_escaped_at_both_levels():
    """Option level (\\ ' :) inside graph level (\\ ' [ ] , ;). test_edl renders
    through a directory with this name to show ffmpeg reads it back as the same path."""
    assert escape_filter_path("/tmp/a b/c.ass") == "/tmp/a b/c.ass"
    assert (
        escape_filter_path("/tmp/we ird:d'ir,[x];y/c.ass")
        == "/tmp/we ird\\\\:d\\\\\\'ir\\,\\[x\\]\\;y/c.ass"
    )
