# Question specs

The core of the project. Everything else is plumbing.

> The `L042` and `«C07»` notation is defined in [CONCEPTS.md](CONCEPTS.md).

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

`kind` selects the boundary instruction used in Pass D. That's the point of asking it.

---

## Pass D — boundary refinement

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

## Pass E — standalone gate

State: **the cut clip text and nothing else.** No title, no surrounding transcript. The
model should be in the same position as the viewer.

```python
{"clip": {"text": "…the exact words inside the cut…"}}
```

```python
VERIFY_QUESTIONS = {
    "starts_mid_thought": Noul(
        instructions=(
            "Does the first sentence of `clip.text` begin in the middle of a thought — "
            "continuing a sentence that started earlier, or answering a question that is "
            "not in `clip.text`?"
        ),
        criteria=NoulCriteria(
            true="Opens on 'and so', 'but then', 'yeah exactly', or an answer with no question",
            false="Opens on a complete thought of its own",
        ),
    ),
    "ends_mid_thought": Noul(
        instructions="Does `clip.text` stop before its last sentence is finished?",
        criteria=NoulCriteria(
            true="The final sentence is cut off or leads into something not included",
            false="The final sentence completes",
        ),
    ),
    "dangling_reference": Noul(
        instructions=(
            "Does `clip.text` refer to a person, place or thing using a word like 'he', "
            "'she', 'they', 'it', 'this' or 'that' without ever naming what it refers to "
            "inside `clip.text`?"
        ),
        criteria=NoulCriteria(
            true="A pronoun or 'that thing' points at something never named in this text",
            false="Everything referred to is named somewhere in this text",
        ),
    ),
    "standalone": Noul(
        instructions=(
            "Would a viewer who has seen nothing else understand `clip.text` from "
            "beginning to end?"
        ),
        criteria=NoulCriteria(
            true="Self-contained: the subject is named and the point is completed here",
            false="Requires something said before or after this text",
        ),
    ),
    "hook": Score(
        instructions="How well does the opening of `clip.text` hold attention?",
        criteria=[
            "Opens on logistics, throat-clearing, or an unfinished thought",
            "Opens on a plain statement of the subject",
            "Opens on a question, a claim someone would argue with, or a vivid image",
            "Opens on something a viewer would stop scrolling to hear the rest of",
        ],
    ),
    "payoff": Score(
        instructions="Does `clip.text` deliver what its opening sets up?",
        criteria=[
            "Sets something up and never returns to it",
            "Partly answers it; the rest is left hanging",
            "The point, outcome or punchline is stated plainly inside the text",
        ],
    ),
}
```

`standalone` overlaps the three specific Nouls on purpose. The specific ones are the
**gates** (they name a defect code can act on: widen the start, extend the end, drop). The
broad one is a **signal** for ranking. Don't collapse them: each Noul is absolute, and all
four can be low at once. That's the documented difference between one Choice over options
and one Noul per option.

---

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
