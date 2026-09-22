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
    """Pass E. One request per candidate clip, six questions over the clip text alone.

    **The state is the cut text and nothing else** -- no title, no surrounding transcript.
    Given the context, the model resolves the dangling pronoun from it and calls the clip
    fine; the viewer cannot. Putting the model exactly where the viewer sits is the whole
    mechanism, and it is the one thing to not "improve" by adding helpful context.

    This is where Jev earns its place now that code owns boundaries: no offset, snap or
    silence detector can tell you a clip opens on a pronoun with no referent. There is
    nothing to compute -- it has to be read.

    Four Nouls and two Scores, because the first four name a defect code can act on and
    the last two feed ranking. Each Noul is absolute, so all four can be low at once.
    """
    return {
        "starts_mid_thought": Noul(
            instructions=(
                "Does the first sentence of `clip.text` begin in the middle of a thought -- "
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
