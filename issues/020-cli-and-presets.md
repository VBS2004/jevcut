# 020 — CLI and content presets

| | |
| --- | --- |
| **Milestone** | M4 Product |
| **Depends on** | 014 |
| **Blocks** | — |
| **Size** | M |

## Why

Question wording, thresholds and duration bands differ by genre — a conference talk's
"moment" isn't a gameplay reaction's. jevmeter shipped per-content presets for exactly this
reason. 014's per-genre sweep produces the numbers; this issue packages them.

## Build

- Presets as data (`presets/*.json`), not code: question-instruction variants, thresholds,
  duration band, anchors-per-window, cut-point density.
- Ship: `podcast`, `talk`, `gameplay`, `tutorial`, `debate`. Each with the eval numbers
  that produced it in a comment field.
- CLI:
  - `jevcut run <input> --preset podcast [--top 10] [--dry-run]`
  - `jevcut live <stream-url> --preset gameplay`
  - `jevcut explain <clip_id>` · `jevcut cost <run_id>` · `jevcut eval`
- `--preset auto`: run Pass C's `kind` Choice on a sample of windows and pick the preset
  from the distribution. Cheap, and it's the same question already being asked.
- README quickstart with one real worked example and its actual cost and timing.

## Acceptance criteria

- [ ] Five presets, each with eval numbers on its genre.
- [ ] A preset is fully specified by data — no code path per genre.
- [ ] `--preset auto` matches the human-assigned genre on ≥80% of the eval set.
- [ ] A new user gets clips from one command with only `TYPESAFE_API_KEY` set.

## Gotchas

- A preset with no eval numbers behind it is a guess wearing a name. Don't ship one.
- Don't proliferate presets. Five well-measured beats fifteen guessed, and each one is a
  maintenance burden every time the model version moves.
