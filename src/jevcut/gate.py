"""Pass E -- does the clip we just cut actually work on its own?

The check no clipper we have read performs. autoclip asks its model for
self-containment as a *scoring criterion inside the prompt* and then never verifies the
clip it cut; the others do not ask at all (docs/PRIOR-ART.md). The three standing
complaints about commercial clippers -- starts mid-sentence, opens on a pronoun with no
referent, ends before the punchline -- are exactly what goes unchecked.

This is where Jev belongs now that code owns boundaries. A constant offset cannot tell
you a clip opens on "and that's why he did it": there is nothing to compute, it has to
be read. That is the opposite of the boundary problem, where arithmetic kept winning.

**Judgments here, policy at the edge.** `verify` returns what Jev said and nothing more,
so the numbers stay reusable when the policy changes (issue 008 owns policy properly;
`verdict` below is the interim one and every threshold in it is a placeholder until 014).
"""

from __future__ import annotations

from dataclasses import dataclass, field

from jevcut.client import JevClient
from jevcut.config import Config
from jevcut.questions import verify_questions


@dataclass(slots=True)
class Judgment:
    """What Jev said about one clip. No decisions in here."""

    nouls: dict[str, float] = field(default_factory=dict)
    #: Score expectation per question, plus its distribution -- a 1.0 can mean "all
    #: weight on level 1" or "split between 0 and 2", and only the spread tells them
    #: apart, so both are kept.
    scores: dict[str, float] = field(default_factory=dict)
    confidence: dict[str, float] = field(default_factory=dict)
    probabilities: dict[str, dict] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "nouls": self.nouls,
            "scores": self.scores,
            "confidence": self.confidence,
            "probabilities": self.probabilities,
        }


def verify(client: JevClient, text: str, config: Config | None = None) -> Judgment:
    """One request, six questions, over the clip text and nothing else."""
    config = config or Config()
    result = client.ask({"clip": {"text": text}}, verify_questions(), pass_name="verify")

    j = Judgment()
    for name, answer in result.answers.items():
        if answer.type == "noul":
            j.nouls[name] = answer.noul
        elif answer.type == "score":
            j.scores[name] = answer.score
        if answer.confidence is not None:
            j.confidence[name] = answer.confidence
        if answer.probabilities:
            j.probabilities[name] = answer.probabilities
    return j


#: What to do with a clip. Only `drop` is final.
SHIP, DROP, WIDEN_START, WIDEN_END, WIDEN_BOTH = (
    "ship",
    "drop",
    "widen_start",
    "widen_end",
    "widen_both",
)


@dataclass(slots=True)
class Verdict:
    action: str
    #: Why, in the order a human would fix them. Empty when shipping.
    reasons: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return self.action == SHIP

    @property
    def repairable(self) -> bool:
        return self.action in (WIDEN_START, WIDEN_END, WIDEN_BOTH)


def verdict(j: Judgment, config: Config | None = None) -> Verdict:
    """Interim policy. Thresholds are guesses until 014 tunes them on real data.

    **Worth is decided first, and separately.** No boundary move turns connective tissue
    into a clip, so a clip that is not worth having is dropped and never repaired. Only
    once it is worth having does how it is cut matter -- and then every craft failure is
    a repair instruction rather than a rejection, because all of them mean "something the
    viewer needs is outside the cut", which is a thing widening can fix.

    That ordering was the fix for a real failure: the first version ignored worth entirely
    in the verdict and dropped on craft, so a dull clip with tidy edges would ship while a
    strong moment with a ragged edge was thrown away.
    """
    config = config or Config()
    if j.nouls.get("worth_clipping", 1.0) < config.worth_threshold:
        return Verdict(DROP, ["not worth clipping"])
    # The lowest payoff level is "sets something up and never returns to it". That is the
    # end arriving too early, which widening forward can fix -- unlike a missing point.
    if j.scores.get("payoff", 2.0) < config.payoff_floor:
        return Verdict(WIDEN_END, ["payoff never lands"])

    before, after = [], []
    if j.nouls.get("starts_mid_thought", 0.0) >= config.mid_thought_threshold:
        before.append("starts mid-thought")
    if j.nouls.get("dangling_reference", 0.0) >= config.dangling_ref_threshold:
        before.append("dangling reference")
    if j.nouls.get("ends_mid_thought", 0.0) >= config.mid_thought_threshold:
        after.append("ends mid-thought")

    if not before and not after:
        # `standalone` is a summary judgment, so on its own it does not say which edge is
        # short. Reach in both directions and let the next round narrow it down.
        if j.nouls.get("standalone", 1.0) < config.standalone_threshold:
            return Verdict(WIDEN_BOTH, ["not standalone"])
        return Verdict(SHIP)

    if before and after:
        return Verdict(WIDEN_BOTH, before + after)
    return Verdict(WIDEN_START if before else WIDEN_END, before + after)
