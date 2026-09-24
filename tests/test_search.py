"""The boundary search: code lists openings and endings, Jev chooses and judges, code picks.

The stand-ins read the text they are sent: the opening chooser finds the mark placed right
before a given sentence in the rendered region, and the judge reads which sentence a
candidate ending closes on. So each test states a situation -- "the thought begins at
sentence 18" -- and checks the search gets there through the real rendering and mapping.
"""

from __future__ import annotations

import re
from types import SimpleNamespace

import pytest

from conftest import speech
from jevcut import cuts as cuts_mod
from jevcut import search as search_mod
from jevcut.config import Config
from jevcut.gate import Judgment
from jevcut.models import Transcript
from jevcut.transcript import segment_words


def _talk(n: int = 40) -> Transcript:
    # ~4.5s a sentence: "this is sentence number i and it ends here." at 0.45s a word.
    text = " ".join(f"this is sentence number {i} and it ends here." for i in range(n))
    sentences = segment_words(speech(text, 0.0, word_s=0.45, gap_s=0.05))
    return Transcript(sentences=sentences, duration=sentences[-1].t1)


def _span(text: str) -> tuple[int, int]:
    numbers = [int(n) for n in re.findall(r"sentence number (\d+)", text)]
    return numbers[0], numbers[-1]


class Chooser:
    """Answers the opening Choice with the mark rendered right before sentence ``at``, and
    puts the runner-up weight on the mark before sentence ``then``."""

    def __init__(self, at: int, *, then: int | None = None, fail: bool = False):
        self.at, self.then, self.fail, self.asked = at, then, fail, []

    def ask(self, state, questions, *, pass_name):
        self.asked.append((state, questions))
        if self.fail:
            raise RuntimeError("HTTP 529 from OpenRouter: overloaded")
        text = state["region"]["text"]

        def mark_before(n: int) -> str:
            mark = re.findall(r"«(C\d+)»", text[: text.index(f"sentence number {n} ")])[-1]
            assert mark in questions["opening"].criteria
            return mark

        weights = {mark_before(self.at): 0.7}
        if self.then is not None:
            weights[mark_before(self.then)] = 0.2
        answer = SimpleNamespace(choice=mark_before(self.at), probabilities=weights)
        return SimpleNamespace(answers={"opening": answer})


def _judge(thought_starts: int, lands_at: int, *, fails=()):
    """A judge for one moment: clean only when opened at ``thought_starts``, and paying off
    most when closed at ``lands_at``. Endings closing on a number in ``fails`` raise."""
    calls = []

    def verify(client, text, config=None):
        first, last = _span(text)
        calls.append((first, last))
        if last in fails:
            raise RuntimeError("HTTP 529 from OpenRouter: overloaded")
        return Judgment(
            nouls={
                "needs_the_room": 0.1,
                "starts_mid_thought": 0.1 if first == thought_starts else 0.9,
                "dangling_reference": 0.1,
                "ends_mid_thought": 0.1 if last >= lands_at else 0.9,
                "standalone": 0.8,
            },
            scores={"hook": 2.0, "payoff": 2.0 if last == lands_at else 1.0},
        )

    return verify, calls


@pytest.fixture
def talk():
    t = _talk()
    return t, cuts_mod.extract(t, Config())


def test_the_opening_is_the_mark_the_choice_picks(talk, monkeypatch):
    t, cuts = talk
    verify, _ = _judge(thought_starts=18, lands_at=26)
    monkeypatch.setattr(search_mod.gate_mod, "verify", verify)
    chooser = Chooser(18)
    result = search_mod.search(chooser, t, cuts, t.sentences[20].id, Config())
    assert result.ok
    assert result.boundary.t0 == pytest.approx(t.sentences[18].t0, abs=0.01)
    # One request for the opening, every candidate offered, numbered locally from C00.
    ((state, questions),) = chooser.asked
    assert next(iter(questions["opening"].criteria)) == "C00"
    assert state["region"]["moment"] == t.sentences[20].text


def test_the_region_reads_past_the_anchor_but_offers_only_openings_before_it(talk, monkeypatch):
    t, cuts = talk
    verify, _ = _judge(thought_starts=18, lands_at=26)
    monkeypatch.setattr(search_mod.gate_mod, "verify", verify)
    chooser = Chooser(18)
    search_mod.search(chooser, t, cuts, t.sentences[20].id, Config())
    ((state, questions),) = chooser.asked
    text = state["region"]["text"]
    assert "sentence number 22 " in text  # context after the moment
    assert "«" not in text[text.index("sentence number 20 ") :]  # no mark after it
    assert len(questions["opening"].criteria) == text.count("«")


def test_a_failed_opening_request_drops_the_clip_with_a_reason(talk, monkeypatch):
    t, cuts = talk
    verify, calls = _judge(thought_starts=18, lands_at=26)
    monkeypatch.setattr(search_mod.gate_mod, "verify", verify)
    result = search_mod.search(Chooser(18, fail=True), t, cuts, t.sentences[20].id, Config())
    assert not result.ok
    assert result.verdict.reasons == ["gate unavailable"]
    assert (result.requests, result.failed, calls) == (1, 1, [])


def test_the_ending_is_where_the_payoff_lands(talk, monkeypatch):
    t, cuts = talk
    verify, _ = _judge(thought_starts=18, lands_at=26)
    monkeypatch.setattr(search_mod.gate_mod, "verify", verify)
    result = search_mod.search(Chooser(18), t, cuts, t.sentences[20].id, Config())
    assert result.boundary.t1 == pytest.approx(t.sentences[26].t1, abs=0.01)
    assert result.judgment.scores["payoff"] == 2.0


def _ending_judge(ends_mid):
    """Clean opening at 18; ``ends_mid(last)`` sets how unfinished each ending reads, and
    payoff keeps rising with length, the way it does on real material."""

    def verify(client, text, config=None):
        first, last = _span(text)
        return Judgment(
            nouls={
                "needs_the_room": 0.1,
                "starts_mid_thought": 0.1 if first == 18 else 0.9,
                "dangling_reference": 0.1,
                "ends_mid_thought": ends_mid(last),
                "standalone": 0.8,
            },
            scores={"hook": 2.0, "payoff": min(2.0, 1.0 + 0.1 * last / 4)},
        )

    return verify


def test_the_shortest_finished_clip_wins_over_a_longer_bigger_payoff(talk, monkeypatch):
    t, cuts = talk
    verify = _ending_judge(lambda last: 0.1 if last >= 26 else 0.9)
    monkeypatch.setattr(search_mod.gate_mod, "verify", verify)
    result = search_mod.search(Chooser(18), t, cuts, t.sentences[20].id, Config())
    assert result.boundary.t1 == pytest.approx(t.sentences[26].t1, abs=0.01)


def test_with_no_clean_ending_the_least_unfinished_one_ships(talk, monkeypatch):
    t, cuts = talk
    # Every ending passes the gate's looser bar, none the opening's; 30 is the least bad.
    verify = _ending_judge(lambda last: 0.55 if last == 30 else 0.65)
    monkeypatch.setattr(search_mod.gate_mod, "verify", verify)
    result = search_mod.search(Chooser(18), t, cuts, t.sentences[20].id, Config())
    assert result.ok
    assert result.boundary.t1 == pytest.approx(t.sentences[30].t1, abs=0.01)


def test_the_clip_stays_in_the_band(talk, monkeypatch):
    t, cuts = talk
    verify, calls = _judge(thought_starts=18, lands_at=26)
    monkeypatch.setattr(search_mod.gate_mod, "verify", verify)
    config = Config()
    low, high = config.duration_band_s
    result = search_mod.search(Chooser(18), t, cuts, t.sentences[20].id, config)
    assert low <= result.boundary.duration <= high
    assert result.requests == len(calls) + 1  # the endings, plus the one opening Choice


def test_a_failed_request_is_skipped_not_fatal(talk, monkeypatch):
    t, cuts = talk
    verify, _ = _judge(thought_starts=18, lands_at=26, fails={27, 28})
    monkeypatch.setattr(search_mod.gate_mod, "verify", verify)
    result = search_mod.search(Chooser(18), t, cuts, t.sentences[20].id, Config())
    assert result.ok
    assert result.failed == 2


def test_every_request_failing_drops_the_clip_with_a_reason(talk, monkeypatch):
    t, cuts = talk
    verify, _ = _judge(thought_starts=18, lands_at=26, fails=set(range(40)))
    monkeypatch.setattr(search_mod.gate_mod, "verify", verify)
    result = search_mod.search(Chooser(18), t, cuts, t.sentences[20].id, Config())
    assert not result.ok
    assert result.verdict.reasons == ["gate unavailable"]


def test_no_clean_ending_is_a_drop_that_names_the_failure(talk, monkeypatch):
    t, cuts = talk
    # The payoff lands beyond anything the band can reach from this opening.
    verify, _ = _judge(thought_starts=18, lands_at=39)
    monkeypatch.setattr(search_mod.gate_mod, "verify", verify)
    result = search_mod.search(Chooser(18), t, cuts, t.sentences[20].id, Config())
    assert not result.ok
    assert "ends mid-thought" in result.verdict.reasons
