import json

import pytest

from jevcut.backends import Answer, BackendError, OpenRouterBackend, Response, parse_response
from jevcut.client import BudgetError, JevClient, estimate_tokens
from jevcut.config import Config


class FakeBackend:
    name = "fake"

    def __init__(self):
        self.calls = []

    def system_one(self, state, questions, model):
        self.calls.append((state, questions, model))
        return Response(
            model="typesafe/jev-1.13",
            answers={"q": Answer(type="noul", noul=0.81)},
            input_tokens=1234,
        )


def _client(tmp_path, **overrides) -> JevClient:
    c = JevClient(Config(**overrides), run_dir=tmp_path / "run")
    c.backend = FakeBackend()
    return c


# --- config -------------------------------------------------------------------


def test_config_round_trips(tmp_path):
    original = Config(backend="openrouter", pause_cut_s=0.4)
    path = tmp_path / "config.json"
    original.to_json(path)
    assert Config.from_json(path) == original


def test_config_rejects_unknown_keys():
    with pytest.raises(ValueError, match="unknown config keys"):
        Config.from_dict({"backend": "openrouter", "nope": 1})


def test_backend_defaults_are_pinned_versions_not_aliases():
    assert Config(backend="openrouter").model == "typesafe/jev-1.13"
    assert Config(backend="typesafe").model == "jev-1.13.0"
    assert "latest" not in Config().model


def test_explicit_model_id_wins():
    assert Config(model_id="typesafe/jev-1.14").model == "typesafe/jev-1.14"


# --- tracing and budget -------------------------------------------------------


def test_ask_traces_every_call(tmp_path):
    client = _client(tmp_path)
    client.ask({"clip": "hello"}, {"q": {"type": "noul"}}, pass_name="verify")

    lines = (client.run_dir / "trace.jsonl").read_text().splitlines()
    assert len(lines) == 1
    record = json.loads(lines[0])
    assert record["pass"] == "verify"
    assert record["backend"] == "openrouter"
    assert record["model_requested"] == "typesafe/jev-1.13"
    assert record["model_answered"] == "typesafe/jev-1.13"
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
    assert client.backend.calls[0][2] == "typesafe/jev-1.13"


def test_oversized_state_fails_before_sending(tmp_path):
    client = _client(tmp_path)
    with pytest.raises(BudgetError, match="longest question"):
        client.ask({"big": "x" * 200_000}, {"q": {}}, pass_name="scan")
    assert client.backend.calls == []


def test_request_budget_is_enforced(tmp_path):
    client = _client(tmp_path, max_requests_per_video=1)
    client.ask({"a": 1}, {"q": {}}, pass_name="scan")
    with pytest.raises(BudgetError, match="request budget"):
        client.ask({"a": 1}, {"q": {}}, pass_name="scan")


def test_failures_are_traced_too(tmp_path):
    client = _client(tmp_path)

    def boom(*a, **k):
        raise RuntimeError("429 whatever")

    client.backend.system_one = boom
    with pytest.raises(RuntimeError):
        client.ask({"a": 1}, {"q": {}}, pass_name="scan")

    record = json.loads((client.run_dir / "trace.jsonl").read_text().splitlines()[0])
    assert "429" in record["error"]


def test_token_estimate_is_in_the_right_ballpark():
    assert 20 <= estimate_tokens("x" * 100) <= 30


# --- openrouter backend -------------------------------------------------------


def test_openrouter_payload_matches_the_decisions_api(monkeypatch):
    from typesafe_sdk import Choice, Noul, NoulCriteria

    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-v1-test")
    backend = OpenRouterBackend()
    payload = backend.build_payload(
        "Help! My payouts have been failing for 3 days.",
        {
            "is_urgent": Noul(
                instructions="Does this message convey urgency?",
                criteria=NoulCriteria(
                    true="Explicitly time-sensitive", false="No urgency expressed"
                ),
            ),
            "department": Choice(
                instructions="Which team should handle this?",
                criteria={"billing": "Payments", "technical": "Bugs"},
            ),
        },
        "typesafe/jev-1.13",
    )
    assert payload["model"] == "typesafe/jev-1.13"
    assert payload["state"].startswith("Help!")
    assert payload["questions"]["is_urgent"] == {
        "type": "noul",
        "instructions": "Does this message convey urgency?",
        "criteria": {"true": "Explicitly time-sensitive", "false": "No urgency expressed"},
    }
    assert payload["questions"]["department"]["type"] == "choice"


def test_openrouter_headers(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-v1-test")
    headers = OpenRouterBackend(title="jevcut")._headers()
    assert headers["Authorization"] == "Bearer sk-or-v1-test"
    assert headers["X-Title"] == "jevcut"
    assert "HTTP-Referer" not in headers  # optional, omitted when unset


def test_missing_key_fails_with_a_useful_message(monkeypatch, tmp_path):
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.chdir(tmp_path)  # away from the repo's .env.local
    with pytest.raises(BackendError, match="OPENROUTER_API_KEY"):
        OpenRouterBackend()


def test_parse_response_reads_all_three_primitives():
    response = parse_response(
        {
            "model": "typesafe/jev-1.13",
            "usage": {"prompt_tokens": 512},
            "answers": {
                "is_urgent": {"type": "noul", "noul": 0.93},
                "department": {
                    "type": "choice",
                    "choice": "billing",
                    "confidence": 0.88,
                    "probabilities": {"billing": 0.9, "technical": 0.1},
                },
                "frustration": {"type": "score", "score": 1.4, "confidence": 0.5},
            },
        }
    )
    assert response.model == "typesafe/jev-1.13"
    assert response.input_tokens == 512
    assert response.answers["is_urgent"].noul == 0.93
    assert response.answers["department"].probabilities["billing"] == 0.9
    assert response.answers["frustration"].score == 1.4


def test_parse_response_handles_a_decision_envelope():
    response = parse_response({"decision": {"answers": {"q": {"type": "noul", "noul": 0.1}}}})
    assert response.answers["q"].noul == 0.1


def test_parse_response_rejects_a_broken_shape():
    with pytest.raises(BackendError, match="answers shape"):
        parse_response({"answers": ["not", "a", "dict"]})


# --- env loading --------------------------------------------------------------


def test_env_local_is_read_but_never_overrides_the_real_env(monkeypatch, tmp_path):
    from jevcut.backends import load_env

    (tmp_path / ".env.local").write_text("OPENROUTER_API_KEY=from-file\nOTHER=x\n")
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.delenv("OTHER", raising=False)
    load_env(tmp_path)
    import os

    assert os.environ["OPENROUTER_API_KEY"] == "from-file"

    monkeypatch.setenv("OPENROUTER_API_KEY", "from-shell")
    load_env(tmp_path)
    assert os.environ["OPENROUTER_API_KEY"] == "from-shell"


# --- cost and token accounting ------------------------------------------------


def test_reported_cost_beats_our_arithmetic(tmp_path):
    class BilledBackend(FakeBackend):
        def system_one(self, state, questions, model):
            self.calls.append((state, questions, model))
            return Response(
                model="typesafe/jev-1.13-20260917",
                answers={"q": Answer(type="noul", noul=0.5)},
                input_tokens=275,
                cost_usd=1.155e-05,
                request_id="gen-dec-123",
                provider="TypeSafe",
            )

    client = JevClient(Config(), run_dir=tmp_path / "run")
    client.backend = BilledBackend()
    client.ask({"a": 1}, {"q": {}}, pass_name="scan")

    summary = client.summary()
    assert summary["cost_usd"] == pytest.approx(1.155e-05)
    assert summary["cost_is_reported"] is True

    record = json.loads((client.run_dir / "trace.jsonl").read_text().splitlines()[0])
    assert record["request_id"] == "gen-dec-123"
    assert record["provider"] == "TypeSafe"


def test_cost_falls_back_to_arithmetic_when_unreported(tmp_path):
    client = _client(tmp_path)  # FakeBackend reports tokens but no cost
    client.ask({"a": 1}, {"q": {}}, pass_name="scan")
    assert client.summary()["cost_is_reported"] is False
    assert client.summary()["cost_usd"] == pytest.approx(1234 * 0.042 / 1e6)


def test_estimator_matches_observed_usage_within_10_percent():
    """The two live observations the constants were fitted to (issue 018's criterion)."""
    from jevcut.client import REQUEST_OVERHEAD_TOKENS

    for content_chars, reported in ((94, 275), (1532, 696)):
        predicted = REQUEST_OVERHEAD_TOKENS + estimate_tokens("x" * content_chars)
        assert abs(predicted - reported) / reported < 0.10


def test_overhead_is_counted_against_the_budget(tmp_path):
    from jevcut.client import REQUEST_OVERHEAD_TOKENS

    client = _client(tmp_path)
    estimate = client.check_budget({"a": "hello"}, {"q": {}})
    assert estimate["total"] > REQUEST_OVERHEAD_TOKENS


# --- concurrency and accounting regressions -----------------------------------


def test_the_request_budget_holds_under_concurrency(tmp_path):
    """check_budget used to read the counters outside the lock while _trace incremented
    them after the response. At 8 threads on a budget of 5, that let 12 requests through."""
    import threading
    from concurrent.futures import ThreadPoolExecutor

    class SlowBackend:
        name = "slow"

        def system_one(self, state, questions, model):
            threading.Event().wait(0.01)  # widen the check-then-act window
            return Response(model="m", answers={}, input_tokens=10)

    budget = 5
    client = JevClient(Config(max_requests_per_video=budget), run_dir=tmp_path / "run")
    client.backend = SlowBackend()

    def call(_):
        try:
            client.ask({"a": 1}, {"q": {}}, pass_name="scan")
            return True
        except BudgetError:
            return False

    with ThreadPoolExecutor(max_workers=8) as pool:
        allowed = sum(pool.map(call, range(40)))
    assert allowed == budget


def test_check_budget_does_not_consume_the_budget(tmp_path):
    client = _client(tmp_path, max_requests_per_video=1)
    for _ in range(5):
        client.check_budget({"a": 1}, {"q": {}})
    assert client.usage.requests == 0
    client.ask({"a": 1}, {"q": {}}, pass_name="scan")  # the one real request still fits


def test_a_reserved_slot_is_settled_against_reported_usage(tmp_path):
    client = _client(tmp_path)  # FakeBackend reports 1234 input tokens
    client.ask({"a": 1}, {"q": {}}, pass_name="scan")
    assert client.usage.input_tokens == 1234  # not estimate + reported


def test_mixed_cost_reporting_is_not_latched(tmp_path):
    """One response carrying usage.cost must not make the other ninety-nine free."""

    class Mixed:
        name = "mixed"
        n = 0

        def system_one(self, state, questions, model):
            Mixed.n += 1
            return Response(
                model="m",
                answers={},
                input_tokens=1000,
                cost_usd=1.155e-05 if Mixed.n == 1 else None,
            )

    client = JevClient(Config(), run_dir=tmp_path / "run")
    client.backend = Mixed()
    for _ in range(100):
        client.ask({"a": 1}, {"q": {}}, pass_name="x")

    summary = client.summary()
    assert summary["cost_usd"] == pytest.approx(1.155e-05 + 99 * 1000 * 0.042 / 1e6)
    assert summary["cost_is_partly_estimated"] is True


def test_internal_retries_are_counted_as_requests(tmp_path):
    """Requests are the binding constraint, so three HTTP calls must count as three."""

    class RetryingBackend:
        name = "retrying"

        def system_one(self, state, questions, model):
            return Response(model="m", answers={}, input_tokens=10, http_attempts=3)

    client = JevClient(Config(), run_dir=tmp_path / "run")
    client.backend = RetryingBackend()
    client.ask({"a": 1}, {"q": {}}, pass_name="scan")
    assert client.usage.requests == 3

    record = json.loads((client.run_dir / "trace.jsonl").read_text().splitlines()[0])
    assert record["http_attempts"] == 3
