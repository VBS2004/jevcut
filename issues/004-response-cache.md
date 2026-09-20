# 004 — Response cache and deterministic replay

| | |
| --- | --- |
| **Milestone** | M0 Foundations |
| **Depends on** | 001 |
| **Blocks** | 013, 014 |
| **Size** | S |

## Why

014 sweeps thresholds and 013 re-runs 40 videos repeatedly. Changing a weight or a display
filter **must not re-run inference** — the evidence and the question meanings are
unchanged, so the judgments are still valid. Without a cache, every tuning iteration is a
fresh bill and a fresh source of variance.

The TypeSafe cookbooks use `cooksafe.JsonCache` for exactly this; the same pattern works
here.

## Build

- Cache key: `sha256(model_id + state_json + questions_json)`. Model ID **in the key** —
  a version bump must invalidate, not silently reuse.
- Store request and response verbatim in `runs/<run_id>/cache.json`.
- Modes: `live` (call + store), `replay` (fail loudly on a miss), `refresh` (ignore cache).
- `replay` is the default in tests and CI so the test suite costs nothing and can't flake
  on the network.

## Acceptance criteria

- [ ] Two identical pipeline runs make zero API calls on the second.
- [ ] Changing only a ranking weight makes zero API calls.
- [ ] Changing a question's wording invalidates exactly that question's entries.
- [ ] A cache miss in `replay` mode raises with the key and the pass name.
- [ ] Cached runs are portable — commit one to `eval/fixtures/` so the suite runs without
      a key.

## Gotchas

- Normalize question dicts before hashing (sorted keys) or trivial reordering thrashes the
  cache.
- The cache is *not* a correctness shortcut: when 012 reports a bad clip, check the trace
  is from the current question set before concluding anything about the model.
