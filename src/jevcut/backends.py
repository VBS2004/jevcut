"""Where the questions actually get sent.

Jev is reachable two ways and the rest of jevcut should not care which is in use:

* **OpenRouter** -- ``POST /api/alpha/decisions`` with ``typesafe/jev-1.13``. Plain HTTP,
  so this backend has no dependency beyond the standard library.
* **TypeSafe direct** -- the ``typesafe-sdk`` client.

Both return the same normalized :class:`Response`, so passes, tracing and budgeting are
written once. The question payloads are identical either way: the SDK's ``model_dump()``
already produces the exact JSON shape the Decisions API documents.
"""

from __future__ import annotations

import json
import os
import random
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field, fields
from pathlib import Path
from typing import Any, Protocol

OPENROUTER_URL = "https://openrouter.ai/api/alpha/decisions"
BACKEND_DEFAULT_MODEL = {
    # Both are pinned versions, not floating aliases: a threshold tuned against one
    # version is not valid on the next, and an alias can move underneath you.
    "openrouter": "typesafe/jev-1.13",
    "typesafe": "jev-1.13.0",
}
RETRY_STATUSES = {408, 409, 429, 500, 502, 503, 504}


class BackendError(RuntimeError):
    pass


# --- normalized response ------------------------------------------------------


@dataclass(slots=True)
class Answer:
    type: str
    noul: float | None = None
    choice: str | None = None
    score: float | None = None
    confidence: float | None = None
    probabilities: dict[str, float] | None = None
    legend: dict | None = None

    def to_dict(self) -> dict:
        # slots=True means no __dict__, so walk the declared fields.
        return {f.name: getattr(self, f.name) for f in fields(self) if getattr(self, f.name) is not None}


@dataclass(slots=True)
class Response:
    model: str | None
    answers: dict[str, Answer]
    input_tokens: int | None = None
    output_tokens: int | None = None
    # OpenRouter reports what it actually billed. Prefer it over recomputing from a
    # published rate -- the rate can change and the provider's number is the truth.
    cost_usd: float | None = None
    request_id: str | None = None
    provider: str | None = None
    raw: dict = field(default_factory=dict, repr=False)


def _answer_from_dict(d: dict) -> Answer:
    return Answer(
        type=d.get("type", ""),
        noul=d.get("noul"),
        choice=d.get("choice"),
        score=d.get("score"),
        confidence=d.get("confidence"),
        probabilities=d.get("probabilities"),
        legend=d.get("legend"),
    )


def question_payload(q: Any) -> Any:
    """A question as the JSON both APIs expect."""
    if isinstance(q, (dict, list, str, int, float, bool, type(None))):
        return q
    for attr in ("model_dump", "dict", "_asdict"):
        if hasattr(q, attr):
            try:
                return getattr(q, attr)()
            except TypeError:
                pass
    return str(q)


# --- env ----------------------------------------------------------------------


def load_env(start: Path | None = None) -> None:
    """Read ``.env.local`` then ``.env``, walking up from ``start``.

    A variable already set in the real environment always wins, so an explicit
    ``OPENROUTER_API_KEY=... jevcut ...`` is never silently overridden by a stale file.
    """
    here = (start or Path.cwd()).resolve()
    for directory in [here, *here.parents]:
        for name in (".env.local", ".env"):
            path = directory / name
            if not path.exists():
                continue
            for line in path.read_text().splitlines():
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, _, value = line.partition("=")
                key = key.strip()
                value = value.strip().strip('"').strip("'")
                if key and key not in os.environ:
                    os.environ[key] = value
        if (directory / ".git").exists():
            break


# --- backends -----------------------------------------------------------------


class Backend(Protocol):
    name: str

    def system_one(self, state: Any, questions: dict[str, Any], model: str) -> Response: ...


@dataclass
class OpenRouterBackend:
    """The Decisions API over plain HTTP. No third-party dependency."""

    api_key: str | None = None
    timeout_s: float = 120.0
    max_retries: int = 5
    referer: str | None = None
    title: str | None = None
    url: str = OPENROUTER_URL
    name: str = "openrouter"

    def __post_init__(self) -> None:
        if not self.api_key:
            load_env()
            self.api_key = os.environ.get("OPENROUTER_API_KEY")
        if not self.api_key:
            raise BackendError(
                "OPENROUTER_API_KEY is not set. Put it in .env.local or export it."
            )

    def build_payload(self, state: Any, questions: dict[str, Any], model: str) -> dict:
        return {
            "model": model,
            "state": state,
            "questions": {k: question_payload(q) for k, q in questions.items()},
        }

    def _headers(self) -> dict[str, str]:
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        # Optional, and only for OpenRouter's leaderboards.
        if self.referer:
            headers["HTTP-Referer"] = self.referer
        if self.title:
            headers["X-Title"] = self.title
        return headers

    def system_one(self, state: Any, questions: dict[str, Any], model: str) -> Response:
        body = json.dumps(self.build_payload(state, questions, model)).encode()
        last_error: Exception | None = None

        for attempt in range(self.max_retries + 1):
            request = urllib.request.Request(
                self.url, data=body, headers=self._headers(), method="POST"
            )
            try:
                with urllib.request.urlopen(request, timeout=self.timeout_s) as resp:
                    return parse_response(json.loads(resp.read().decode()))
            except urllib.error.HTTPError as exc:
                detail = exc.read().decode(errors="replace")[:500]
                if exc.code not in RETRY_STATUSES or attempt == self.max_retries:
                    raise BackendError(f"HTTP {exc.code} from OpenRouter: {detail}") from exc
                last_error = exc
                self._sleep(attempt, exc.headers.get("Retry-After"))
            except (urllib.error.URLError, TimeoutError) as exc:
                if attempt == self.max_retries:
                    raise BackendError(f"could not reach OpenRouter: {exc}") from exc
                last_error = exc
                self._sleep(attempt, None)

        raise BackendError(f"retries exhausted: {last_error}")

    def _sleep(self, attempt: int, retry_after: str | None) -> None:
        """Honour Retry-After when the server sends one; exponential backoff otherwise."""
        if retry_after:
            try:
                time.sleep(min(float(retry_after), 60.0))
                return
            except ValueError:
                pass
        time.sleep(min(2**attempt * 0.5, 30.0) * (0.5 + random.random()))


@dataclass
class TypeSafeBackend:
    """The first-party SDK, for keys issued by TypeSafe directly."""

    api_key: str | None = None
    timeout_s: float = 120.0
    max_retries: int = 5
    name: str = "typesafe"
    _client: Any = field(default=None, repr=False)

    def _ensure(self) -> Any:
        if self._client is None:
            from typesafe_sdk import RetryPolicy, TypeSafeClient

            load_env()
            self._client = TypeSafeClient(
                api_key=self.api_key,
                timeout=self.timeout_s,
                # Set explicitly rather than inherited, so the behaviour is visible here.
                retry=RetryPolicy(max_retries=self.max_retries, respect_retry_after=True),
            )
        return self._client

    def system_one(self, state: Any, questions: dict[str, Any], model: str) -> Response:
        raw = self._ensure().system_one(state, questions, model=model)
        usage = getattr(raw, "usage", None)
        return Response(
            model=getattr(raw, "model", None),
            answers={
                key: _answer_from_dict(
                    {
                        f: getattr(ans, f, None)
                        for f in ("type", "noul", "choice", "score", "confidence",
                                  "probabilities", "legend")
                    }
                )
                for key, ans in (getattr(raw, "answers", {}) or {}).items()
            },
            input_tokens=getattr(usage, "input_tokens", None),
            output_tokens=getattr(usage, "output_tokens", None),
        )

    def close(self) -> None:
        if self._client is not None and hasattr(self._client, "close"):
            self._client.close()
            self._client = None


def parse_response(payload: dict) -> Response:
    """Normalize a Decisions API response.

    Defensive about envelope shape and usage field names: this is an alpha endpoint, and
    a key rename should cost us a token count, not a run.
    """
    body = payload.get("decision", payload)
    answers = body.get("answers") or {}
    if not isinstance(answers, dict):
        raise BackendError(f"unexpected answers shape: {type(answers).__name__}")

    usage = body.get("usage") or payload.get("usage") or {}
    return Response(
        model=body.get("model") or payload.get("model"),
        answers={k: _answer_from_dict(v) for k, v in answers.items()},
        input_tokens=usage.get("input_tokens") or usage.get("prompt_tokens"),
        output_tokens=usage.get("output_tokens") or usage.get("completion_tokens"),
        cost_usd=usage.get("cost"),
        request_id=body.get("id") or payload.get("id"),
        provider=body.get("provider") or payload.get("provider"),
        raw=payload,
    )


def make_backend(config: Any) -> Backend:
    if config.backend == "openrouter":
        return OpenRouterBackend(
            timeout_s=config.timeout_s,
            max_retries=config.max_retries,
            referer=getattr(config, "openrouter_referer", None),
            title=getattr(config, "openrouter_title", None),
        )
    if config.backend == "typesafe":
        return TypeSafeBackend(timeout_s=config.timeout_s, max_retries=config.max_retries)
    raise BackendError(f"unknown backend {config.backend!r}; use 'openrouter' or 'typesafe'")
