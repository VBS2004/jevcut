import pytest

from jevcut.backends import Answer, Response
from jevcut.client import JevClient
from jevcut.config import Config
from jevcut.models import Transcript
from jevcut.questions import NO_ANCHOR, scan_questions
from jevcut.scan import dedupe, scan, scan_window, windows, Anchor, Window
from jevcut.transcript import segment_words
from conftest import speech


def _transcript(n_sentences: int = 200) -> Transcript:
    text = " ".join(f"this is sentence number {i} and it ends here." for i in range(n_sentences))
    sentences = segment_words(speech(text, 0.0, word_s=0.3, gap_s=0.05))
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
        return Response(
            model="typesafe/jev-1.13",
            answers={
                "contains_moment": Answer(type="noul", noul=p_moment),
                "anchor": Answer(
                    type="choice",
                    choice=choice,
                    confidence=0.7,
                    probabilities={o: (0.6 if o == choice else 0.4 / len(options)) for o in options},
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
    found = windows(t, Config(window_sentences=80, window_overlap=10))
    assert [w.id for w in found] == list(range(len(found)))
    assert len(found[0].sentences) == 80
    # consecutive windows share exactly `overlap` sentences
    shared = set(found[0].line_ids) & set(found[1].line_ids)
    assert len(shared) == 10


def test_every_sentence_appears_in_some_window():
    t = _transcript(200)
    covered = {sid for w in windows(t) for sid in w.line_ids}
    assert covered == {s.id for s in t.sentences}


def test_an_hour_of_video_is_about_eight_windows():
    """005's acceptance criterion, at the documented 600-sentences-per-hour density."""
    t = _transcript(600)
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
    anchors = scan_window(client, Window(id=0, sentences=t.sentences), Config(max_anchors_per_window=3))
    assert len(anchors) == 3


def test_carries_the_anchor_distribution_through(tmp_path):
    t = _transcript(20)
    client = _client(tmp_path, [(0.91, t.sentences[3].id), (0.1, NO_ANCHOR)])
    anchor = scan_window(client, Window(id=0, sentences=t.sentences), Config())[0]
    assert anchor.p_moment == 0.91
    assert anchor.anchor_probability == 0.6
    assert anchor.kind == "story"
    assert anchor.t0 == t.sentences[3].t0


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
    out = dedupe([
        Anchor("L050", 0, "story", 400.0, 401.0, 0.8, 0.5, 0.5),
        Anchor("L010", 0, "story", 100.0, 101.0, 0.9, 0.5, 0.5),
    ])
    assert [a.t0 for a in out] == [100.0, 400.0]


# --- end to end ---------------------------------------------------------------


def test_scan_stays_inside_the_request_budget(tmp_path):
    """005: ~8 windows and <=24 anchors in <=12 requests for an hour of video."""
    t = _transcript(600)
    # every window yields one anchor, then reports nothing left
    client = _client(tmp_path, [(0.9, "L000")] * 0)  # script empty -> flat everywhere
    anchors = scan(client, t, Config())
    assert anchors == []
    assert client.usage.requests <= 12
