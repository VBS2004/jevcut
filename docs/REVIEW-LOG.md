# Review log

## 2026-09-20 — M0 + Pass C (issues 001–003, 005)

Reviewed `master...m0-foundations`: 4 commits, 29 files. Findings below were each
reproduced before being accepted, and each fix carries a regression test.

Context worth recording: most of this code was written during a **low-effort** stretch,
and the defects cluster exactly where that shows — concurrency applied to one function
and not its neighbour, comments describing intent rather than code, and the one
hand-rolled module left untested.

### Fixed — correctness

| # | Where | Defect | Evidence |
| --- | --- | --- | --- |
| 1 | `client.py` | **Budget guard was check-then-act outside the lock.** A comment claimed "read under the lock"; there was no lock. Pass C was the first caller with 8 threads. | 8 threads, budget 5 → **12 requests allowed**. Now 5, overshoot 0. |
| 2 | `scan.py` | **One failed window discarded the whole scan.** `pool.map` re-raises the first worker exception and throws away every result behind it, so a 5xx outliving its retries meant paying for every window and writing no `anchors.json`. | Now per-future collection; failures logged, survivors kept. |
| 3 | `cuts.py` | **No candidate at the start of the first sentence or the end of the last.** The loop only emitted boundaries *between* sentence pairs. A clip opening on the first line was unrecoverable — and looked like a model error rather than a missing option. | 3-sentence transcript spanning 0–4s produced cuts spanning 2.67s–2.67s. New `edge` kind, highest thinning weight. |
| 4 | `client.py` | **Cost undercounted on mixed reporting.** One response carrying `usage.cost` latched `has_reported_cost` forever; every later call reporting none was counted as free. | 100 calls, 1 reporting → **$0.000012 instead of $0.004200**, labelled "(reported)". Now tracked per call. |
| 5 | `backends.py` | **Internal retries invisible to accounting.** Up to 6 real HTTP POSTs counted as 1 request, against the limit the cost model calls the binding constraint. | `Response.http_attempts` now flows into `usage.requests` and the trace. |
| 6 | `transcript.py` | **ASR cache poisoning.** An empty decode was cached as `[]` and short-circuited every later run, permanently. The key also ignored `model_size`, so a `base` transcript was served to a caller asking for `large`. | Empty results now raise; `model_size` is in the cache key. |
| 7 | `transcript.py` | **`_split_long` infinite recursion** at `max_sentence_words <= 1`: the margin pushed the split index onto the last element, so `left` was the whole group. | `RecursionError` reproduced. Split index clamped to `len-2`. |
| 8 | `scan.py` | **Malformed answers were indistinguishable from a flat window.** `.noul or 0.0` turned a missing answer into 0.0, and the "option we never offered" branch had a comment saying "log and stop" that did not log — exactly the distinction issue 010 exists to make. | Both branches now warn with the window, round and option count. |

### Fixed — design

| # | Where | Change |
| --- | --- | --- |
| 9 | `config.py` | `anchor_removal_s` did double duty as the in-window re-pick radius *and* the cross-window dedupe radius. Split into `anchor_removal_s` / `anchor_dedupe_s` so 014 can tune either without moving both. |
| 10 | `scan.py` | Short trailing windows (81 sentences → `[80, 11]`) cost a whole request — ~250 tokens of fixed overhead alone — for content the previous window already overlaps. Tails under `min_tail_window` are folded back in. |
| 11 | `backends.py` | **The HTTP retry path had zero test coverage** — backoff, jitter, `Retry-After` parsing and the retryable-status set, in the one module hand-rolled rather than taken from an SDK. 17 tests added. |

### Checked, no finding

Windowing covers every sentence with exactly `window_overlap` shared lines (verified
n = 0…600, including after tail merging). *Still true of coverage; the overlap itself is
now `window_overlap_s`, measured in seconds — counting it in sentences let the insurance
shrink on fast speech. Found reading autoclip, not in this review.* `render_markers` emits each cut once, in time
order, including mid-sentence pauses. The `MAX_CHOICE_OPTIONS - 1` guard leaves room for
the no-match option. `Config` round-trip and unknown-key rejection. `.gitignore`'s
`.env.*` / `!.env.example` pair — no secret is tracked. `load_env` precedence over the
real environment.

### Still open

- Issue 003's **95% boundary-recall criterion is unverified** — it needs the labeled set
  from 011. `coverage()` is implemented and the `edge` fix closes one known hole in it.
- The Whisper and scenedetect paths remain unexercised (neither optional extra installed).
