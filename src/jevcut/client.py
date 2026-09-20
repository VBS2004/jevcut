"""Issue 001 -- the Jev client wrapper.

Every pass sends one state with many questions, because Jev ingests the state once and
evaluates all questions against it in parallel. So the unit of cost is the *request*, and
this wrapper's job is to make each one accountable: pinned model, enforced context limits,
retries that respect rate limits, and a trace line good enough to reconstruct the call.

The trace is not optional bookkeeping. Issue 010's triage depends on being able to see the
exact options Jev was offered -- otherwise "the model picked the wrong cut" and "the right
cut was never in the list" are indistinguishable.
"""

from __future__ import annotations

import json
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from jevcut.config import (
    CONTEXT_STATE_PLUS_QUESTION_TOKENS,
    CONTEXT_TOTAL_TOKENS,
    PRICE_PER_INPUT_TOKEN,
    Config,
)


class BudgetError(RuntimeError):
    """Raised before a request is sent, never after.

    A run that silently truncates its input to fit is worse than one that fails: it
    produces plausible output from incomplete evidence.
    """


def estimate_tokens(obj: Any) -> int:
    """Rough pre-flight estimate (~4 chars/token). Reconciled against reported usage."""
    text = obj if isinstance(obj, str) else json.dumps(obj, ensure_ascii=False, default=str)
    return max(1, len(text) // 4)


def _question_payload(q: Any) -> Any:
    """A question as JSON, for the trace. SDK objects expose model_dump(); raw payloads
    are already data and must pass through untouched -- a stringified question is useless
    for the diffing that issue 010 does."""
    if isinstance(q, (dict, list, str, int, float, bool, type(None))):
        return q
    for attr in ("model_dump", "dict", "_asdict"):
        if hasattr(q, attr):
            try:
                return getattr(q, attr)()
            except TypeError:
                pass
    return str(q)


@dataclass
class Usage:
    requests: int = 0
    input_tokens: int = 0

    @property
    def cost_usd(self) -> float:
        return self.input_tokens * PRICE_PER_INPUT_TOKEN


@dataclass
class JevClient:
    config: Config = field(default_factory=Config)
    run_dir: Path | None = None
    run_id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    usage: Usage = field(default_factory=Usage)
    _client: Any = field(default=None, repr=False)

    def __post_init__(self) -> None:
        self.run_dir = Path(self.run_dir or Path("runs") / self.run_id)
        self.run_dir.mkdir(parents=True, exist_ok=True)
        self.config.to_json(self.run_dir / "config.json")

    # -- lifecycle -------------------------------------------------------------

    def _ensure_client(self) -> Any:
        if self._client is None:
            from typesafe_sdk import RetryPolicy, TypeSafeClient

            self._client = TypeSafeClient(
                model=self.config.model_id,
                timeout=self.config.timeout_s,
                # The SDK retries and honours retry-after by default; set it explicitly so
                # the behaviour is visible here rather than inherited silently.
                retry=RetryPolicy(
                    max_retries=self.config.max_retries,
                    respect_retry_after=True,
                ),
            )
        return self._client

    def close(self) -> None:
        if self._client is not None and hasattr(self._client, "close"):
            self._client.close()
            self._client = None

    def __enter__(self) -> JevClient:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    # -- the one call ----------------------------------------------------------

    def check_budget(self, state: Any, questions: dict[str, Any]) -> dict[str, int]:
        """Enforce the documented context limits before spending anything."""
        state_tokens = estimate_tokens(state)
        per_question = {k: estimate_tokens(_question_payload(q)) for k, q in questions.items()}
        longest = max(per_question.values(), default=0)
        total = state_tokens + sum(per_question.values())

        if state_tokens + longest > CONTEXT_STATE_PLUS_QUESTION_TOKENS:
            worst = max(per_question, key=per_question.get)  # type: ignore[arg-type]
            raise BudgetError(
                f"state ({state_tokens} tok) + longest question '{worst}' ({longest} tok) "
                f"exceeds the {CONTEXT_STATE_PLUS_QUESTION_TOKENS} limit"
            )
        if total > CONTEXT_TOTAL_TOKENS:
            raise BudgetError(
                f"state + {len(questions)} questions = {total} tok exceeds the "
                f"{CONTEXT_TOTAL_TOKENS} per-request limit"
            )
        if self.usage.requests + 1 > self.config.max_requests_per_video:
            raise BudgetError(f"request budget exhausted ({self.config.max_requests_per_video})")
        if self.usage.input_tokens + total > self.config.max_tokens_per_video:
            raise BudgetError(f"token budget exhausted ({self.config.max_tokens_per_video})")

        return {"state": state_tokens, "total": total, "longest_question": longest}

    def ask(
        self,
        state: Any,
        questions: dict[str, Any],
        *,
        pass_name: str,
        meta: dict | None = None,
    ) -> Any:
        estimate = self.check_budget(state, questions)
        client = self._ensure_client()

        started = time.monotonic()
        error: str | None = None
        response = None
        try:
            response = client.system_one(state, questions, model=self.config.model_id)
            return response
        except Exception as exc:
            error = f"{type(exc).__name__}: {exc}"
            raise
        finally:
            self._trace(
                pass_name=pass_name,
                state=state,
                questions=questions,
                response=response,
                latency_s=time.monotonic() - started,
                estimate=estimate,
                error=error,
                meta=meta or {},
            )

    # -- tracing ---------------------------------------------------------------

    def _trace(self, **kw: Any) -> None:
        response = kw.pop("response")
        answers: dict[str, Any] = {}
        model_used = None
        input_tokens = kw["estimate"]["total"]

        if response is not None:
            model_used = getattr(response, "model", None)
            usage = getattr(response, "usage", None)
            if usage is not None and getattr(usage, "input_tokens", None) is not None:
                input_tokens = usage.input_tokens
            for key, ans in (getattr(response, "answers", {}) or {}).items():
                answers[key] = {
                    f: getattr(ans, f)
                    for f in ("type", "noul", "choice", "score", "confidence", "probabilities", "legend")
                    if getattr(ans, f, None) is not None
                }

        self.usage.requests += 1
        self.usage.input_tokens += input_tokens

        record = {
            "run_id": self.run_id,
            "ts": time.time(),
            "pass": kw["pass_name"],
            # Model requested vs. model that answered: an alias moving underneath a tuned
            # threshold is exactly the kind of drift this line catches later.
            "model_requested": self.config.model_id,
            "model_answered": model_used,
            "latency_s": round(kw["latency_s"], 3),
            "estimated_tokens": kw["estimate"],
            "input_tokens": input_tokens,
            "state": kw["state"],
            "questions": {k: _question_payload(q) for k, q in kw["questions"].items()},
            "answers": answers,
            "error": kw["error"],
            "meta": kw["meta"],
        }
        with (self.run_dir / "trace.jsonl").open("a") as fh:
            fh.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")

    def summary(self) -> dict:
        return {
            "run_id": self.run_id,
            "run_dir": str(self.run_dir),
            "requests": self.usage.requests,
            "input_tokens": self.usage.input_tokens,
            "cost_usd": self.usage.cost_usd,
        }
