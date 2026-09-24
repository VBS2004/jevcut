# Concepts

Read this first. Every other document assumes these four ideas.

## The constraint everything follows from

Jev **cannot tell you a timestamp.** Two reasons, both from the
[jaggedness page](https://docs.typesafe.ai/model-jaggedness/jev-1.13.md): it is not
trained to generate text, and it reads numbers as text rather than as quantities, so it
cannot do arithmetic or compare times.

So "where should this clip start?" is an unanswerable question. But **"which of these
options is the start?"** is answerable, and that was the original design:

> Code enumerates every plausible boundary and labels it. Jev picks a label.
> Code maps the label back to a timestamp.

That still holds for the anchor: Jev picks the `L018` a moment is about. For boundaries
it holds in a different shape: code enumerates the candidate openings and endings, and
rather than choosing a label from a list, Jev reads the clip each candidate would make
and judges it; code keeps the best ([RESEARCH.md](../RESEARCH.md) has why, measured).

The model never sees a number. Code never invents a boundary — it only offers the
enumerated ones.

## The three IDs

| ID | What it is | Who picks it |
| --- | --- | --- |
| `L018` | a **sentence** — one addressable line of transcript | Pass C picks one as the *anchor*: the quotable line |
| `C03` | a **cut point** — one candidate place to cut | **code lists, Jev judges**: the boundary search (`search.py`) judges a clip for each candidate opening and ending at a real boundary and keeps the best; `boundaries.py` aligns the rendered edge into the silence. Pass D was going to have Jev pick the mark outright; arithmetic kept winning that, see [RESEARCH.md](../RESEARCH.md) |
| — | a **region** — the slice of transcript sent in one request | built by code around an anchor |

Sentence IDs come from the
[line-by-line search cookbook](https://docs.typesafe.ai/cookbooks/semantic_find.md):
render the transcript as `L042| text…` so a Choice can point at a line. Cut IDs do the
same thing for boundaries.

### "But `L042` still contains a number"

It does, and that is fine, because the constraint above is narrower than it first reads.
Jev cannot do **arithmetic or ordering** on numbers. It never has to here: `L042` is a
**name**, not a quantity, and the only operation performed on it is matching.

The stronger reason: **in a Choice, Jev does not write the ID at all.** Code enumerates the
options; the answer is a probability spread across that enumerated set. There is no step
where the model must recall "042" and emit it correctly — it is putting weight on one
member of a list we own. Every project in [PRIOR-ART](PRIOR-ART.md) does the same and they
work; autoclip tags *every word* `[1042]word` and says outright that the model "never has
to derive an index, only copy one".

**Where it would genuinely break** is a question that asks Jev to compare or count IDs —
"is `L041` before `L088`?", "how many lines between these two?". That is arithmetic and it
would fail. Nothing here does it: order comes from code and from the fact that the state
renders lines in order already.

**The real risk is confusability, not numeracy.** `L041`, `L042` and `L043` differ by one
character, so a pick that lands on a neighbour of the intended line is plausible — an
off-by-one from labels that look alike, not from a model that cannot count. Opaque labels
(`qux`, `vim`) would be harder to confuse, at the cost of every trace and region render
becoming unreadable to a human.

That is a measurable question rather than an argument: the top-2 margin already says when a
pick was confusable, [010](../issues/010-trace-logging.md) reports the adjacency rate, and
[014](../issues/014-threshold-tuning.md) A/B-tests the label scheme. Do not change it on
taste.

## Cut points, concretely

A cut point is a place you *could* cut: the end of a sentence, a pause of 350ms or more,
a speaker change, a scene change, or either end of the transcript. `cuts.py` finds them
all, merges ones that coincide, and thins them to roughly one every 2–4 seconds.

They are written into the transcript as `«C03»` markers at their real positions —
including mid-sentence, when the pause is mid-sentence.

**This is how `jevcut region` prints them:**

```
«C00»
L012| That is the thundering herd problem.
«C01»
L013| Exactly.
L014| And we had no backoff on the client side.
«C02»
L015| None.
L016| That was the whole bug.
«C03»
L017| Three characters of config.
«C04»
L018| That is what took down checkout for ninety minutes.
«C05»
L019| How did you find it?
```

**This is what code keeps:**

```
C00 ->  55.05s  (speaker_change)
C01 ->  59.42s  (speaker_change)
C02 ->  64.61s  (sentence_end)
C03 ->  67.25s  (sentence_end)
C04 ->  69.70s  (sentence_end)
C05 ->  74.30s  (speaker_change)
```

The search offers marks as candidate edges; for each, Jev judges the clip text that would
fall between them, and code keeps the best — say `C03` — looks up 67.25s, moves the edge
into the silence around it, and hands that to ffmpeg. Jev never sees the marks
themselves, only the clips they would make.

### Why the marker list is the most important output in the project

Look at the example again: **there is no marker between `L013` and `L014`.** So no clip
can ever start on "And we had no backoff on the client side." Not because anything judged
it a bad start — because it is not on the list. The boundary search only ever offers
marks as candidates, never the space between them.

> Nothing can choose a boundary that was omitted.

A missing marker is a boundary that does not exist. And in the output it looks *identical*
to a bad boundary choice. That is why issue 003's acceptance criterion is a recall
check — "is there a candidate within 1 second of every boundary a human picked?" — and
why [issue 010](../issues/010-trace-logging.md) classifies `missing_candidate` before
anything is called a model error.

You can look at this yourself for any anchor:

```bash
uv run jevcut region t.json L018 --cuts c.json
```

## Regions

A **region** is an anchor ± `region_pad_s` (90 seconds by default), rendered with its cut
markers **renumbered locally from `C00`** — the example above is one. It was built as the
state for a Pass D request, with two escape options (`before_this_region`,
`after_this_region`) for a moment that runs past its edges.

Nothing in the clip pipeline builds one now: boundaries are code, and the gate's state is
the clip text alone. `jevcut region` still prints one, and it is the quickest way to see
which cut points exist around an anchor — and so which boundaries a clip *could* have.

## Anchors

An **anchor** is the single line a viewer would quote — the sentence a moment is actually
*about*. Pass C finds them cheaply across the whole video; only around those anchors does
the boundary search spend requests judging candidate clips.

An anchor is not a boundary. It is a pointer at where a moment lives, which is a much
easier judgment than where it begins and ends, and it is why the cascade is cheap: finding
anchors costs a few requests per 80 sentences, and only the survivors get the ~15
requests of the boundary search.

## Putting it together

```
transcript   L000 L001 L002 ... L018 ... L400        (002)
                              ▲
cut points   «C00» ... «C03» ... «C07» ...           (003)
                              │
Pass C       anchor = L018, kind = story             (005)
                              │
search       each opening mark judged, then each      search.py (007)
             ending: start = C03, end = C09
                              │
Pass F       rank by hook and payoff                 (008)
                              │
code         C03 -> 67.25s, C09 -> 96.40s            → ffmpeg (009)
```

Terms used elsewhere in the docs: **Pass C** is the coarse scan, **Pass D** the boundary
Choice that code replaced (006, off the critical path), **Pass E** the clip gate, **Pass F** ranking. They are described in
[ARCHITECTURE.md](ARCHITECTURE.md) and specified question-by-question in
[QUESTIONS.md](QUESTIONS.md).
