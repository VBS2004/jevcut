"""The response cache -- 004. Its point is not money, it is that a comparison means
something: the Pass E repair loop branches on thresholds, so ordinary answer variance
sends clips down different paths and two identical runs disagree."""

import pytest
from typesafe_sdk import Noul, NoulCriteria

from jevcut.backends import Answer, Response
from jevcut.cache import CacheMiss, ResponseCache, as_cached, key_for


def _q(true_text="a point lands"):
    return {
        "worth": Noul(
            instructions="Is this worth having?",
            criteria=NoulCriteria(true=true_text, false="filler"),
        )
    }


def _response(p=0.9):
    return Response(
        model="typesafe/jev-1.13",
        answers={"worth": Answer(type="noul", noul=p, confidence=0.8)},
        input_tokens=500,
        cost_usd=0.00002,
    )


# --- the key ------------------------------------------------------------------


def test_the_key_ignores_dict_ordering():
    """Ordering leaking into the key produces misses that look exactly like the
    nondeterminism this exists to remove."""
    a = key_for("m", {"x": 1, "y": 2}, _q())
    b = key_for("m", {"y": 2, "x": 1}, _q())
    assert a == b


def test_rewording_a_question_invalidates_it():
    """There must be no way to edit a prompt and silently keep answers to the old one."""
    assert key_for("m", {"s": 1}, _q()) != key_for("m", {"s": 1}, _q("something else"))


def test_a_different_model_is_a_different_key():
    """A version bump must invalidate, not silently reuse."""
    assert key_for("jev-1.13", {"s": 1}, _q()) != key_for("jev-1.14", {"s": 1}, _q())


def test_a_different_state_is_a_different_key():
    assert key_for("m", {"s": 1}, _q()) != key_for("m", {"s": 2}, _q())


# --- storing and serving ------------------------------------------------------


def test_a_stored_answer_comes_back_intact(tmp_path):
    c = ResponseCache(tmp_path, "live")
    k = key_for("m", {"s": 1}, _q())
    assert c.get(k) is None
    c.put(k, _response(0.77))
    back = c.get(k)
    assert back is not None
    assert back.answers["worth"].noul == 0.77
    assert back.answers["worth"].confidence == 0.8
    assert c.hits == 1


def test_a_hit_costs_nothing():
    """A hit reporting its original cost would make the budget guard and the cost report
    describe a run that did not happen."""
    cached = as_cached(_response())
    assert cached.cost_usd == 0.0
    assert cached.input_tokens == 0
    assert cached.http_attempts == 0
    assert cached.answers["worth"].noul == 0.9, "the judgment itself is unchanged"


def test_replay_refuses_to_quietly_become_a_live_run(tmp_path):
    c = ResponseCache(tmp_path, "replay")
    with pytest.raises(CacheMiss, match="no cached response"):
        c.get(key_for("m", {"s": 1}, _q()))


def test_refresh_ignores_what_is_stored(tmp_path):
    k = key_for("m", {"s": 1}, _q())
    ResponseCache(tmp_path, "live").put(k, _response())
    assert ResponseCache(tmp_path, "refresh").get(k) is None


def test_off_neither_stores_nor_serves(tmp_path):
    c = ResponseCache(tmp_path, "off")
    k = key_for("m", {"s": 1}, _q())
    c.put(k, _response())
    assert c.get(k) is None
    assert not c.enabled
    assert not list(tmp_path.rglob("*.json"))


def test_an_unknown_mode_is_refused(tmp_path):
    with pytest.raises(ValueError, match="cache mode"):
        ResponseCache(tmp_path, "sometimes")
