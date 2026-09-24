# Labeling rubric (v2)

What a label says, and so what jevcut is scored against. v2 adds the product spec the v1
labels did not state: **a clip is the shortest cut that works, opening on its hook.**

v1 (`eval/labels/`, `eval/labels-b/`) asked for "the natural cut" and never said to prefer
the shorter of two working cuts. Its labels ran 54s median; jevcut's matched that, and a
rule that ended clips on the punchline was scored as ending early (RESEARCH.md, "Shortest
clean ending"). v2 (`eval/labels-v2/`, `eval/labels-v2-b/`) is labeled from scratch under
this page, blind, so the ruler states the spec before anything is tuned to it.

## A clip

A stretch someone scrolling a feed, with no context, would watch to the end and get: a
self-contained point, story, joke, hot take, surprising fact or clear explanation. If the
point is something shown on screen ("look at this", a chart read aloud), it is not a clip.

## The start: open on the hook

- Start on the **first line that grabs** -- the claim, the question, the image, the
  surprising fact. Not the run-up to it: no "so", "okay so next", "let's talk about",
  "another thing is", housekeeping, or a sentence that only restates the previous topic.
- **But keep setup the payoff needs.** If the punchline only lands because of a line
  before the hook, that line is part of the clip. A clip that opens on a hook and then
  loses the viewer is worse than one that opens a sentence earlier.
- Never open mid-thought or on a pronoun that points before the cut.

## The end: stop when it lands

- End at the **earliest point where the payoff has landed**: the punchline, the answer,
  the conclusion.
- Stop there. Restating the point, summarising it, a second example of the same thing,
  "so yeah", a tangent, or the next topic's first line are not part of the clip.
- Never end mid-sentence, before the answer to a question the clip raises, or before the
  punchline.

## Length

The band is **25-75s**. Inside it, **shorter is better**: when two cuts both work, the
shorter is the preferred `start`/`end`. A moment that cannot land in 75s still gets
labeled, with its tightest working cut and `"over_band": true`.

## Ranges

`start_range` and `end_range` cover every edge a good editor would accept, with the
preferred edge inside. For the end, that runs from the shortest ending that lands to the
latest that adds nothing dead. Keep ranges honest: a few seconds unless two edges
genuinely both work, and then say so in `why`.

## Also OK, and hard negatives

- `also_ok`: clips an editor would accept but not insist on. Picking one is not a false
  positive and missing one is not a miss. Not a dumping ground.
- `negatives`: stretches that *sound* clippable -- energetic, a strong claim, numbers,
  laughter -- but do not stand alone: narration of the screen, a claim whose support came
  a minute earlier, sponsor reads, intros and calls to subscribe, room-only moments,
  inside references. 2-6 per video, only tempting ones.

## How many

As many as are genuinely good: typically 3-8 for a 10-30 min video, up to ~12 for 60+ min.
Fewer is fine. Never pad: a weak label makes the eval reward weak output.

## Independence

Labelers read only this page and the transcripts. Never jevcut's output (`edl.json`,
`index.html`, `anchors.json`, any `clipNNN.mp4`), never another labeler's files, never
RESEARCH.md or git history of labels. The two v2 labelers never see each other's work.
