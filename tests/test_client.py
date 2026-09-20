import json

import pytest

from jevcut.client import BudgetError, JevClient, estimate_tokens
from jevcut.config import Config


class FakeAnswer:
    type = "noul"
    noul = 0.81
    confidence = None
    choice = None
    score = None
    probabilities = None
    legend = None


class FakeUsage:
    input_tokens = 1234
    output_tokens = 0


class FakeResponse:
    model = "jev-1.13.0"
    usage = FakeUsage()
    answers = {"q": FakeAnswer()}


class FakeSDK:
    def __init__(self):
        self.calls = []

    def system_one(self, state, questions, model=None):
        self.calls.append((state, questions, model))
        return FakeResponse()


def _client(tmp_path, **overrides) -> JevClient:
    c = JevClient(Config(**overrides), run_dir=tmp_path / "run")
    c._client = FakeSDK()
    return c


def test_config_round_trips(tmp_path):
    original = Config(model_id="jev-1.13.0", pause_cut_s=0.4)
    path = tmp_path / "config.json"
    original.to_json(path)
    assert Config.from_json(path) == original


def test_config_rejects_unknown_keys():
    with pytest.raises(ValueError, match="unknown config keys"):
        Config.from_dict({"model_id": "x", "nope": 1})


def test_ask_traces_every_call(tmp_path):
    client = _client(tmp_path)
    client.ask({"clip": "hello"}, {"q": {"type": "noul"}}, pass_name="verify")

    lines = (client.run_dir / "trace.jsonl").read_text().splitlines()
    assert len(lines) == 1
    record = json.loads(lines[0])
    assert record["pass"] == "verify"
    assert record["model_requested"] == "jev-1.13.0"
    assert record["model_answered"] == "jev-1.13.0"
    assert record["answers"]["q"]["noul"] == 0.81
    assert record["questions"] == {"q": {"type": "noul"}}
    assert record["error"] is None


def test_usage_uses_reported_tokens_not_the_estimate(tmp_path):
    client = _client(tmp_path)
    client.ask({"clip": "hello"}, {"q": {}}, pass_name="verify")
    assert client.usage.input_tokens == 1234
    assert client.summary()["cost_usd"] == pytest.approx(1234 * 0.042 / 1e6)


def test_model_is_pinned_on_the_call(tmp_path):
    client = _client(tmp_path)
    client.ask({"a": 1}, {"q": {}}, pass_name="scan")
    assert client._client.calls[0][2] == "jev-1.13.0"


def test_oversized_state_fails_before_sending(tmp_path):
    client = _client(tmp_path)
    with pytest.raises(BudgetError, match="longest question"):
        client.ask({"big": "x" * 200_000}, {"q": {}}, pass_name="scan")
    assert client._client.calls == []


def test_request_budget_is_enforced(tmp_path):
    client = _client(tmp_path, max_requests_per_video=1)
    client.ask({"a": 1}, {"q": {}}, pass_name="scan")
    with pytest.raises(BudgetError, match="request budget"):
        client.ask({"a": 1}, {"q": {}}, pass_name="scan")


def test_failures_are_traced_too(tmp_path):
    client = _client(tmp_path)

    def boom(*a, **k):
        raise RuntimeError("429 whatever")

    client._client.system_one = boom
    with pytest.raises(RuntimeError):
        client.ask({"a": 1}, {"q": {}}, pass_name="scan")

    record = json.loads((client.run_dir / "trace.jsonl").read_text().splitlines()[0])
    assert "429" in record["error"]


def test_token_estimate_is_in_the_right_ballpark():
    assert 20 <= estimate_tokens("x" * 100) <= 30
