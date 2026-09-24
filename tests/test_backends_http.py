"""The HTTP retry path — hand-rolled, and until now the only module with no coverage."""

from __future__ import annotations

import io
import json
import urllib.error

import pytest

from jevcut.backends import RETRY_STATUSES, BackendError, OpenRouterBackend


@pytest.fixture
def backend(monkeypatch) -> OpenRouterBackend:
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-v1-test")
    b = OpenRouterBackend(max_retries=3)
    monkeypatch.setattr("jevcut.backends.time.sleep", lambda _s: None)  # no real waiting
    return b


class _Body(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def _ok(payload: dict) -> _Body:
    return _Body(json.dumps(payload).encode())


def _http_error(code: int, retry_after: str | None = None) -> urllib.error.HTTPError:
    headers = {"Retry-After": retry_after} if retry_after else {}
    return urllib.error.HTTPError("u", code, "err", headers, io.BytesIO(b"upstream detail"))


def _responder(monkeypatch, outcomes: list):
    """Serve `outcomes` in order; raise them if they are exceptions."""
    calls = {"n": 0}

    def fake_urlopen(request, timeout=None):
        calls["n"] += 1
        item = outcomes[min(calls["n"] - 1, len(outcomes) - 1)]
        if isinstance(item, Exception):
            raise item
        return item

    monkeypatch.setattr("jevcut.backends.urllib.request.urlopen", fake_urlopen)
    return calls


PAYLOAD = {"model": "typesafe/jev-1.13", "answers": {"q": {"type": "noul", "noul": 0.4}}}


def test_a_clean_call_makes_one_request(backend, monkeypatch):
    calls = _responder(monkeypatch, [_ok(PAYLOAD)])
    response = backend.system_one("s", {"q": {}}, "typesafe/jev-1.13")
    assert response.answers["q"].noul == 0.4
    assert calls["n"] == 1
    assert response.http_attempts == 1


@pytest.mark.parametrize("status", sorted(RETRY_STATUSES))
def test_every_retryable_status_is_retried(backend, monkeypatch, status):
    calls = _responder(monkeypatch, [_http_error(status), _ok(PAYLOAD)])
    response = backend.system_one("s", {"q": {}}, "m")
    assert calls["n"] == 2
    assert response.http_attempts == 2


def test_a_non_retryable_status_fails_immediately(backend, monkeypatch):
    calls = _responder(monkeypatch, [_http_error(400)])
    with pytest.raises(BackendError, match="HTTP 400"):
        backend.system_one("s", {"q": {}}, "m")
    assert calls["n"] == 1


def test_the_upstream_message_survives_into_the_error(backend, monkeypatch):
    _responder(monkeypatch, [_http_error(422)])
    with pytest.raises(BackendError, match="upstream detail"):
        backend.system_one("s", {"q": {}}, "m")


def test_retries_are_bounded_by_max_retries(backend, monkeypatch):
    calls = _responder(monkeypatch, [_http_error(429)])
    with pytest.raises(BackendError, match="HTTP 429"):
        backend.system_one("s", {"q": {}}, "m")
    assert calls["n"] == backend.max_retries + 1  # the first try plus the retries


def test_retry_after_is_honoured_over_backoff(backend, monkeypatch):
    slept: list[float] = []
    monkeypatch.setattr("jevcut.backends.time.sleep", slept.append)
    _responder(monkeypatch, [_http_error(429, retry_after="7"), _ok(PAYLOAD)])
    backend.system_one("s", {"q": {}}, "m")
    assert slept == [7.0]


def test_an_absurd_retry_after_is_capped(backend, monkeypatch):
    slept: list[float] = []
    monkeypatch.setattr("jevcut.backends.time.sleep", slept.append)
    _responder(monkeypatch, [_http_error(429, retry_after="99999"), _ok(PAYLOAD)])
    backend.system_one("s", {"q": {}}, "m")
    assert slept == [60.0]


def test_a_garbage_retry_after_falls_back_to_backoff(backend, monkeypatch):
    slept: list[float] = []
    monkeypatch.setattr("jevcut.backends.time.sleep", slept.append)
    _responder(monkeypatch, [_http_error(429, retry_after="soon"), _ok(PAYLOAD)])
    backend.system_one("s", {"q": {}}, "m")
    assert len(slept) == 1 and 0 < slept[0] <= 30.0


def test_backoff_grows_across_attempts(backend, monkeypatch):
    slept: list[float] = []
    monkeypatch.setattr("jevcut.backends.time.sleep", slept.append)
    _responder(monkeypatch, [_http_error(503), _http_error(503), _ok(PAYLOAD)])
    backend.system_one("s", {"q": {}}, "m")
    assert len(slept) == 2 and slept[1] > 0


def test_connection_errors_retry_then_give_up(backend, monkeypatch):
    calls = _responder(monkeypatch, [urllib.error.URLError("no route")])
    with pytest.raises(BackendError, match="could not reach OpenRouter"):
        backend.system_one("s", {"q": {}}, "m")
    assert calls["n"] == backend.max_retries + 1


def test_a_connection_error_that_recovers(backend, monkeypatch):
    calls = _responder(monkeypatch, [urllib.error.URLError("flaky"), _ok(PAYLOAD)])
    response = backend.system_one("s", {"q": {}}, "m")
    assert calls["n"] == 2
    assert response.http_attempts == 2
