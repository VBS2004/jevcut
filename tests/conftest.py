"""Synthetic word streams, so the M0 layers are testable with no ASR and no API key."""

from __future__ import annotations

import pytest

from jevcut.models import Word


def make_words(spec: list[tuple[str, float, float]], speaker: str | None = None) -> list[Word]:
    return [Word(text=t, t0=a, t1=b, speaker=speaker) for t, a, b in spec]


def speech(
    text: str,
    start: float = 0.0,
    *,
    word_s: float = 0.4,
    gap_s: float = 0.05,
    speaker: str | None = None,
) -> list[Word]:
    """Evenly-paced words. Punctuation in `text` drives sentence breaks."""
    words, t = [], start
    for token in text.split():
        words.append(Word(text=token, t0=round(t, 3), t1=round(t + word_s, 3), speaker=speaker))
        t += word_s + gap_s
    return words


@pytest.fixture
def two_sentences() -> list[Word]:
    return speech("The reactor went offline. Nobody noticed for six hours.")


@pytest.fixture
def long_talk() -> list[Word]:
    """~3 minutes with a speaker change and a long silence in the middle."""
    a = speech("We tried the obvious fix first and it did not work at all.", 0.0, speaker="A")
    b = speech("So what did you do next then?", 30.0, speaker="B")
    c = speech(
        "We rewrote the scheduler. That took three weeks. It was worth it.", 45.0, speaker="A"
    )
    return a + b + c
