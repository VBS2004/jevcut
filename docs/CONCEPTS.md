# Concepts

Read this first. Every other document assumes these four ideas.

## The constraint everything follows from

Jev **cannot tell you a timestamp.** Two reasons, both from the
[jaggedness page](https://docs.typesafe.ai/model-jaggedness/jev-1.13.md): it is not
trained to generate text, and it reads numbers as text rather than as quantities, so it
cannot do arithmetic or compare times.

So "where should this clip start?" is an unanswerable question. But **"which of these
options is the start?"** is answerable, and that is the whole design:

> Code enumerates every plausible boundary and labels it. Jev picks a label.
> Code maps the label back to a timestamp.

The model never sees a number. Code never guesses a boundary.

## The three IDs

| ID | What it is | Who picks it |
| --- | --- | --- |
| `L018` | a **sentence** — one addressable line of transcript | Pass C picks one as the *anchor*: the quotable line |
| `C03` | a **cut point** — one candidate place to cut | Pass D picks one as the start and one as the stop |
| — | a **region** — the slice of transcript sent in one request | built by code around an anchor |

Sentence IDs come from the
[line-by-line search cookbook](https://docs.typesafe.ai/cookbooks/semantic_find.md):
render the transcript as `L042| text…` so a Choice can point at a line. Cut IDs do the
same thing for boundaries.

## Cut points, concretely

A cut point is a place you *could* cut: the end of a sentence, a pause of 350ms or more,
a speaker change, a scene change, or either end of the transcript. `cuts.py` finds them
all, merges ones that coincide, and thins them to roughly one every 2–4 seconds.

They are written into the transcript as `«C03»` markers at their real positions —
including mid-sentence, when the pause is mid-sentence.

**This is what Jev sees:**

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

**This is what code keeps, and never sends:**

```
C00 ->  55.05s  (speaker_change)
C01 ->  59.42s  (speaker_change)
C02 ->  64.61s  (sentence_end)
C03 ->  67.25s  (sentence_end)
C04 ->  69.70s  (sentence_end)
C05 ->  74.30s  (speaker_change)
```

Pass D asks *"which `«C..»` mark is the latest one that still includes everything the
viewer needs?"* Jev answers `C03`. Code looks up 67.25s and hands it to ffmpeg.

### Why the marker list is the most important output in the project

Look at the example again: **there is no marker between `L013` and `L014`.** So no clip
can ever start on "And we had no backoff on the client side." Not because Jev would
refuse — because it was never offered the choice.

> The model cannot choose a value that was omitted.

A missing marker is a boundary that does not exist. And in the traces it looks *identical*
to the model choosing badly. That is why issue 003's acceptance criterion is a recall
check — "is there a candidate within 1 second of every boundary a human picked?" — and
why [issue 010](../issues/010-trace-logging.md) classifies `missing_candidate` before
anything is called a model error.

You can look at this yourself for any anchor:

```bash
uv run jevcut region t.json L018 --cuts c.json
```

## Regions

You never send the whole transcript. Accuracy falls as the state fills with irrelevant
material, and there is a 32k-token cap on state plus the longest question anyway.

So once Pass C names an anchor, code builds a **region**: that anchor ± `region_pad_s`
(90 seconds by default), with the cut markers inside it **renumbered locally from `C00`**.
That region is the entire state for one Pass D request.

Local numbering is deliberate. `C00` always means "the first option in this region",
whether the anchor sits at minute 2 or minute 200 — so the option list stays short and
the question is identical everywhere. The mapping back to real timestamps lives in
`Region.cuts_by_id`, in code.

A region carries two escape options, `before_this_region` and `after_this_region`. When
one wins, it means the setup starts earlier (or the moment runs later) than anything
offered — so code widens the region and asks again, instead of accepting a clip it knows
is truncated.

## Anchors

An **anchor** is the single line a viewer would quote — the sentence a moment is actually
*about*. Pass C finds them cheaply across the whole video; Pass D then spends real money
only around each one.

An anchor is not a boundary. It is a pointer at where a moment lives, which is a much
easier judgment than where it begins and ends, and it is why the cascade is cheap: finding
anchors costs one request per 80 sentences, and only the survivors get the expensive
boundary work.

## Putting it together

```
transcript   L000 L001 L002 ... L018 ... L400        (002)
                              ▲
cut points   «C00» ... «C03» ... «C07» ...           (003)
                              │
Pass C       anchor = L018, kind = story             (005)
                              │
region       L018 ± 90s, cuts renumbered C00..Cnn    (003)
                              │
Pass D       start_cut = C03, end_cut = C09          (006)
                              │
code         C03 -> 67.25s, C09 -> 96.40s            → ffmpeg
```

Terms used elsewhere in the docs: **Pass C** is the coarse scan, **Pass D** boundary
refinement, **Pass E** the standalone gate, **Pass F** ranking. They are described in
[ARCHITECTURE.md](ARCHITECTURE.md) and specified question-by-question in
[QUESTIONS.md](QUESTIONS.md).
