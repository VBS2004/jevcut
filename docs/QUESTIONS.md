# Question specs

The core of the project. Everything else is plumbing.

> The `L042` and `«C07»` notation is defined in [CONCEPTS.md](CONCEPTS.md).

> **The lessons here that are not about clipping have been lifted into a reusable skill**,
> `~/.claude/skills/jev-questions/`: criteria that describe situations rather than words,
> the spread test for whether a question discriminates at all, when to reach for a Noul
> over a Choice, keeping judgment separate from policy, and the failure patterns that look
> like model errors and are not. Written from what this project measured, including the
> mistakes. Update it when this file learns something general.

Rules these obey, from [how to build with System One](https://docs.typesafe.ai/concepts/how-to-build-with-system-one.md)
and the [jaggedness page](https://docs.typesafe.ai/model-jaggedness/jev-1.13.md):

- **One narrow judgment per question.** Never "is this a good clip and where does it start".
- **Write the literal condition.** Jev answers the question you wrote, not the one you
  meant. If you catch yourself explaining what you really meant, that explanation is the
  missing half of the instruction.
- **Criteria extend the instruction, never contradict it.** A Noul whose `true` maps to
  "no" performs worse.
- **Point at state by name.** Backticked paths like `clip.text`, `window.lines[3]` —
  indirection costs accuracy.
- **Always include a no-match option** on a Choice. Probabilities sum to 1; something wins
  whether or not anything fits.
- **Score levels describe concrete situations**, never degrees. "Moderately strong" gives
  the model nothing to match against; the docs show numbers-only levels collapsing to
  confidence 0.5.
- **Don't carry thresholds between primitives.** A threshold tuned on a Noul is
  meaningless on a Choice. Don't expect `P(x) + P(not x) == 1` either.

---

## Pass C — coarse scan

State: one window. `{"window": {"video_title": str, "lines": ["L000| …", …]}}`
(~80 lines). All three questions in a single request.

```python
from typesafe_sdk import Choice, Noul, NoulCriteria

SCAN_QUESTIONS = {
    "contains_moment": Noul(
        instructions=(
            "Does `window.lines` contain a moment that would hold a stranger's "
            "attention on its own — a story, a strong opinion, a surprising fact, a "
            "joke, or a clear explanation of one idea?"
        ),
        criteria=NoulCriteria(
            true="At least one stretch of these lines has a point that arrives and lands",
            false="Only logistics, filler, greetings, repetition, or talk that only makes "
                  "sense as part of a longer discussion",
        ),
    ),
    "anchor": Choice(
        instructions=(
            "Which line of `window.lines` is the single line a viewer would quote — the "
            "sentence the moment is actually about? Choose `none_of_these` if no line in "
            "this window would be quoted on its own."
        ),
        criteria={**{f"L{i:03d}": None for i in WINDOW_IDS}, "none_of_these": "No line here stands out"},
    ),
    "kind": Choice(
        instructions="What kind of moment is the strongest one in `window.lines`?",
        criteria={
            "story":       "A personal account with a beginning and an outcome",
            "hot_take":    "A strong opinion or claim stated plainly",
            "explanation": "One idea explained so a newcomer follows it",
            "joke":        "A setup and a punchline",
            "demo":        "Showing or walking through something concrete",
            "none":        "None of these describe anything in these lines",
        },
    ),
}
```

Line option descriptions are `None` because the state already carries each line's text —
straight from the semantic-find cookbook.

The answer is read by stretch, not by line: code sums the vote over ±20s around each line
and takes Jev's top line inside the strongest stretch (see ARCHITECTURE §C). The wording
is unchanged — Jev still names the quotable line; code only stops a moment told over
several lines from losing to one louder line because its vote was split.

`kind` was asked to select Pass D's boundary instruction. With Pass D off the critical path, nothing decides on it any more: it is stored on each anchor and clip (`Clip.kind`, written to the EDL) as a label. It costs one Choice per scan window; keep it if presets (020) use it, drop it if 014 finds no use.

---

## Pass D — boundary refinement

> **Off the critical path since 2026-09-22.** Boundaries are set in code now (`boundaries.py`); a tuned constant matched or beat this Choice on every boundary task measured. Kept as the spec for 006 in case the gate ever shows the code boundaries are what is wrong with the clips. See [RESEARCH.md](../RESEARCH.md).
>
> **The start half came back on 2026-09-24**, in a different shape: `opening` below, one Choice over the search's real-boundary openings, measured against two labelers. The end half, the escapes and the speculative Nouls have not.

State: anchor ±90s, cut points inlined as `«C07»` between sentences.

```python
{"clip_region": {
    "anchor_line": "L042",
    "text": "L039| …  «C05» L040| …  «C06» L041| …  «C07» L042| …"
}}
```

```python
REFINE_QUESTIONS = {
    "start_cut": Choice(
        instructions=(
            "The moment in `clip_region` is the one containing `clip_region.anchor_line`. "
            "A viewer will start watching at one of the «C..» marks. Which mark is the "
            "LATEST one that still includes everything the viewer needs to hear for that "
            "moment to make sense — the question being answered, the subject being named, "
            "the setup before the punchline? Do not choose a mark that starts in the "
            "middle of a sentence or after the subject has already been named."
        ),
        criteria={**{cid: None for cid in CUTS_BEFORE_ANCHOR}, "before_this_region": (
            "The setup begins earlier than any mark shown here")},
    ),
    "end_cut": Choice(
        instructions=(
            "Which «C..» mark is the FIRST one after the moment containing "
            "`clip_region.anchor_line` is complete — the point has landed and what follows "
            "starts a new subject or trails off into filler? Do not choose a mark that "
            "lands before the outcome, answer or punchline is stated."
        ),
        criteria={**{cid: None for cid in CUTS_AFTER_ANCHOR}, "after_this_region": (
            "The moment is still going at the end of the region shown")},
    ),
    "needs_more_setup": Noul(
        instructions=(
            "Would a viewer who starts at the earliest «C..» mark shown in `clip_region` "
            "still be missing something they need in order to follow the moment?"
        ),
        criteria=NoulCriteria(
            true="The moment refers to a person, thing or question introduced before this region",
            false="Everything needed is inside this region",
        ),
    ),
    "cold_open_ok": Noul(
        instructions=(
            "Is the line containing `clip_region.anchor_line` strong enough to be the very "
            "first thing a viewer hears, with nothing before it?"
        ),
        criteria=NoulCriteria(
            true="It states a claim, question or image that makes sense with no setup",
            false="It only makes sense after something earlier",
        ),
    ),
}
```

`needs_more_setup` and `cold_open_ok` are **speculative** — asked before we know which
start wins, consumed by code only on the branch that applies. They cost tokens and nothing
else; they run in parallel against a state Jev ingests once. `cold_open_ok` true means code
may skip the setup entirely and start at the anchor — the tightest possible clip.

The `before_this_region` / `after_this_region` escapes are what let code **widen the window
and re-ask** instead of silently accepting a truncated clip.

---

## The opening — one Choice per anchor

State: the transcript from the earliest candidate opening to 20s past the anchor, every
candidate marked in place and renumbered from `C00`, plus the anchor line as the moment.

```python
{"region": {"text": "L039| …  «C00» L040| …  «C01» L041| … L042| …", "moment": "…"}}
```

| question | type | asks | role in the boundary search |
| --- | --- | --- | --- |
| `opening` | Choice over the marks | at which mark should a short clip around the moment start: on the line that grabs, keeping the setup it needs | picks the opening |

Wording in `src/jevcut/questions.py` → `opening_questions()`.

- **Why a Choice, when Pass D's lost.** Pass D was measured against topic starts in
  meetings, with no second labeler. Against clip starts labeled twice, judging each
  opening alone (strongest `hook` among the clean) was noise-bound: the right start was
  usually top three on `hook`, within 0.1-0.15 of the best, and the cleanliness filter
  discarded it about half the time. A Choice sees every candidate at once, so it only
  has to rank them. It landed more starts in range on all four label sets (RESEARCH.md).
- **The Choice ranks; the gate checks.** The pick is not final until the finished clip
  is judged: an opening the gate reads as mid-thought, dangling, or with no hook gives way
  to the Choice's next picks, judged against the same ending (`search._check_opening`).
  Three rewordings of this question itself were tried on 38 videos and none moved the
  worst starts (RESEARCH.md).
- **"Prefer the later mark" was tried and cut.** It pushed picks onto the anchor line
  itself: 58 of 138 took the last mark. The picks still lean late without it, which is
  the open problem, not a wording to tune here.

---

## The ad check — one Noul per shipped clip

State: the finished clip's text, as for the gate. Asked once, after the search has picked
both edges, so it costs one request per clip rather than one per candidate ending.

| question | type | asks | role |
| --- | --- | --- | --- |
| `promotion` | Noul | is the clip a sponsor read, an ad, or the speaker plugging something of their own, rather than the discussion itself | drops the clip |

Wording in `src/jevcut/questions.py` → `promotion_questions()`.

- **Why it exists.** Judged on the labelers' own texts, the gate passed half the hard
  negatives, and a third of those were sponsor reads and plugs: written to open like part
  of the argument, they read as self-contained, hooky and paid off, so no other question
  can see them.
- **Spread-tested before wiring in** ([`eval/experiments/promotion_question.py`](../eval/experiments/promotion_question.py)),
  on all 253 rubric-v2 texts: it fired on 17 of 17 promotions (median 0.95) and on none of
  the 236 content texts (none above 0.05), product reviews included. The `false`
  criterion says outright that naming, praising or reviewing a product is still content.
- A failed request ships the clip: losing a real moment to a provider error costs more
  than the rare ad it might have caught.

---

## Pass E — the clip gate

State: **the cut clip text and nothing else.** No title, no surrounding transcript. The
model should be in the same position as the viewer.

```python
{"clip": {"text": "…the exact words inside the cut…"}}
```

**The exact wording lives in `src/jevcut/questions.py` → `verify_questions()`, and only
there.** This section used to carry a full copy, the copy drifted, and for two days it
showed a version that rejected every clip of real speech. What belongs here is what each
question is for and why it is worded the way it is.

| question | type | asks | role in the boundary search |
| --- | --- | --- | --- |
| `needs_the_room` | Noul | does the point depend on the live **audience** rather than on what the speakers say | fails the finished clip |
| `starts_mid_thought` | Noul | does the opening depend on something the viewer was not given | fails the finished clip |
| `dangling_reference` | Noul | does it turn on something the viewer cannot identify from the clip alone | fails the finished clip |
| `ends_mid_thought` | Noul | does it stop before the point it was making arrives | chooses the ending |
| `standalone` | Noul | would a viewer who has seen nothing else follow it | fails the finished clip |
| `hook` | Score 0–3 | how well the opening holds attention | ranking |
| `payoff` | Score 0–2 | does it deliver what the opening sets up | ranking; bottom level fails the clip |

### What changed, and why

- **Criteria describe situations, not words.** The first version said a clip starting
  mid-thought "opens on 'and so', 'but then', 'yeah exactly'". People speak in
  connectives, so against a real talk it fired on nearly every excerpt. Listing the
  connectives that were *fine* instead was the same mistake inverted.
- **`worth_clipping` deleted (2026-09-23).** Flattest question across 38 clips (0.07
  normalised), never fired, same result from two wordings. It asked the model to combine
  `hook` and `payoff`, which the ranking already does in code.
- **`needs_the_room` added, then reworded (2026-09-22/23).** Added after a human rejected
  a clip whose payoff was a show of hands. Its first criteria listed "an answer called
  back, a reaction the speaker replies to" — every reply in a panel — and on a panel video
  it flagged half the anchors. Asking outright whether the point depends on the speakers
  or on an audience cut false flags from 23 of 92 to 1.
- **Measure before wiring in.** Every change above was spread-tested on real clip texts
  first; two rewrites that sounded better (`hook`, `worth_clipping`) measured worse and
  were not shipped. The method is in the `jev-questions` skill.

## Pass L — live tick

State: rolling 60s of transcript, re-sent each tick. One question.

```python
LIVE_TICK = {
    "in_moment": Noul(
        instructions=(
            "In `recent.text`, is the speaker in the middle of telling a story, making a "
            "strong claim, explaining one idea, or building to a punchline RIGHT NOW — at "
            "the end of this text?"
        ),
        criteria=NoulCriteria(
            true="The last few sentences are building toward a point not yet delivered, "
                 "or delivering one",
            false="The last few sentences are logistics, filler, small talk, or a subject "
                  "that just ended",
        ),
    ),
}
```

"RIGHT NOW — at the end of this text" is load-bearing. Without it Jev answers about the
whole 60s, and the FSM fires on moments that already ended.

## Pass R — retro start (live)

```python
RETRO_START = Choice(
    instructions=(
        "The speaker is in the middle of a moment at the end of `buffer.text`. Which «C..» "
        "mark is the LATEST one that still includes the start of that moment — where the "
        "subject is first named or the setup begins?"
    ),
    criteria={**{cid: None for cid in BUFFER_CUTS}, "before_this_buffer": (
        "The moment started before this buffer")},
)
```

`before_this_buffer` firing often means the 90s ring buffer is too short for this content
type. That's a tunable, and a metric — see [EVAL.md](EVAL.md).

---

## Things deliberately NOT asked

| Tempting question | Why not | Instead |
| --- | --- | --- |
| "What timestamp should the clip start at?" | Jev doesn't generate; reads dates and numbers as text | Choice over cut IDs |
| "How long should this clip be?" | No numeric precision | duration band in code |
| "How many good moments are in this video?" | Counting is a documented failure mode | count anchors in code |
| "Rate this clip 1–100" | Score levels aren't numerically calibrated; you can't interpolate a magnitude | Score with described levels, weights in code |
| "Is this clip better than that one?" | Two clips in one state = irrelevant detail, and pairwise doesn't scale | comparable per-item Scores, rank in code |
| "Is this a good clip?" | Several judgments hidden in one question | the six Pass E questions |
