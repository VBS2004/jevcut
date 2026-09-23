"""Question builders, one function per pass.

These are the specs in docs/QUESTIONS.md, in code. Keep the two in sync: the wording is
the thing being tuned, and issue 014 A/B-tests these exact strings.
"""

from __future__ import annotations

from typesafe_sdk import Choice, Noul, NoulCriteria, Score

NO_ANCHOR = "none_of_these"

KIND_CRITERIA = {
    "story": "A personal account with a beginning and an outcome",
    "hot_take": "A strong opinion or claim stated plainly",
    "explanation": "One idea explained so a newcomer follows it",
    "joke": "A setup and a punchline",
    "demo": "Showing or walking through something concrete",
    "none": "None of these describe anything in these lines",
}


def scan_questions(line_ids: list[str]) -> dict:
    """Pass C. One request per window, three questions against the same state.

    `contains_moment` is absolute ("is there anything here at all?"); `anchor` is
    relative ("which line, given one must win"). They answer different questions, so
    their numbers are not comparable and thresholds never transfer between them.
    """
    return {
        "contains_moment": Noul(
            instructions=(
                "Does `window.lines` contain a moment that would hold a stranger's "
                "attention on its own -- a story, a strong opinion, a surprising fact, a "
                "joke, or a clear explanation of one idea?"
            ),
            criteria=NoulCriteria(
                true="At least one stretch of these lines has a point that arrives and lands",
                false=(
                    "Only logistics, filler, greetings, repetition, or talk that only "
                    "makes sense as part of a longer discussion"
                ),
            ),
        ),
        "anchor": Choice(
            instructions=(
                "Which line of `window.lines` is the single line a viewer would quote -- "
                f"the sentence the moment is actually about? Choose `{NO_ANCHOR}` if no "
                "line in this window would be quoted on its own."
            ),
            # Option descriptions are None because the state already carries each line's
            # text -- the semantic-find cookbook pattern.
            criteria={**{lid: None for lid in line_ids}, NO_ANCHOR: "No line here stands out"},
        ),
        "kind": Choice(
            instructions="What kind of moment is the strongest one in `window.lines`?",
            criteria=dict(KIND_CRITERIA),
        ),
    }


def verify_questions() -> dict:
    """Pass E. One request per candidate clip, seven questions over the clip text alone.

    **The state is the cut text and nothing else** -- no title, no surrounding transcript.
    Given the context, the model resolves the dangling pronoun from it and calls the clip
    fine; the viewer cannot. Putting the model exactly where the viewer sits is the whole
    mechanism, and it is the one thing to not "improve" by adding helpful context.

    Two kinds of question, and the difference decides what happens next:

    * **Worth** -- `needs_the_room`, `hook`, `payoff`. Irreparable: no boundary move
      brings a show of hands to someone watching later.

    There was a `worth_clipping` Noul here and it was deleted. Across 38 clips it had
    the flattest distribution of any question (0.07 normalised, and unbiased because it
    never gated, so unlike the others its spread was not truncated by its own
    rejections), it never once fired in 116 drops, and two separate wordings behaved the
    same. The reason is structural rather than verbal: "is this worth clipping" is
    `hook` and `payoff` aggregated, so it asked the model to do the combining that the
    composite-scoring pattern puts in code -- which then combined it again.
    * **Craft** -- the mid-thought pair, `dangling_reference`, `standalone`. Repairable by
      widening, because each one means "something the viewer needs is outside the cut".

    **Criteria describe situations, never words.** Two earlier versions of these questions
    listed the openings that counted as broken, then listed the ones that did not. Both
    were the same mistake: enumerating surface forms for a model that reads meaning. The
    first told it that starting on a conjunction was a defect, which is true of prose and
    false of speech, and every excerpt of a real talk failed. Describe what is true of the
    content and let it judge -- that is what the Score guidance in PRIOR-ART means by
    levels describing situations.
    """
    return {
        # --- worth: no boundary move fixes a no here ---------------------------------
        # Asks the model to tell speakers from audience instead of listing examples of
        # "live exchange". The first wording listed "an answer called back, a reaction the
        # speaker replies to", which is every reply in a panel: it flagged 23 of 92
        # ordinary clips across a solo talk and a panel. Stating the distinction outright
        # dropped that to 1 of 92 -- the model can make it; it only had to be asked.
        "needs_the_room": Noul(
            instructions=(
                "`clip.text` has one speaker or several speakers talking with each other, "
                "and there may also be an audience listening who are not speakers. Does the "
                "point of the clip depend on that audience rather than on what the speakers "
                "say?"
            ),
            criteria=NoulCriteria(
                true=(
                    "The point turns on the audience: a speaker asks them to respond, and "
                    "what they did is what the clip builds to. Someone watching later was "
                    "never part of that audience, so the point does not reach them"
                ),
                false=(
                    "The point is carried by what the speakers say. Speakers replying to one "
                    "another is still speech a later viewer can follow in full, however much "
                    "they interrupt or answer each other"
                ),
            ),
        ),
        # --- craft: a yes here is a boundary problem, not a content problem -----------
        "starts_mid_thought": Noul(
            instructions=(
                "A viewer begins watching at the first word of `clip.text`, having heard "
                "nothing before it. Does the opening leave them unable to follow what is "
                "being talked about?"
            ),
            criteria=NoulCriteria(
                true=(
                    "The opening depends on something the viewer was not given: it "
                    "finishes a thought that began earlier, or replies to something said "
                    "before the clip"
                ),
                false=(
                    "The opening carries enough on its own for the viewer to follow it "
                    "from the first line"
                ),
            ),
        ),
        "ends_mid_thought": Noul(
            instructions="Does `clip.text` stop before the point it was making arrives?",
            criteria=NoulCriteria(
                true=(
                    "It stops while the speaker is still getting somewhere, leaving the "
                    "viewer waiting for the rest"
                ),
                false=(
                    "What the clip was building to has arrived by the time it ends, "
                    "whatever the speaker went on to say afterwards"
                ),
            ),
        ),
        "dangling_reference": Noul(
            instructions=(
                "Does `clip.text` turn on something the viewer cannot identify from the clip alone?"
            ),
            criteria=NoulCriteria(
                true=(
                    "The point rests on some person, thing or event that is never "
                    "identified here, so the viewer cannot tell what is meant"
                ),
                false=(
                    "Whatever the point rests on is identified here or plain from what is "
                    "said. Something mentioned in passing that the point does not depend "
                    "on is not a problem"
                ),
            ),
        ),
        "standalone": Noul(
            instructions=(
                "Would a viewer who has seen nothing else follow `clip.text` from beginning to end?"
            ),
            criteria=NoulCriteria(
                true=("What it is about and where it arrives are both inside the clip"),
                false="Following it needs something the viewer was never given",
            ),
        ),
        # --- scores: feed ranking, and a floor on payoff feeds the verdict ------------
        "hook": Score(
            instructions="How well does the opening of `clip.text` hold attention?",
            criteria=[
                "It is housekeeping, hesitation, or a thought already underway",
                "It states plainly what is about to be discussed",
                "It raises a question, makes a claim worth arguing with, or puts an image "
                "in front of the listener",
                "It is the kind of opening that stops someone who was about to look away",
            ],
        ),
        "payoff": Score(
            instructions="Does `clip.text` deliver what its opening sets up?",
            criteria=[
                "It raises something and never comes back to it",
                "It comes back to it partly, leaving the rest open",
                "What it was building to is stated outright before it ends",
            ],
        ),
    }
