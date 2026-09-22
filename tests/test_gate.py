"""Pass E -- the check no clipper we read performs. See src/jevcut/gate.py."""

import pytest

from conftest import speech
from jevcut import boundaries, gate
from jevcut import cuts as cuts_mod
from jevcut.backends import Answer, Response
from jevcut.client import JevClient
from jevcut.config import Config
from jevcut.models import Transcript
from jevcut.transcript import segment_words


class StubBackend:
    """Answers the six verify questions from a dict of overrides."""

    name = "stub"

    def __init__(self, nouls=None, scores=None):
        self.nouls = nouls or {}
        self.scores = scores or {}
        self.states = []

    def system_one(self, state, questions, model):
        self.states.append(state)
        answers = {}
        for name, q in questions.items():
            if q.type == "noul":
                answers[name] = Answer(type="noul", noul=self.nouls.get(name, 0.05), confidence=0.8)
            else:
                answers[name] = Answer(
                    type="score",
                    score=self.scores.get(name, 2.0),
                    confidence=0.7,
                    probabilities={"0": 0.1, "1": 0.2, "2": 0.7},
                )
        return Response(model="typesafe/jev-1.13", answers=answers, input_tokens=300)


def _client(tmp_path, **kw) -> JevClient:
    c = JevClient(Config(), run_dir=tmp_path / "run")
    c.backend = StubBackend(**kw)
    return c


# --- what Jev is shown --------------------------------------------------------


def test_the_state_is_the_clip_text_and_nothing_else(tmp_path):
    """The whole mechanism: given context, the model resolves the pronoun the viewer
    cannot. Adding a title or the surrounding transcript here would break the gate."""
    client = _client(tmp_path)
    gate.verify(client, "the words inside the cut")
    state = client.backend.states[0]
    assert state == {"clip": {"text": "the words inside the cut"}}


def test_all_six_judgments_come_back(tmp_path):
    j = gate.verify(_client(tmp_path), "some clip")
    assert set(j.nouls) == {
        "starts_mid_thought",
        "ends_mid_thought",
        "dangling_reference",
        "standalone",
    }
    assert set(j.scores) == {"hook", "payoff"}


def test_score_distributions_are_kept_not_just_the_expectation(tmp_path):
    """A 1.0 can mean all weight on level 1 or a split between 0 and 2, and only the
    spread tells them apart."""
    j = gate.verify(_client(tmp_path), "some clip")
    assert j.probabilities["hook"] == {"0": 0.1, "1": 0.2, "2": 0.7}
    assert j.confidence["standalone"] == 0.8


# --- the verdict --------------------------------------------------------------


def test_a_clean_clip_passes(tmp_path):
    j = gate.verify(_client(tmp_path, nouls={"standalone": 0.95}), "x")
    assert gate.verdict(j).ok


@pytest.mark.parametrize(
    "noul,reason",
    [
        ("starts_mid_thought", "starts mid-thought"),
        ("dangling_reference", "dangling reference"),
        ("ends_mid_thought", "ends mid-thought"),
    ],
)
def test_each_defect_is_named(tmp_path, noul, reason):
    j = gate.verify(_client(tmp_path, nouls={noul: 0.9, "standalone": 0.9}), "x")
    v = gate.verdict(j)
    assert not v.ok and reason in v.reasons


def test_a_missing_setup_is_widenable_but_a_missing_payoff_is_not(tmp_path):
    """More setup fixes what came before the clip. Nothing fixes an unfinished ending."""
    before = gate.verify(
        _client(tmp_path, nouls={"dangling_reference": 0.9, "standalone": 0.9}), "x"
    )
    assert gate.verdict(before).widenable

    after = gate.verify(_client(tmp_path, nouls={"ends_mid_thought": 0.9, "standalone": 0.9}), "x")
    assert not gate.verdict(after).widenable


def test_a_clip_nobody_could_follow_fails_even_with_no_specific_defect(tmp_path):
    j = gate.verify(_client(tmp_path, nouls={"standalone": 0.1}), "x")
    v = gate.verdict(j)
    assert not v.ok and "not standalone" in v.reasons


# --- widening -----------------------------------------------------------------


def _transcript(n=120):
    text = " ".join(f"this is sentence number {i} and it ends here." for i in range(n))
    sents = segment_words(speech(text, 0.0, word_s=0.35, gap_s=0.05))
    return Transcript(sentences=sents, duration=sents[-1].t1)


def test_widening_moves_the_start_back_and_leaves_the_end_alone():
    config = Config()
    t = _transcript()
    cuts = cuts_mod.extract(t, config)
    b = boundaries.place(t, cuts, t.sentences[60].id, config)
    wider = boundaries.widen_start(cuts, b, config)
    assert wider is not None
    assert wider.t0 < b.t0
    assert wider.t1 == b.t1 and wider.end_cut == b.end_cut
    assert wider.duration > b.duration


def test_widening_refuses_to_bloat_a_clip_past_the_band():
    config = Config()
    t = _transcript()
    cuts = cuts_mod.extract(t, config)
    b = boundaries.place(t, cuts, t.sentences[60].id, config)
    tight = Config(duration_band_s=(config.duration_band_s[0], b.duration + 0.1))
    assert boundaries.widen_start(cuts, b, tight) is None


def test_widening_at_the_start_of_the_video_has_nowhere_to_go():
    config = Config()
    t = _transcript()
    cuts = cuts_mod.extract(t, config)
    b = boundaries.place(t, cuts, t.sentences[60].id, config)
    first = boundaries.Boundary(
        t0=cuts[0].t_start,
        t1=b.t1,
        render_t0=0.0,
        render_t1=b.render_t1,
        start_cut=cuts[0].id,
        end_cut=b.end_cut,
    )
    assert boundaries.widen_start(cuts, first, config) is None
