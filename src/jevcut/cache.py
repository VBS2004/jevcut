"""Issue 004 -- the response cache, and why the numbers move without it.

Every judgment this project makes is a function of three things: the model, the state,
and the questions. Ask the same three twice and the answer should be the same -- but it
is not quite, and the repair loop in Pass E **branches on thresholds**, so a 0.49 and a
0.51 send a clip down entirely different paths of widen, trim or drop. Small variance at
the leaves, large divergence in the output: two identical runs produce different clip
sets, and a config change cannot be told apart from noise.

So the cache is not primarily about money. It is what makes a comparison mean anything.

**Content-addressed, and shared across runs.** The key is the model, the state and the
questions, so the same call from any run is the same entry. 004 specifies a per-run
`cache.json`, which replays one run byte-for-byte but gives no hits when comparing config
A against B -- which is the thing we actually need. The per-run trace still records what
was hit.

**Rewording a question invalidates it automatically**, because the question text is in
the key. There is no way to edit a prompt and silently keep answers to the old one.

**The honest caveat:** a cache makes the pipeline deterministic by freezing the model's
answer at whatever the first call returned. That removes noise from comparisons, not from
reality. Conclusions drawn under replay are conditional on that sample.
"""

from __future__ import annotations

import hashlib
import json
import tempfile
from dataclasses import replace
from pathlib import Path
from typing import Any

from jevcut.backends import Response, _answer_from_dict, question_payload

#: `live` calls on a miss and stores. `replay` fails loudly on a miss, so a test or a
#: comparison cannot quietly become a live run. `refresh` ignores what is stored and
#: overwrites, for re-measuring after a model version changes.
MODES = ("live", "replay", "refresh", "off")


class CacheMiss(RuntimeError):
    """Raised in `replay` mode. Loud on purpose: a silent fallthrough to the network is
    how a deterministic comparison turns back into a noisy one without anyone noticing."""


def _canonical(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)


def key_for(model: str | None, state: Any, questions: dict[str, Any]) -> str:
    """The identity of a judgment: model, state, questions. Nothing else.

    Sorted keys and fixed separators, because dict ordering leaking into the key produces
    misses that look exactly like the nondeterminism this exists to remove. The model is
    in the key so a version bump invalidates rather than silently reusing.
    """
    payload = _canonical(
        {
            "model": model,
            "state": state,
            "questions": {name: question_payload(q) for name, q in sorted(questions.items())},
        }
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


class ResponseCache:
    """One JSON file per judgment, under a two-character shard directory.

    Separate files rather than one index: Pass C runs eight threads, and a shared file
    would need a lock on every read.
    """

    def __init__(self, directory: str | Path, mode: str = "live") -> None:
        if mode not in MODES:
            raise ValueError(f"cache mode must be one of {MODES}, not {mode!r}")
        self.dir = Path(directory)
        self.mode = mode
        self.hits = 0
        self.misses = 0

    @property
    def enabled(self) -> bool:
        return self.mode != "off"

    def _path(self, key: str) -> Path:
        return self.dir / key[:2] / f"{key}.json"

    def get(self, key: str) -> Response | None:
        if self.mode in ("off", "refresh"):
            return None
        path = self._path(key)
        if not path.exists():
            self.misses += 1
            if self.mode == "replay":
                raise CacheMiss(
                    f"no cached response for {key[:12]} in {self.dir}. Run once in `live` "
                    "mode to populate it, or the questions changed -- their text is part "
                    "of the key."
                )
            return None
        data = json.loads(path.read_text())
        self.hits += 1
        stored = data["response"]
        return Response(
            model=stored.get("model"),
            answers={k: _answer_from_dict(v) for k, v in stored.get("answers", {}).items()},
            input_tokens=stored.get("input_tokens"),
            output_tokens=stored.get("output_tokens"),
            cost_usd=stored.get("cost_usd"),
            request_id=stored.get("request_id"),
            provider=stored.get("provider"),
            http_attempts=stored.get("http_attempts", 1),
        )

    def put(self, key: str, response: Response, *, pass_name: str = "") -> None:
        if self.mode == "off":
            return
        path = self._path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        record = {
            "pass": pass_name,
            "response": {
                "model": response.model,
                "answers": {k: a.to_dict() for k, a in response.answers.items()},
                "input_tokens": response.input_tokens,
                "output_tokens": response.output_tokens,
                "cost_usd": response.cost_usd,
                "request_id": response.request_id,
                "provider": response.provider,
                "http_attempts": response.http_attempts,
            },
        }
        # Written via a temp file in the same directory, then moved: eight threads and a
        # half-written JSON file would poison the entry for every later run.
        with tempfile.NamedTemporaryFile(
            "w", dir=path.parent, delete=False, encoding="utf-8"
        ) as fh:
            json.dump(record, fh, ensure_ascii=False)
            tmp = Path(fh.name)
        tmp.replace(path)


def as_cached(response: Response) -> Response:
    """The same answers, costing nothing.

    A hit that reported its original cost would make the budget guard and the cost report
    describe a run that did not happen.
    """
    return replace(response, cost_usd=0.0, input_tokens=0, output_tokens=0, http_attempts=0)
