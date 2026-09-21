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

Three ways this could be wrong, in order of how much they'd cost us:

1. **Selection is the hard part, not boundaries.** If humans mostly disagree about
   *which* moments to clip and barely at all about where they start, the whole cut-point
   apparatus is solving a problem nobody has.
2. **Snapping is good enough.** If sentence-boundary snapping lands within the range a
   human would accept, the Choice-over-cut-points machinery buys precision nobody
   perceives.
3. **The gate rejects too much.** If `standalone` and `dangling_reference` fire on clips
   humans find perfectly fine, we ship fewer clips than a naive tool and call it quality.

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

## Starting points

Directories, refreshed weekly:
[hellogumbo/awesome-jev](https://github.com/hellogumbo/awesome-jev),
[cobanov/awesome-jev](https://github.com/cobanov/awesome-jev),
[logicrw/awesome-jev-projects](https://github.com/logicrw/awesome-jev-projects),
[AnotiaWang/awesome-jev](https://github.com/AnotiaWang/awesome-jev),
[fatwang2/awesome-jev](https://github.com/fatwang2/awesome-jev).

Already studied (see [docs/PRIOR-ART.md](docs/PRIOR-ART.md)):
`trungdq88/youtube-sponsor-detection`, `ChetasLua/jevmeter`, `valentynkit/jev-skip`.
These were skimmed, not read. Re-reading their source is itself a research task.

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
