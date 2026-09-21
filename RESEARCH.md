# Research phase

**Status: active. Building is paused at issue 006.**

Issues 001–003 and 005 are built and live-verified (PR #1). The pause is deliberate:
the design in [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) was derived from skimming
three repos in one sitting, and the thesis it rests on has never been checked against
real code or real data. A convincing plan is not evidence.

## The thesis, stated so it can be killed

> Auto-clipping fails mostly at **boundaries**, not at selection. Picking an exact cut
> point from an enumerated candidate list beats snapping to fixed windows, and a
> dedicated standalone gate (mid-thought / dangling reference / no payoff) removes the
> defects people actually complain about.

Four ways this could be wrong, in order of how much they'd cost us:

1. **Selection is the hard part, not boundaries.** If humans mostly disagree about
   *which* moments to clip and barely at all about where they start, the whole cut-point
   apparatus is solving a problem nobody has.
2. **Snapping is good enough.** If sentence-boundary snapping lands within the range a
   human would accept, the Choice-over-cut-points machinery buys precision nobody
   perceives.
3. **The gate rejects too much.** If `standalone` and `dangling_reference` fire on clips
   humans find perfectly fine, we ship fewer clips than a naive tool and call it quality.
4. **Classical methods already solve it.** The most likely one, and the one the current
   design never considers. Topic segmentation is a thirty-year-old field and acoustic
   boundary detection is older. If a classical segmenter puts boundaries where humans do,
   Jev is an expensive way to reproduce free output.
   → **Half answered, 2026-09-21.** Tested against 48 human-placed boundaries
   ([PRIOR-ART](docs/PRIOR-ART.md#classical-methods)). *Topic segmentation*: dead at clip
   granularity — TextTiling is at or below chance at 1–2s at every parameter setting.
   *Boundary snapping*: alive and the live threat — caption-cue starts alone hit 81% within
   1.0s. The threat narrowed to Baseline 4; it did not go away.

A fifth, found while reading the sponsor repo and **settled rather than left open**: the
thesis is about *verbal* clips, and nothing in the design can see a moment that carries no
words. v1 is scoped to verbal content and says so in the README; the non-verbal case is
specced and deferred in [issue 021](issues/021-event-clips.md). Research below stays
focused on whether the boundary thesis holds **for speech**.

## What we are actually doing

Reading public repos — Jev-based and not — to answer:

- **Where does Jev genuinely fit?** Not where it *could* be used, where it is the right
  tool: a bounded judgment that code can consume, that a regex or a parser cannot do, and
  that does not need generation, arithmetic or multi-hop reasoning.
- **Where do existing clippers actually break?** Find the issue threads, the complaints,
  the test fixtures. The three failure modes in the README came from my own reasoning
  about the category, not from evidence.
- **What has already been tried?** The awesome-jev directories grow weekly. Somebody may
  have run this experiment.

## Method

For each repo: what problem, what approach, what does it get wrong, and is there a
judgment in it that Jev would do better than what is there now. Record findings in
`docs/PRIOR-ART.md`, which already has the format.

Read the code, not the README. A README states intent; the code states what happens.

## Classical baselines to check first

The design currently uses acoustics only as a *candidate generator* (pauses, shot cuts)
and assumes a model is needed to choose among them. That assumption is untested, and these
methods predate the assumption:

**Acoustic / signal** — silence and speech-activity segmentation: `silero-vad`, WebRTC VAD,
`auditok`, `inaSpeechSegmenter`; speaker diarization: `pyannote.audio`; shot boundaries:
`PySceneDetect`, TransNetV2. These produce boundaries with **no model call at all**.

**Text / topic segmentation** — TextTiling, C99, BayesSeg, and modern neural successors.
These answer "where does one subject end and the next begin" directly, which is close to
what Pass D is asking Jev to do.

**Question to hold while reading:** does the method put a boundary where a human would?
If yes, it belongs in the eval as a **free baseline** that jevcut must beat — and if it
wins, the honest move is to use it for boundaries and reserve Jev for the judgments that
genuinely need semantics (is this moment worth clipping, does it stand alone, does the
payoff land). That is a better product than the one currently designed, not a defeat.

A hybrid is the likeliest good answer: classical methods enumerate and pre-rank the
candidates, Jev picks among a shortlist. That is cheaper and more accurate than either
alone, and it is not what [ARCHITECTURE.md](docs/ARCHITECTURE.md) currently describes.

## Starting points

Directories, refreshed weekly:
[hellogumbo/awesome-jev](https://github.com/hellogumbo/awesome-jev),
[cobanov/awesome-jev](https://github.com/cobanov/awesome-jev),
[logicrw/awesome-jev-projects](https://github.com/logicrw/awesome-jev-projects),
[AnotiaWang/awesome-jev](https://github.com/AnotiaWang/awesome-jev),
[fatwang2/awesome-jev](https://github.com/fatwang2/awesome-jev).

Read in full — source, not README (see [docs/PRIOR-ART.md](docs/PRIOR-ART.md)):
`trungdq88/youtube-sponsor-detection`, `artbyjazi/autoclip`. The second is not Jev-based,
which is the point: it ships the same product with a generative model and no Jev anywhere.

Skimmed only, and re-reading their source is still a research task:
`ChetasLua/jevmeter`, `valentynkit/jev-skip`.

## What the reads have produced

Detail is in [docs/PRIOR-ART.md](docs/PRIOR-ART.md); what it changed here:

| Commit | Settled |
| --- | --- |
| `1b37b98` | v1 is verbal-only and the README says so. Nothing in the design can see a moment carrying no words; the non-verbal case is specced and deferred in [021](issues/021-event-clips.md) |
| `f30a3e8` | autoclip logged in PRIOR-ART |
| `e7b7f66` | [009](issues/009-edl-and-render.md): rendered edges align into the measured silence. The flat 150–250ms pre-roll it specified is the wrong fix — the gap before a word varies with how the speaker breathes |
| `46a3bad` | [013](issues/013-baseline-comparison.md): Baseline 4, snap + align with no model call. Baselines 1–3 all vary selection and boundaries together, so none of them isolates the thesis |
| `7eebb2d` | [003](issues/003-cut-point-extraction.md): a cut point is a gap, resolved to `t_start`/`t_end` by role. The midpoint reported a correct pick as wrong by half the gap, on `start_err_p90` |
| `8aace33` | [005](issues/005-pass-c-coarse-scan.md): windows step by seconds. Overlap counted in sentences shrank on fast speech, below a clip's length |

Three findings worth carrying forward:

- **ID-addressing is not a Jev advantage.** autoclip reached "the model never emits a
  timestamp" without Jev: word indices, every word tagged, so the model copies an index
  rather than deriving one. What survives is narrower — autoclip *clamps* an out-of-range
  index, while a Choice cannot emit an invalid option at all.
- **Failure modes 2 and 4 got more likely, not less.** autoclip refines boundaries in three
  deterministic passes with no model call, and treats the result as settled — its open gate
  for v0.1.0 is reframe quality. That is "snapping is good enough" and "classical methods
  already solve it", already in production.
- **The comparison found two defects in our own design** (`7eebb2d`, `8aace33`). Both were
  invisible until there was something to measure against, and neither was a model problem.

Nobody in the category publishes accuracy numbers — not autoclip, whose README says clip
picks are unverified, and not the sponsor repo, which commits no eval results. The
[011](issues/011-eval-set.md)/[012](issues/012-metrics-harness.md) harness would be the
first measurement in the space.

**Done, 2026-09-21: classical topic segmenters.** TextTiling measured against real labels
rather than read about — see failure mode 4 above and
[`eval/experiments/`](eval/experiments/texttiling_vs_labels.py). It does not reach clip
granularity, so it is not a candidate generator and not a Pass C prior.

**Most valuable next: evidence, not another codebase.** The README's three failure modes
still come from reasoning about the category rather than from anyone complaining. That is
failure mode 1, the one that costs most if true, and it lives in issue trackers and user
threads, not in source. Baseline 4 remains the live threat to the thesis and is now the
thing [006](issues/006-pass-d-boundary-refinement.md) has to beat.

## What would let building resume

Either:

- **Evidence for the thesis** — real examples where boundary error is the visible defect,
  and where an enumerated cut list would have fixed it. Then resume at issue 006.
- **Evidence against it** — then change the design before writing more code, and update
  the decision log in [ROADMAP.md](ROADMAP.md).
- **A better target entirely.** The research may turn up a place Jev fits more cleanly
  than auto-clipping does. That is a good outcome, not a wasted phase.

Nothing built so far is wasted either way: ingest, cut-point extraction, the traced client
and the coarse scan are all reusable, and the review log is a record of how this code
fails when written fast.
