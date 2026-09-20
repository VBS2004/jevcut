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

from jevcut.backends import Backend, Response, make_backend, question_payload
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


# Calibrated against live traces rather than assumed. Two observations through
# OpenRouter: ~94 chars of state+questions -> 275 reported input tokens, and ~1532 chars
# -> 696. That fits a large fixed cost per request (the API's own scaffolding around the
# questions) plus ~3.5 chars per token of our content. A plain chars/4 rule underestimates
# a small request by 10x, which would make the budget guard useless exactly where it
# matters. Issue 018 refines these from a larger sample.
REQUEST_OVERHEAD_TOKENS = 250
CHARS_PER_TOKEN = 3.5


def estimate_tokens(obj: Any) -> int:
    """Content tokens only, excluding per-request overhead."""
    text = obj if isinstance(obj, str) else json.dumps(obj, ensure_ascii=False, default=str)
    return max(1, int(len(text) / CHARS_PER_TOKEN))


@dataclass
class Usage:
    requests: int = 0
    input_tokens: int = 0

    reported_cost_usd: float = 0.0
    has_reported_cost: bool = False

    @property
    def cost_usd(self) -> float:
        """What was billed when the provider says so, our own arithmetic otherwise."""
        if self.has_reported_cost:
            return self.reported_cost_usd
        return self.input_tokens * PRICE_PER_INPUT_TOKEN


@dataclass
class JevClient:
    config: Config = field(default_factory=Config)
    run_dir: Path | None = None
    run_id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    usage: Usage = field(default_factory=Usage)
    backend: Backend | None = None

    def __post_init__(self) -> None:
        self.run_dir = Path(self.run_dir or Path("runs") / self.run_id)
        self.run_dir.mkdir(parents=True, exist_ok=True)
        self.config.to_json(self.run_dir / "config.json")

    # -- lifecycle -------------------------------------------------------------

    def _ensure_backend(self) -> Backend:
        if self.backend is None:
            self.backend = make_backend(self.config)
        return self.backend

    def close(self) -> None:
        if self.backend is not None and hasattr(self.backend, "close"):
            self.backend.close()  # type: ignore[attr-defined]

    def __enter__(self) -> JevClient:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    # -- the one call ----------------------------------------------------------

    def check_budget(self, state: Any, questions: dict[str, Any]) -> dict[str, int]:
        """Enforce the documented context limits before spending anything."""
        state_tokens = estimate_tokens(state)
        per_question = {k: estimate_tokens(question_payload(q)) for k, q in questions.items()}
        longest = max(per_question.values(), default=0)
        total = REQUEST_OVERHEAD_TOKENS + state_tokens + sum(per_question.values())

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
        backend = self._ensure_backend()

        started = time.monotonic()
        error: str | None = None
        response: Response | None = None
        try:
            response = backend.system_one(state, questions, self.config.model)
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
        response: Response | None = kw.pop("response")
        answers: dict[str, Any] = {}
        model_used = None
        # Fall back to the pre-flight estimate when the backend reports no usage, so a
        # missing field costs accuracy in the cost report rather than losing the call.
        input_tokens = kw["estimate"]["total"]

        if response is not None:
            model_used = response.model
            if response.input_tokens is not None:
                input_tokens = response.input_tokens
            if response.cost_usd is not None:
                self.usage.reported_cost_usd += response.cost_usd
                self.usage.has_reported_cost = True
            answers = {k: a.to_dict() for k, a in response.answers.items()}

        self.usage.requests += 1
        self.usage.input_tokens += input_tokens

        record = {
            "run_id": self.run_id,
            "ts": time.time(),
            "pass": kw["pass_name"],
            "backend": self.config.backend,
            # The provider's own request id: what you quote when chasing one call.
            "request_id": response.request_id if response is not None else None,
            "provider": response.provider if response is not None else None,
            "reported_cost_usd": response.cost_usd if response is not None else None,
            # Model requested vs. model that answered: an alias moving underneath a tuned
            # threshold is exactly the kind of drift this line catches later.
            "model_requested": self.config.model,
            "model_answered": model_used,
            "latency_s": round(kw["latency_s"], 3),
            "estimated_tokens": kw["estimate"],
            "input_tokens": input_tokens,
            "state": kw["state"],
            "questions": {k: question_payload(q) for k, q in kw["questions"].items()},
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
            "cost_is_reported": self.usage.has_reported_cost,
        }
