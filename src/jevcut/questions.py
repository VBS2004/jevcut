"""Question builders, one function per pass.

These are the specs in docs/QUESTIONS.md, in code. Keep the two in sync: the wording is
the thing being tuned, and issue 014 A/B-tests these exact strings.
"""

from __future__ import annotations

from typesafe_sdk import Choice, Noul, NoulCriteria

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
