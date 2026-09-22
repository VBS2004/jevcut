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

    #: High means good for these; for the rest high means a defect. A stub that
    #: defaults everything to 0.05 would mark every clip "not worth clipping".
    POSITIVE = ("standalone",)

    def __init__(self, nouls=None, scores=None):
        self.nouls = nouls or {}
        self.scores = scores or {}
        self.states = []

    def system_one(self, state, questions, model):
        self.states.append(state)
        answers = {}
        for name, q in questions.items():
            if q.type == "noul":
                default = 0.95 if name in self.POSITIVE else 0.05
                answers[name] = Answer(
                    type="noul", noul=self.nouls.get(name, default), confidence=0.8
                )
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


def test_all_seven_judgments_come_back(tmp_path):
    j = gate.verify(_client(tmp_path), "some clip")
    assert set(j.nouls) == {
        "needs_the_room",
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


# --- the verdict: worth first, then craft -------------------------------------


def test_a_clean_clip_ships(tmp_path):
    assert gate.verdict(gate.verify(_client(tmp_path), "x")).action == gate.SHIP


def test_worth_clipping_is_gone_on_purpose(tmp_path):
    """Deleted after measuring: flattest of eight questions across 38 clips (0.07
    normalised, and unbiased because it never gated, so unlike the others its spread was
    not truncated by its own rejections), never once fired in 116 drops, and two wordings
    behaved identically. It was asking the model to aggregate hook and payoff, which is
    what the composite in edl.py does in code."""
    j = gate.verify(_client(tmp_path), "x")
    assert "worth_clipping" not in j.nouls
    assert not hasattr(Config(), "worth_threshold")


@pytest.mark.parametrize(
    "noul,action,reason",
    [
        ("starts_mid_thought", gate.WIDEN_START, "starts mid-thought"),
        ("dangling_reference", gate.WIDEN_START, "dangling reference"),
        ("ends_mid_thought", gate.WIDEN_END, "ends mid-thought"),
    ],
)
def test_each_craft_defect_asks_for_the_right_edge(tmp_path, noul, action, reason):
    """Every craft failure means something the viewer needs is outside the cut, so it is
    a repair instruction, not a rejection. Which edge depends on which failure."""
    v = gate.verdict(gate.verify(_client(tmp_path, nouls={noul: 0.9}), "x"))
    assert v.action == action and reason in v.reasons and v.repairable


def test_defects_at_both_ends_widen_both(tmp_path):
    j = gate.verify(
        _client(tmp_path, nouls={"starts_mid_thought": 0.9, "ends_mid_thought": 0.9}), "x"
    )
    assert gate.verdict(j).action == gate.WIDEN_BOTH


def test_a_payoff_that_never_lands_reaches_forward(tmp_path):
    """Level 0 is "sets something up and never returns to it" -- the end arriving early,
    which more clip can fix."""
    v = gate.verdict(gate.verify(_client(tmp_path, scores={"payoff": 0.0}), "x"))
    assert v.action == gate.WIDEN_END and "payoff never lands" in v.reasons


def test_standalone_alone_does_not_say_which_edge_is_short(tmp_path):
    v = gate.verdict(gate.verify(_client(tmp_path, nouls={"standalone": 0.1}), "x"))
    assert v.action == gate.WIDEN_BOTH and "not standalone" in v.reasons


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


def test_a_middling_score_widens_while_it_can_and_ships_once_it_cannot(tmp_path):
    """Two bars, not one. These questions answer "kind of" for every excerpt, so a
    middling score is a good reason to reach further and a bad reason to discard.

    Found when a looser reject bar let a clip through before the repair loop had
    improved its opening -- the widening was doing real work, not just unblocking.
    """
    j = gate.verify(_client(tmp_path, nouls={"starts_mid_thought": 0.6}), "x")
    cfg = Config()  # repair 0.5, reject 0.75; 0.6 sits between them

    assert gate.verdict(j, cfg, repairs_left=True).action == gate.WIDEN_START
    assert gate.verdict(j, cfg).action == gate.SHIP


def test_a_bad_score_is_still_rejected_once_repairs_are_spent(tmp_path):
    j = gate.verify(_client(tmp_path, nouls={"starts_mid_thought": 0.9}), "x")
    assert gate.verdict(j, Config()).action == gate.WIDEN_START


def test_a_clip_whose_payoff_happens_in_the_room_is_dropped(tmp_path):
    """Invisible to every other question: the text resolves perfectly, and what it
    resolves into is a show of hands nobody watching later can see. Widening cannot
    bring the room along, so this is a worth failure, not a craft one."""
    j = gate.verify(_client(tmp_path, nouls={"needs_the_room": 0.85}), "x")
    v = gate.verdict(j)
    assert v.action == gate.DROP and not v.repairable
    assert "payoff happens in the room" in v.reasons


def test_the_room_check_waits_for_the_final_cut(tmp_path):
    """The room-dependent part is usually at an edge, so a clip can read high at
    placement and low once trimmed. Applied mid-repair this drops clips for material
    that was about to be removed -- it did exactly that to two good ones."""
    j = gate.verify(_client(tmp_path, nouls={"needs_the_room": 0.85}), "x")
    assert gate.verdict(j, repairs_left=True).action != gate.DROP
    assert gate.verdict(j).action == gate.DROP
