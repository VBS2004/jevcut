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


@dataclass(slots=True)
class Verdict:
    ok: bool
    #: Why it failed, in the order a human would fix them. Empty when `ok`.
    reasons: list[str] = field(default_factory=list)
    #: True when the failures are all "something before this is missing", which widening
    #: the start can actually fix. A clip that ends mid-thought or has no payoff cannot
    #: be rescued by more setup.
    widenable: bool = False


def verdict(j: Judgment, config: Config | None = None) -> Verdict:
    """Interim policy. Thresholds are guesses until 014 tunes them on real data.

    Deliberately strict: a missed clip costs nothing and a bad one costs credibility,
    which is the under-clip philosophy taken from jev-skip (docs/PRIOR-ART.md).
    """
    config = config or Config()
    reasons = []
    if j.nouls.get("starts_mid_thought", 0.0) >= config.mid_thought_threshold:
        reasons.append("starts mid-thought")
    if j.nouls.get("dangling_reference", 0.0) >= config.dangling_ref_threshold:
        reasons.append("dangling reference")
    if j.nouls.get("ends_mid_thought", 0.0) >= config.mid_thought_threshold:
        reasons.append("ends mid-thought")
    if j.nouls.get("standalone", 1.0) < 0.5:
        reasons.append("not standalone")

    fixable = {"starts mid-thought", "dangling reference", "not standalone"}
    return Verdict(
        ok=not reasons,
        reasons=reasons,
        widenable=bool(reasons) and set(reasons) <= fixable,
    )
