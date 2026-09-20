# 001 — Project scaffold and Jev client wrapper

| | |
| --- | --- |
| **Milestone** | M0 Foundations |
| **Depends on** | — |
| **Blocks** | everything |
| **Size** | S |

## Why

Every later pass sends one state with many questions and needs the same things: retries,
a pinned model ID, token accounting, and a trace of exactly what was asked. Build it once.

## Build

- `pip install "typesafe-sdk>=0.5.7" --extra-index-url https://pypi.typesafe.ai/`
- `src/jevcut/client.py` — thin wrapper over `TypeSafeClient`:
  - `ask(state: dict, questions: dict, *, pass_name: str) -> Answers`
  - **Pin the versioned model ID** (`jev-1.13.0`) in config, not `jev-latest`. Aliases
    move and thresholds tuned against a version stop being valid when they do.
  - Log the response's `model` field on every call — that's the record of which model
    produced which result.
  - Record per-call: pass name, state token estimate, question count, latency, usage.
- `src/jevcut/config.py` — dataclass config: model ID, thresholds, window sizes, duration
  bands. Everything tunable in one place, because 014 will be sweeping these.
- API key from `TYPESAFE_API_KEY` env only. Never a file, never a flag.

## Acceptance criteria

- [ ] A smoke test sends one Noul and prints the probability.
- [ ] Rate-limit (429) retries with backoff and honours `retry-after`. The SDK does this
      by default — verify it, don't assume it.
- [ ] Every call appends one structured record to a run log.
- [ ] Config round-trips to JSON so a run can be reproduced from its log.

## Gotchas

- Keep the API key server-side; if a UI ever appears, it calls our backend, not TypeSafe.
- Budget check: 64k tokens per request total, 32k for state + longest question. Pass C's
  anchor Choice carries ~80 options and is the longest question in the system — assert
  against the limit rather than discovering it as a 400.
