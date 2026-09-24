import itertools

import pytest

from conftest import speech
from jevcut.backends import Answer, Response
from jevcut.client import JevClient
from jevcut.config import Config
from jevcut.models import Transcript
from jevcut.questions import NO_ANCHOR, scan_questions
from jevcut.scan import (
    Anchor,
    ScanResult,
    Window,
    dedupe,
    read_scan,
    scan,
    scan_window,
    windows,
    write_scan,
)
from jevcut.transcript import segment_words


def _transcript(n_sentences: int = 200, word_s: float = 0.3) -> Transcript:
    """``word_s`` sets the speaking pace: 9 words a sentence, so 0.62 is ~6s a sentence,
    the documented 600-sentences-per-hour density."""
    text = " ".join(f"this is sentence number {i} and it ends here." for i in range(n_sentences))
    sentences = segment_words(speech(text, 0.0, word_s=word_s, gap_s=0.05))
    return Transcript(sentences=sentences, duration=sentences[-1].t1)


class ScriptedBackend:
    """Answers scan requests from a queue of (p_moment, anchor_choice) pairs."""

    name = "scripted"

    def __init__(self, script):
        self.script = list(script)
        self.calls = []

    def system_one(self, state, questions, model):
        self.calls.append((state, questions))
        p_moment, choice = self.script.pop(0) if self.script else (0.0, NO_ANCHOR)
        options = list(questions["anchor"].criteria)
        if isinstance(choice, dict):
            # A whole distribution, as Jev returned it; the pick is its top option.
            probabilities = {o: choice.get(o, 0.0) for o in options}
            choice = max(probabilities, key=probabilities.get)
        else:
            probabilities = {o: (0.6 if o == choice else 0.4 / len(options)) for o in options}
        return Response(
            model="typesafe/jev-1.13",
            answers={
                "contains_moment": Answer(type="noul", noul=p_moment),
                "anchor": Answer(
                    type="choice",
                    choice=choice,
                    confidence=0.7,
                    probabilities=probabilities,
                ),
                "kind": Answer(type="choice", choice="story", confidence=0.8),
            },
            input_tokens=1500,
        )


def _client(tmp_path, script, **overrides) -> JevClient:
    c = JevClient(Config(**overrides), run_dir=tmp_path / "run")
    c.backend = ScriptedBackend(script)
    return c


# --- windowing ----------------------------------------------------------------


def test_windows_overlap_so_a_straddling_moment_is_not_lost():
    t = _transcript(200)
    found = windows(t, Config(window_sentences=80, window_overlap_s=45.0))
    assert [w.id for w in found] == list(range(len(found)))
    assert len(found[0].sentences) == 80
    # consecutive windows share at least `window_overlap_s` seconds of speech
    shared_s = found[0].sentences[-1].t1 - found[1].sentences[0].t0
    assert shared_s >= 45.0


@pytest.mark.parametrize("word_s", [0.1, 0.3, 0.62, 1.0])
def test_overlap_holds_its_length_in_seconds_at_any_pace(word_s):
    """The recall hole this shape exists to close.

    Counted in sentences, the overlap shrinks on fast speech until it is shorter than a
    clip -- so a moment on the seam is truncated in both neighbours and nominated by
    neither. Measured in seconds it is the same insurance at any delivery.
    """
    t = _transcript(200, word_s=word_s)
    # 100 sentences so the window spans well over twice the overlap at every pace here;
    # the half-span cap has its own test below.
    found = windows(t, Config(window_sentences=100, window_overlap_s=45.0))
    assert len(found) > 1
    for a, b in itertools.pairwise(found):
        assert b.sentences[0].t0 < a.sentences[-1].t1  # they really do overlap
        assert a.sentences[-1].t1 - b.sentences[0].t0 >= 45.0


def test_a_huge_overlap_cannot_collapse_the_step():
    """A mis-set overlap should cost tokens, never a request per sentence."""
    t = _transcript(200)
    found = windows(t, Config(window_sentences=80, window_overlap_s=10_000.0))
    assert len(found) < 20


def test_every_sentence_appears_in_some_window():
    t = _transcript(200)
    covered = {sid for w in windows(t) for sid in w.line_ids}
    assert covered == {s.id for s in t.sentences}


def test_an_hour_of_video_is_about_eight_windows():
    """005's acceptance criterion, at the documented 600-sentences-per-hour density.

    The pace matters now that the step is measured in seconds, so this builds a real
    hour rather than 600 sentences of whatever length the fixture happens to produce.
    """
    t = _transcript(600, word_s=0.62)
    assert 3500 <= t.duration <= 3800  # the fixture really is an hour
    assert 7 <= len(windows(t)) <= 9


# --- question shape -----------------------------------------------------------


def test_anchor_options_include_a_no_match_escape():
    q = scan_questions(["L000", "L001"])
    assert NO_ANCHOR in q["anchor"].criteria
    assert q["anchor"].criteria["L000"] is None  # text is already in the state


def test_all_three_questions_ride_one_request():
    assert set(scan_questions(["L000"])) == {"contains_moment", "anchor", "kind"}


# --- the removal loop ---------------------------------------------------------


def test_a_flat_window_costs_exactly_one_request(tmp_path):
    client = _client(tmp_path, [(0.1, NO_ANCHOR)])
    window = Window(id=0, sentences=_transcript(20).sentences)
    assert scan_window(client, window, Config()) == []
    assert len(client.backend.calls) == 1


def test_none_of_these_stops_the_loop(tmp_path):
    client = _client(tmp_path, [(0.9, NO_ANCHOR)])
    window = Window(id=0, sentences=_transcript(20).sentences)
    assert scan_window(client, window, Config()) == []
    assert len(client.backend.calls) == 1


def test_repeat_with_removal_finds_a_second_anchor(tmp_path):
    t = _transcript(40)
    first, second = t.sentences[2].id, t.sentences[30].id
    client = _client(tmp_path, [(0.9, first), (0.8, second), (0.2, NO_ANCHOR)])
    anchors = scan_window(client, Window(id=0, sentences=t.sentences), Config())
    assert [a.sentence_id for a in anchors] == [first, second]


def test_the_winner_is_removed_from_the_next_round(tmp_path):
    t = _transcript(40)
    first = t.sentences[2].id
    client = _client(tmp_path, [(0.9, first), (0.8, t.sentences[30].id), (0.1, NO_ANCHOR)])
    scan_window(client, Window(id=0, sentences=t.sentences), Config())
    second_round_options = list(client.backend.calls[1][1]["anchor"].criteria)
    assert first not in second_round_options


def test_anchors_per_window_is_capped(tmp_path):
    t = _transcript(120)
    ids = [t.sentences[i].id for i in (2, 40, 80, 110)]
    client = _client(tmp_path, [(0.9, i) for i in ids])
    anchors = scan_window(
        client, Window(id=0, sentences=t.sentences), Config(max_anchors_per_window=3)
    )
    assert len(anchors) == 3


def test_carries_the_anchor_distribution_through(tmp_path):
    t = _transcript(20)
    client = _client(tmp_path, [(0.91, t.sentences[3].id), (0.1, NO_ANCHOR)])
    anchor = scan_window(client, Window(id=0, sentences=t.sentences), Config())[0]
    assert anchor.p_moment == 0.91
    assert anchor.anchor_probability == 0.6
    assert anchor.kind == "story"
    assert anchor.t0 == t.sentences[3].t0


# --- split votes: a moment is several lines ----------------------------------


def _split_vote(t: Transcript, none: float = 0.12) -> dict[str, float]:
    """The shape of a real window (CoderOne, 2026-09-23): the hot take's vote spread over
    four neighbouring lines, a playground-demo line far away on the single highest share."""
    ids = [s.id for s in t.sentences]
    votes = {ids[10]: 0.14, ids[12]: 0.10, ids[13]: 0.06, ids[15]: 0.06, ids[70]: 0.18}
    return {**votes, NO_ANCHOR: none}


def test_a_moment_told_over_several_lines_beats_one_louder_line(tmp_path):
    t = _transcript(80, word_s=0.4)  # ~4s a sentence, so lines 10-15 sit within 20s
    client = _client(tmp_path, [(0.91, _split_vote(t)), (0.1, NO_ANCHOR)])
    anchors = scan_window(client, Window(id=0, sentences=t.sentences), Config())
    assert anchors[0].sentence_id == t.sentences[10].id  # the stretch's own top line
    assert anchors[0].stretch_probability == pytest.approx(0.36)
    assert anchors[0].anchor_probability == 0.14


def test_none_of_these_must_beat_the_whole_stretch_not_one_line(tmp_path):
    # 18% "none" beat every single line of the moment, and used to end the window.
    t = _transcript(80, word_s=0.4)
    client = _client(tmp_path, [(0.91, _split_vote(t, none=0.18)), (0.1, NO_ANCHOR)])
    anchors = scan_window(client, Window(id=0, sentences=t.sentences), Config())
    assert [a.sentence_id for a in anchors] == [t.sentences[10].id]


def test_none_of_these_still_wins_when_it_outweighs_every_stretch(tmp_path):
    t = _transcript(80, word_s=0.4)
    client = _client(tmp_path, [(0.91, _split_vote(t, none=0.40))])
    assert scan_window(client, Window(id=0, sentences=t.sentences), Config()) == []


def test_every_line_that_voted_for_a_moment_leaves_with_it(tmp_path):
    t = _transcript(80, word_s=0.4)
    client = _client(tmp_path, [(0.91, _split_vote(t)), (0.1, NO_ANCHOR)])
    scan_window(client, Window(id=0, sentences=t.sentences), Config())
    offered = set(client.backend.calls[1][1]["anchor"].criteria)
    assert not {t.sentences[i].id for i in (10, 12, 13, 15)} & offered
    assert t.sentences[70].id in offered  # the other moment is still in the running


def test_without_a_distribution_the_pick_stands(tmp_path):
    t = _transcript(20)
    window = Window(id=0, sentences=t.sentences)
    client = _client(tmp_path, [])
    client.backend.system_one = lambda state, questions, model: Response(
        model="typesafe/jev-1.13",
        answers={
            "contains_moment": Answer(type="noul", noul=0.9),
            "anchor": Answer(type="choice", choice=t.sentences[4].id, confidence=0.5),
            "kind": Answer(type="choice", choice="story", confidence=0.8),
        },
        input_tokens=100,
    )
    anchors = scan_window(client, window, Config(max_anchors_per_window=1))
    assert [a.sentence_id for a in anchors] == [t.sentences[4].id]


# --- dedupe -------------------------------------------------------------------


def test_dedupe_keeps_the_stronger_of_a_repeated_anchor():
    a = Anchor("L010", 0, "story", 100.0, 101.0, 0.7, 0.5, 0.5)
    b = Anchor("L010", 1, "story", 100.0, 101.0, 0.9, 0.6, 0.6)
    assert dedupe([a, b]) == [b]


def test_dedupe_collapses_near_neighbours_not_distant_ones():
    a = Anchor("L010", 0, "story", 100.0, 101.0, 0.9, 0.5, 0.5)
    near = Anchor("L011", 1, "story", 105.0, 106.0, 0.8, 0.5, 0.5)
    far = Anchor("L050", 1, "story", 400.0, 401.0, 0.8, 0.5, 0.5)
    kept = dedupe([a, near, far], Config(anchor_removal_s=20.0))
    assert [x.sentence_id for x in kept] == ["L010", "L050"]


def test_dedupe_returns_anchors_in_time_order():
    out = dedupe(
        [
            Anchor("L050", 0, "story", 400.0, 401.0, 0.8, 0.5, 0.5),
            Anchor("L010", 0, "story", 100.0, 101.0, 0.9, 0.5, 0.5),
        ]
    )
    assert [a.t0 for a in out] == [100.0, 400.0]


# --- end to end ---------------------------------------------------------------


def test_scan_stays_inside_the_request_budget(tmp_path):
    """005: ~8 windows and <=24 anchors in <=12 requests for an hour of video."""
    t = _transcript(600)
    # every window yields one anchor, then reports nothing left
    client = _client(tmp_path, [(0.9, "L000")] * 0)  # script empty -> flat everywhere
    result = scan(client, t, Config())
    assert result.anchors == []
    assert result.complete, "a quiet video is not a failed scan"
    assert client.usage.requests <= 12


# --- resilience ---------------------------------------------------------------


def test_one_failing_window_does_not_discard_the_others(tmp_path):
    """pool.map re-raises the first worker exception and throws away every result behind
    it: a 5xx on the last window used to mean paying for all of them and writing none."""
    t = _transcript(200)

    class FlakyBackend:
        """Fails the first window asked, then picks whatever line it was offered."""

        name = "flaky"

        def __init__(self):
            self.calls = 0

        def system_one(self, state, questions, model):
            self.calls += 1
            if self.calls == 1:
                raise RuntimeError("upstream 503")
            offered = [o for o in questions["anchor"].criteria if o != NO_ANCHOR]
            return Response(
                model="m",
                answers={
                    "contains_moment": Answer(type="noul", noul=0.9),
                    "anchor": Answer(
                        type="choice",
                        choice=offered[0],
                        confidence=0.6,
                        probabilities={offered[0]: 1.0},
                    ),
                    "kind": Answer(type="choice", choice="story", confidence=0.8),
                },
                input_tokens=100,
            )

    config = Config(scan_concurrency=1, max_anchors_per_window=1)
    client = JevClient(config, run_dir=tmp_path / "run")
    client.backend = FlakyBackend()

    result = scan(client, t, config)
    windows_asked = len(windows(t, config))
    assert windows_asked == 3
    assert result.anchors, "surviving windows must still produce anchors"
    assert len(result.anchors) == windows_asked - 1  # every window but the failed one

    # The anchors alone cannot say the scan was partial -- that is the bug this
    # carries. The counts must come back with them.
    assert not result.complete
    assert result.windows_total == 3
    assert result.windows_failed == 1
    assert result.coverage == pytest.approx(2 / 3)
    assert len(result.failures) == 1 and "window" in result.failures[0]


def test_a_missing_answer_is_not_read_as_a_flat_window(tmp_path, caplog):
    class Broken:
        name = "broken"

        def system_one(self, state, questions, model):
            return Response(model="m", answers={}, input_tokens=10)

    client = JevClient(Config(), run_dir=tmp_path / "run")
    client.backend = Broken()
    t = _transcript(20)
    with caplog.at_level("WARNING"):
        assert scan_window(client, Window(id=0, sentences=t.sentences), Config()) == []
    assert "contains_moment" in caplog.text


def test_an_option_we_never_offered_is_logged(tmp_path, caplog):
    t = _transcript(20)
    client = _client(tmp_path, [(0.9, "L999")])  # not in this window
    with caplog.at_level("WARNING"):
        assert scan_window(client, Window(id=0, sentences=t.sentences), Config()) == []
    assert "not one of the" in caplog.text


# --- window tails and knob separation -----------------------------------------


def test_a_short_tail_window_is_folded_into_the_previous_one():
    """A trailing stub costs a whole request (~250 tokens of overhead alone) for content
    the previous window already overlaps."""
    t = _transcript(85)
    # A small overlap is what leaves a stub behind at all: at the 60s default this
    # fixture's pace puts 19 sentences in the overlap, so the tail is a real window.
    config = Config(window_sentences=80, window_overlap_s=5.0, min_tail_window=20)
    found = windows(t, config)
    assert len(found) == 1
    assert len(found[0].sentences) == 85


def test_a_substantial_tail_window_is_kept_at_full_size():
    """Kept, and ending on the last sentence with a full window's span: a partial window
    offers fewer lines, so its winner never had to beat the rest of the talk."""
    t = _transcript(120)
    found = windows(t, Config(min_tail_window=20))
    assert len(found) == 2
    assert len(found[1].sentences) == 80
    assert found[1].sentences[-1].id == t.sentences[-1].id


def test_a_transcript_shorter_than_a_window_is_one_window_as_it_is():
    # Short videos are normal; nothing pads or refuses them.
    t = _transcript(27)
    found = windows(t, Config())
    assert [len(w.sentences) for w in found] == [27]


def test_tail_merging_never_drops_or_duplicates_a_sentence():
    for n in (81, 85, 99, 100, 140, 200, 211, 600):
        t = _transcript(n)
        found = windows(t, Config())
        ids = [sid for w in found for sid in w.line_ids]
        assert set(ids) == {s.id for s in t.sentences}, n
        for w in found:
            assert len(set(w.line_ids)) == len(w.line_ids), n


def test_dedupe_radius_is_tunable_independently_of_the_removal_radius():
    a = Anchor("L010", 0, "story", 100.0, 101.0, 0.9, 0.5, 0.5)
    b = Anchor("L011", 1, "story", 110.0, 111.0, 0.8, 0.5, 0.5)
    assert len(dedupe([a, b], Config(anchor_dedupe_s=5.0, anchor_removal_s=60.0))) == 2
    assert len(dedupe([a, b], Config(anchor_dedupe_s=30.0, anchor_removal_s=1.0))) == 1


# --- the scan artifact -------------------------------------------------------


def test_a_partial_scan_survives_the_round_trip(tmp_path):
    """The counts must reach disk. Pass D reads this file, not the ScanResult."""
    result = ScanResult(
        anchors=[Anchor("L010", 0, "story", 100.0, 101.0, 0.9, 0.5, 0.5)],
        windows_total=4,
        windows_failed=3,
        failures=["window 1: HTTPError: 503"],
    )
    path = tmp_path / "anchors.json"
    write_scan(result, path)
    back = read_scan(path)

    assert back.anchors == result.anchors
    assert back.windows_total == 4
    assert back.windows_failed == 3
    assert back.coverage == pytest.approx(0.25)
    assert not back.complete
    assert back.failures == result.failures


def test_a_complete_scan_says_so(tmp_path):
    path = tmp_path / "anchors.json"
    write_scan(ScanResult(anchors=[], windows_total=7), path)
    back = read_scan(path)
    assert back.complete and back.coverage == 1.0 and back.windows_total == 7


def test_a_bare_anchor_list_is_refused_not_assumed_complete(tmp_path):
    """The old format carries no coverage, and guessing it would reintroduce the bug."""
    path = tmp_path / "anchors.json"
    path.write_text("[]")
    with pytest.raises(ValueError, match="coverage is unknown"):
        read_scan(path)
