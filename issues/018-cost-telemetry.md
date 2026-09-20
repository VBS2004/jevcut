# 018 — Cost telemetry and budget guard

| | |
| --- | --- |
| **Milestone** | M4 Product |
| **Depends on** | 001, 010 |
| **Blocks** | — |
| **Size** | S |

## Why

Billing is input-only at $0.042/Mtok, so cost is fully predictable *before* a request is
sent — if anything counts. The real constraint isn't dollars, it's the 1,200 requests/min
limit, and the docs warn it's "adjusting dynamically" under load. A run that silently
blows through either is a run nobody can reason about.

## Build

- Token accounting per call, rolled up per pass and per video; `$` from the published
  rate; reconcile against reported usage.
- **Budget guard:** hard ceiling per video (tokens and requests), checked before each pass.
  On breach: **stop and report** — never silently truncate the transcript or drop windows.
  A partial run that looks complete is worse than a failed one.
- Rate-limit awareness: track req/min against the account limit, back off proactively
  rather than collecting 429s.
- `jevcut cost <run_id>` — per-pass table: requests, tokens, $, latency, share of total.
- Warn when any single request approaches the 32k state-plus-longest-question limit.

## Acceptance criteria

- [ ] Predicted vs. actual tokens within 10% per pass.
- [ ] Budget breach aborts loudly with which pass and what limit.
- [ ] `jevcut cost` table matches the published rate and the reported usage.
- [ ] Concurrent live streams stay under the account request limit by construction.

## Gotchas

- Output tokens are free; don't count them and don't let a dashboard imply otherwise.
- Rate limits can change without notice. Treat the limit as config with a conservative
  default, not a constant.
- Report **requests/min** as prominently as dollars. It's the number that actually decides
  how many streams run at once.
