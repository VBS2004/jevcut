# Research phase

**Status: concluded 2026-09-22. Building resumes, with the design changed.**

The thesis was not killed and was not confirmed — it was **outgrown**. Five experiments
measured boundary placement and arithmetic stayed competitive every time; the sixth showed
why the proxies could never have decided it. Meanwhile the questions no constant can answer
even in principle went untested the whole time.

**The decision:** code owns boundaries, Jev owns judgment. Sentence snap plus
silence alignment sets `t0`/`t1` with no model call. Jev is spent on *is this worth
clipping, does it stand alone, does the payoff land* — where there is no offset, snap or
rule that competes, because arithmetic has nothing to work from.

This is the outcome this document pre-registered under failure mode 4: *"the honest move is
to use it for boundaries and reserve Jev for the judgments that genuinely need semantics.
That is a better product than the one currently designed, not a defeat."* It went that way.
See the decision log in [ROADMAP.md](ROADMAP.md).

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

## The thesis, measured on a proxy (2026-09-22)

`ami_coverage.py` showed the right cut is **on the sheet** 95% of the time. The thesis is
about whether it gets **circled**, and nothing had ever tested that. 900 requests, $0.078,
[`eval/experiments/pick_vs_snap.py`](eval/experiments/pick_vs_snap.py). Given a region with
cut points enumerated and an anchor inside a topic, how close to the human topic start does
each method land?

| method | median | p90 | ≤2s | ≤5s |
| --- | --- | --- | --- | --- |
| **jev** (Choice over cut points) | 8.7s | 31.0s | 20% | 34% |
| **snap to anchor−20s** (best of a sweep) | **5.5s** | **20.7s** | **24%** | **47%** |
| biggest pause in region | 15.0s | 47.7s | 19% | 25% |
| random cut from the same options | 20.6s | 56.0s | 11% | 17% |
| earliest cut in region | 61.7s | 73.7s | 0% | 0% |

**Two things are true at once, and both matter.**

1. **The mechanism works.** Jev beats a random pick from the identical option list by more
   than 2× on median, and beats the biggest-pause heuristic. It is extracting real semantic
   signal, not decorating a coin flip.
2. **It loses to a tuned constant offset.** Reproduced across two independent runs (8.7s,
   8.8s) and two wordings (variant B: 11.0s). **Confidence is flat** — 27–39% within 5s at
   every band — so no threshold rescues it.

**Caveats, and they are load-bearing.** A meeting's topic boundary is not a clip boundary:
subjects change gradually and by negotiation, where "this thought starts here" may be far
crisper. **There is no noise floor** (AMI has zero double-annotated meetings), so if two
humans would disagree by 10s here, every row above is inside the noise. The wording is
untuned — that is [014](issues/014-threshold-tuning.md)'s job. And the anchor is
synthesised, so a swept constant partly inverts this script's own sampling.

So this is a **warning, not a verdict**. It cannot kill the thesis. It does raise the bar.

**The pattern it belongs to is the real finding.** This is the fourth independent time a
constant or a simple rule has matched or beaten a clever method at boundary placement:

- autoclip refines boundaries with **no model call** and treats it as solved;
- StreamClipper and Streamsnip ship **trigger − 30s**, and people pay for one of them;
- Valand et al. measured their static **−A/+B** baseline at 5.89 against 6.84 for
  refinement — real, and about one point on a ten-point scale;
- and now a tuned constant beats a Choice on this proxy.

None of that says refinement is worthless — the soccer paper measured it as genuinely
better with 61 humans. It says **the margin is ~1 point and has to be fought for**, and
that any Pass D win must be demonstrated against a *tuned* constant rather than a strawman.
[013](issues/013-baseline-comparison.md) now carries that baseline.

### Repeated on YouTube chapters, and why neither proxy can settle it

The AMI result invited the obvious objection: a constant offset cannot generalise across
videos, and AMI is 139 meetings of one format. So it was repeated on **creator-authored
YouTube chapter markers** — heterogeneous single-speaker content, 5 videos with punctuated
manual captions, 41 boundaries.

**The objection is correct about constants.** Per-video best K ran 15–40s with no two
videos agreeing, and the penalty for using one global K was **+2.6s (79% worse than a
per-video oracle)**, against +1.5s (37%) on AMI. A fixed constant really does degrade as
content gets less uniform.

**And Jev still lost**: 11.3s median against 6.5s for one global K, with the same coverage
filter applied (32 cases). Worse than on AMI, not better.

**Then the number that explains both results.** The anchor-to-boundary distance across
those cases: median 27.0s, IQR 21.6–36.2s, **stdev 9.5s**. A perfect constant leaves 7.1s
median error — so the target sits at a nearly fixed distance from the anchor, and a swept
constant is largely recovering the experiment's own sampling distribution.

> **Neither experiment can settle the thesis, in either direction.** Topic and chapter
> boundaries are roughly evenly spaced, so "how far into a segment is a random point" has a
> stable answer and arithmetic estimates it well. A *clip's* start is not like that — the
> setup for one moment begins 3s back and for another 90s back — and that variance is
> precisely what a Choice could exploit and a constant cannot. The proxies do not contain
> it.

So this is not evidence that Jev works, and it is only weak evidence that it does not. What
would discriminate is a target whose distance from the anchor genuinely varies: real clip
starts, which is [011](issues/011-eval-set.md). Until then the thesis is untested, not
failing — and the [013](issues/013-baseline-comparison.md) baseline stands regardless,
because a Pass D that cannot beat arithmetic on *any* task is not worth two requests.

## Open, and deliberately not chased

**Does candidate coverage hold on a long single-speaker talk?** AMI answers the
speaker-count version of this (96% with labels stripped), but its sentences are shaped by
turn-taking, and a 45-minute uninterrupted talk has a different rhythm whose topic
boundaries may not land on sentence ends as cleanly.

Searched 2026-09-22, so nobody repeats it. The right-shaped corpus is
**Malioutov & Barzilay's manually segmented MIT lectures** (possibly distributed with
[bayes-seg](https://github.com/jacobeisenstein/bayes-seg)); VIDEOAULA (34 Portuguese CS
lectures) and AVL (86 boundaries) also exist. **The likely blocker is timings** — these are
sentence-indexed text, and without seconds they cannot test candidate coverage at all.

The realistic route is running ASR ourselves over single-speaker audio with known
boundaries, which YouTube chapter markers would supply free. Not worth it now: the claim
that sent us looking (coverage collapses without speaker changes) turned out to be false,
and [011](issues/011-eval-set.md)'s real labels answer the genre question better than a
proxy corpus in the wrong language. [003](issues/003-cut-point-extraction.md) carries the
per-genre criterion.

**Diarization — not needed for v1 (decided 2026-09-23).** Nothing in the real pipeline
labels speakers: `transcribe_media()` never sets `Word.speaker`, so `speaker_change` cut
points only exist when a word list with speaker tags is supplied by hand (`--from-json`).
Found by the second-video check on a FOSDEM panel. Not built, because:

- **It adds no coverage.** With speaker labels stripped from 968 AMI topic boundaries,
  coverage within 2s was 96%, against 95% with them. A turn change nearly always falls on
  a sentence end, so the cut point exists either way; `speaker_change` only renames it.
- **The one multi-speaker failure we hit didn't need it.** `needs_the_room` over-fired on
  panel cross-talk and was fixed by asking the model to tell speakers from audience in the
  question itself (false flags 23 of 92 → 1), with no speaker tags.
- **It is expensive here.** WhisperX / pyannote means a gated HuggingFace model, a heavy
  dependency, and more GPU memory on a 4GB card that Whisper already shares.

Revisit if clips from interviews start opening on the wrong person's turn, if captions
need speaker names, or if per-speaker selection ("only the guest's answers") becomes a
feature. The existing `speaker_change` code stays: idle on transcribed media, working when
tags are supplied.

## Baseline on the pilot eval set (2026-09-23)

The first measurement across more than one video. Eight YouTube videos in seven genres,
labeled per issue 011 (`eval/labels/`, 66 required clips, 36 `also_ok`, 39 hard
negatives; seven labeled blind), scored with `jevcut eval` at commit `0bddb2a`:

| | predicted | hit | also_ok | precision | recall | chance recall | in-range | on a negative |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| all 8 | 59 | 15 / 66 | 6 | 0.36 | 0.23 | 0.14 | 0.13 | 0.08 |

Per genre, recall runs from 0.00 (both tutorials) to 0.67 (the benchmark review), and
the animated explainer is *below* chance (0.17 vs 0.28).

**What it says, across genres rather than about one video:**

- **Boundaries and repair are where clips die, not selection.** Of 138 anchors, 79 were
  dropped by the gate, and 74 of those drops name a mid-thought start or end. The anchors
  sit on real moments; the placed clip around them starts or stops inside a thought, and
  the widen-only repair loop cannot fix a start that is too *early*.
- **Boundary precision fails outright.** 13% of matched clips have both edges inside the
  labeler's acceptable ranges. The claim in the README is not yet true.
- **When a clip survives it is usually real**: precision 1.00 on the science essay and
  the review, and only 8% of shipped clips sit on a labeled hard negative.
- **Labeling found the 75s cap too tight for long-form**: six strong moments run 84–113s
  (two podcast answers, a panel answer, an essay's close, a cold open).

This is the reference every change is scored against. It argues for replacing the
placement + widen/tighten rules with a search -- code lists start/end candidates at real
sentence boundaries, Jev judges each, code keeps the best -- and for keeping a change only
if it moves these numbers on the set, not on one video.

Caveats: one labeler per video, no human review yet, so no noise floor; the gate crashed
on three videos (HTTP 529) and they were rerun from cache, so the numbers are complete but
the gate needs to survive a failed request.

### Boundary search against that baseline (2026-09-24)

`11f5ebc` replaced placement + widen/tighten with a search (search.py): code lists every
opening at a real sentence boundary, Jev judges each; then every ending from the chosen
opening, judged as the finished clip. Same labels, same scorer:

| | predicted | hit | also_ok | precision | recall | chance | in-range | on a negative |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| baseline | 59 | 15 | 6 | 0.36 | 0.23 | 0.14 | 0.13 | 0.08 |
| search | 98 | 27 | 12 | 0.40 | 0.41 | 0.19 | 0.11 | 0.12 |

- **Selection improved, boundaries did not.** Recall's lift over chance went 0.09 → 0.22
  (panel 0.33 → 0.75, the screen tutorial 0 → 0.60, commentary 0.10 → 0.40) with precision
  held. But only 3 of 27 matches have both edges in range, the thing the search was built
  to fix; 8 of 27 starts and 13 of 27 ends are in range, with errors symmetric (7 early,
  7 late at the start; median 0s) -- noise, not bias.
- **More shipped clips sit on hard negatives** (12 of 98 vs 5 of 59): keeping more clips
  keeps more of the tempting-but-wrong ones.
- **Kept**, because it wins on finding moments and ties on edges. Whether 8 of 27 starts
  is poor or is what "where does this thought start" allows cannot be known without a
  second labeler: the noise floor (issue 011) is now the blocking measurement.
- Cost: ~2,000 gate requests for 8 videos (≈4.5 hours of media) vs a few hundred; the
  debate lost 80 requests to provider overload and was scored on what survived.

### The noise floor, and what it says about the edges (2026-09-24)

A second labeler (B) labeled all eight videos blind -- transcripts only, never opening
labeler A's files or any jevcut output -- into `eval/labels-b/`. `jevcut agree`:

| | A's clips | B's clips | both | A's found by B | B's found by A | start delta p50 / p90 | end delta p50 / p90 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| all 8 | 66 | 56 | 45 | 0.68 | 0.80 | 0.0s / 0.1s | 0.0s / 5.9s |

- **Which moments: two careful labelers share about 70-80%.** That is roughly the ceiling
  for recall against either one; jevcut's 0.41 is about half of it.
- **Where they start: the same sentence, almost always.** On the 45 shared moments the
  start delta is 0 at the median and 0.1s at p90. jevcut's matched starts are in range 8
  of 27 times with an 8s median error, so **its edges are genuinely wrong, not the task
  being fuzzy** -- the gap the next change has to close.
- **Robust to the labeler.** Scored against B instead of A, the search run gives
  precision 0.34 (A: 0.40), recall 0.39 (0.41), chance 0.18 (0.19), in-range 0.27
  (0.11), on a negative 0.05 (0.12). Selection numbers barely move; the edge number is
  small-sample either way.
- **Caveat: both labelers are the same model** reading the same transcript, so they snap
  to the same sentence boundaries more readily than two humans would. Treat 0.0s as a
  lower bound on disagreement, not the human floor; one human review pass would bound it
  from the other side.

### Shortest clean ending, and the rubric that had to change first (2026-09-24)

The product spec, from review of the Olga clips: **a clip is the shortest cut that works,
opening on its hook.** The search's ending picked the strongest `payoff`, which rises with
more material. Changed to the earliest ending clean on `ends_mid_thought` (below the same
0.5 bar the opening uses), else the least unfinished one. Every candidate was already in
the response cache, so all of this was measured by replay at zero requests.

**On the v1 labels it scored as a wash** -- median length 53 → 49s, recall 0.41 → 0.39,
end error 4.6 → 5.2s, more ends before the labeler's shortest acceptable ending (7 → 12).
Reading those "early" ends: five of six stop on the punchline and cut a restatement, a
second list item or a repeated line ("…anybody who claims to predict the future is lying
to you." vs the label running on to "There are too many variables."). The v1 labels ran
54s median because their brief asked for "the natural cut" and never said to prefer the
shorter of two working cuts. **The ruler did not state the spec,** so it scored the spec
as an error.

So the spec was written down first ([eval/RUBRIC.md](eval/RUBRIC.md)) and the set was
labeled again from scratch against it, by two new blind labelers (`eval/labels-v2/`,
`eval/labels-v2-b/`). They agree as tightly as v1's pair -- 80% of moments shared, starts
0.0s apart at p90, ends 6.0s -- at 40-42s median. Against them, same runs:

| ending rule | labeler | P | R | end error | ends early / in / late | start in range | length (labels) |
| --- | --- | --- | --- | --- | --- | --- | --- |
| strongest payoff | v2 A | 0.30 | 0.41 | 6.2s | 0 / 11 / 12 | 4 of 23 | 53s (42s) |
| earliest clean | v2 A | 0.29 | 0.39 | 4.0s | 4 / 8 / 10 | 3 of 22 | 49s (42s) |
| strongest payoff | v2 B | 0.30 | 0.37 | 5.2s | 0 / 11 / 10 | 6 of 21 | 53s (40s) |
| earliest clean | v2 B | 0.29 | 0.35 | 3.2s | 3 / 9 / 8 | 5 of 20 | 49s (40s) |

- **Kept.** The end error falls by a third against both labelers and clips shorten; recall
  moves by one clip. Ends are still more often late than early, so the ending is not yet
  short enough -- but it is now moving the right way on a ruler that says what "right" is.
- **The start is the open problem, and no selection rule fixes it.** Only 3-6 of ~22
  matched starts land in range, mostly late. Replaying every rule over the cached opening
  judgments (latest clean, cleanest, hook within a margin of the top, hook × cleanliness)
  moves in-range by at most a few clips on either label set, inside the noise. Two causes
  under the rules:
  - **The start judgments are miscalibrated for this.** Of labeled starts that are
    candidates, the gate calls only 31 of 52 (v1) and 18 of 35 (v2) clean, so the
    cleanliness filter discards the right start about half the time. `hook` ranks the
    labeled start first among ~9 candidates only a third to a half of the time, though it
    is usually top three and within 0.1-0.15 of the best (on a 0-3 scale): a real signal
    swamped by per-candidate noise, because each opening is scored alone.
  - **1 in 5 labeled starts is not a candidate at all.** Whisper `small` drops full
    stops ("…which is exactly why it works Law four…", "…solve them So I want to…"), so
    the true sentence start sits inside an ASR line with no `sentence_end` before it.
    Whether `large-v3` recovers them is the next measurement.

### The opening as one Choice (2026-09-24)

If each opening scored alone is noise-bound, ask a relative question instead: mark every
candidate opening in the transcript around the moment (renumbered from `C00`, 20s of
context past the anchor) and let one Choice pick the mark to come in on
([`eval/experiments/opening_choice.py`](eval/experiments/opening_choice.py)). That is the
Pass D shape, which lost to a tuned constant on AMI topic starts; this is clip starts,
labeled twice, with a floor of 0.0s.

**The opening alone**, same anchors and candidates, current rule replayed from cache.
Starts in range:

| labels | strongest hook among clean | Choice, "prefer the later mark" | Choice, no tiebreak |
| --- | --- | --- | --- |
| v2 A (44) | 13 | 15-17 | 17 |
| v2 B (41) | 15 | 14-17 | 19 |
| v1 A (64) | 28 | 21 | 30 |
| v1 B (63) | 20 | 18 | 27 |

- The first wording ended "of two marks that work equally well, prefer the later one".
  It hugged the anchor -- 58 of 138 picks took the last mark before it, 46 the one
  before that -- and ran late 26 to 6. Without the tiebreak it wins on all four label
  sets, and median start error halves (v2: 18.4 → 8.2s, 13.9 → 8.0s). It still leans
  late (22 to 8).
- Three runs of the first wording without the cache gave 15/14, 16/15 and 17/17: answer
  variance is about ±2 starts here, which the no-tiebreak margin (+4, +4, +2, +7) clears.

**The whole pipeline** with the Choice as the opening (`search.py`), all 8 videos re-cut:

| opening | labels | predicted | hit | P | R | in range | start err | clip length (labels) |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| strongest hook | v2 A | 100 | 22 | 0.29 | 0.39 | 0.05 | 6.9s | 49s (42s) |
| Choice | v2 A | 82 | 18 | 0.30 | 0.32 | 0.11 | 1.8s | 41s (42s) |
| strongest hook | v2 B | 100 | 20 | 0.29 | 0.35 | 0.15 | 4.7s | 49s (40s) |
| Choice | v2 B | 82 | 16 | 0.32 | 0.28 | 0.25 | 2.0s | 41s (40s) |
| strongest hook | v1 A | 100 | 26 | 0.38 | 0.39 | 0.08 | 4.7s | 49s (54s) |
| Choice | v1 A | 82 | 14 | 0.33 | 0.21 | 0.21 | 0.0s | 41s (54s) |
| strongest hook | v1 B | 100 | 23 | 0.32 | 0.41 | 0.22 | 1.5s | 49s (55s) |
| Choice | v1 B | 82 | 17 | 0.30 | 0.30 | 0.47 | 0.0s | 41s (55s) |

- **Edges: better on every label set.** Both-edges-in-range doubles or better; median
  start error falls to 0-2s; clips now run as long as the v2 labels (41s vs 40-42s), and
  ends stop running late (v2 A: 10 late → 1).
- **Recall: lower,** by 4 matches on each v2 set and more on v1, whose longer labels a
  shorter clip overlaps less. Fewer clips ship (82 vs 100): 35 of 47 drops are the final
  gate calling the Choice's opening mid-thought.
- **The veto is right more often than not.** On labeled moments, openings it vetoed were
  in range 23% of the time, openings it passed 50%. So it stays.
- **Retrying the runner-up on a veto was tried and cut.** Taking the Choice's
  second-weighted mark after a start veto shipped 12 more clips and ~100 more requests
  for 0-2 more hits per label set, with precision slightly down.
- **Cost halves:** 1,050 gate requests for the set against 2,017, ~7 per anchor against
  ~15 -- one Choice replaces ~9 opening judgments.
- **Kept**, as the trade the spec asks for: clips whose edges are right more than twice
  as often, at the length the rubric asks for, for a recall cost of about 4 of ~56
  labeled moments. Recall is now the thing to win back -- through the scan and the gate,
  not by loosening the edges.

**`large-v3` does not fix the missing openings.** Transcribed on the GPU (int8, ~1 min per
10 min of audio) for all 8 videos and checked the fair way -- of the labeled starts that
`small` has no real boundary within 1s of, how many does `large-v3` have? It recovers 15
of 44 missed starts but loses 27 of the 132 `small` had: 68% coverage against 75%. The
labels were timed on `small`'s words, which favours it, but not by enough to make
`large-v3` a clear win. The missing-punctuation hole stays open; the transcript model is
not the lever.

### The gate, judged on the labelers' own clips (2026-09-24)

Every rubric-v2 clip, also_ok and hard negative, cut from the transcript on its labeled
word times and judged exactly as a finished clip is
([`eval/experiments/gate_on_labels.py`](eval/experiments/gate_on_labels.py), 253 requests):

| | labeler A | labeler B |
| --- | --- | --- |
| required clips the gate passes | 53 / 56 (95%) | 52 / 57 (91%) |
| also_ok it passes | 25 / 28 (89%) | 30 / 35 (86%) |
| hard negatives it passes | 18 / 39 (46%) | 19 / 38 (50%) |

Separation, clip over negative (AUC; 0.5 is none): `standalone` 0.79 / 0.74,
`needs_the_room` 0.75 / 0.79, `dangling_reference` 0.75 / 0.67, `payoff` 0.75 / 0.73,
`hook` 0.71 / 0.63, `starts_mid_thought` 0.70 / 0.64, `ends_mid_thought` 0.63 / 0.59.

- **At the right edges the gate passes good clips.** Its failures on labeled clips are
  a handful of borderline ends. So the recall lost to start vetoes after the opening
  Choice is the gate reading openings that really are wrong, not a miscalibrated
  question -- the earlier "half of labeled starts judged unclean" came from short probe
  clips that stopped at the anchor, not from the clip itself.
- **It cannot reject what it has no question for.** Of the 18 negatives it passes (A),
  six are sponsor reads or plugs that open like part of the argument, and most of the
  rest depend on the screen: numbers read off a chart, narration of a live demo.
  `needs_the_room` covers the audience; nothing covers an ad or the screen, though the
  rubric names both. Shipped clips rarely land on these (on-negative 0.10 / 0.04), but
  an ad shipped as a clip is the most visible failure there is.
- **Recall is lost mainly in the scan.** Of the labeled clips jevcut misses, 23 of 38 (A)
  and 27 of 41 (B) never had an anchor inside them; the search and gate lose the rest.
  Winning recall back starts at Pass C, not at the gate.

### The ad check (2026-09-24)

A `promotion` Noul -- is this a sponsor read, an ad or a self-plug rather than the
discussion? -- spread-tested alone on all 253 rubric-v2 texts
([`eval/experiments/promotion_question.py`](eval/experiments/promotion_question.py)):
17 of 17 promotions fired (median 0.95), 0 of 236 content texts did (none above 0.05),
product reviews included. Wired in as one request on each finished clip.

On the pilot set it drops four clips: the WorkOS and Parallel sponsor reads in the Theo
video (the first opens "after a real quick break for today's sponsor" and reads as a
personal story), and two borderline self-plugs -- will.i.am on his own company's agent
("we point out in our course"), and Sean on his own agent's design. Against every label
set: no hit lost, precision up 0.01-0.02, share of clips on a hard negative 0.10 → 0.06
(v2 A) and 0.04 → 0.01 (v2 B). +91 requests, about one per clip. Side by side with every
other version in [BENCHMARKS.md](BENCHMARKS.md).

### Lemonfox transcripts, and a range check that was too strict (2026-09-24)

**Lemonfox** (hosted Whisper, punctuation and speaker labels; $0.50 per 3 hours, all 8
videos in under 2 minutes) put a real boundary within 1s of 78% of labeled starts,
against 75% for Whisper `small` and 68% for local `large-v3`, recovering 20 of the 44
starts `small` misses -- although the labels were timed on `small`'s words. It labeled
speakers on the panel and the debate (5 and 4), which become speaker-change cuts.

**The range check was too strict for any cross-transcript comparison.** Two ASRs time the
same word 0.08s apart at the median and 0.26s at p90, many labeled ranges are a single
point, and the check had no tolerance -- so the same boundary on another transcript
scored as a miss, and even on `small` a handful of starts sat a few tenths outside a
point range. `evaluate.RANGE_SLACK_S = 0.3` now applies to every version; `jevcut bench`
re-scored them all. **Every "in range" figure above this section was measured without
it.**

That re-scoring changes one conclusion. Counting matched clips with *both* edges right
-- the count that is the spec:

| version | v2 A | v2 B | v1 A | v1 B | recall v2 A / B |
| --- | --- | --- | --- | --- | --- |
| search (strongest-hook opening) | 6 | 7 | 11 | 8 | 0.41 / 0.37 |
| opening-choice / promotion-gate | 5 | 6 | 8 | 10 | 0.32 / 0.28 |
| lemonfox-asr (promotion-gate pipeline) | 5 | 9 | 13 | 9 | 0.38 / 0.46 |

- **The opening Choice raised the *rate* of right edges** among matched clips (v2 B 0.33
  → 0.38, v1 B 0.36 → 0.59) and brought clips to the rubric's length, **but it did not
  raise the count** of fully right clips: it found fewer moments. It stays -- shorter,
  cheaper, and the edges it finds are right more often -- but the claim above that it
  won "on every label set" was a rate, not a count.
- **Lemonfox wins back the recall** the Choice cost, on every label set (v2 B 0.28 →
  0.46, v1 A 0.21 → 0.38), and has the most fully right clips on three of four sets.
  Precision drops 0.03-0.06: the scan finds more anchors on a better-punctuated
  transcript (166 vs 138) and more of them ship (120 clips vs 78). Gate requests rise
  with them, 1,141 → 1,477.

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
