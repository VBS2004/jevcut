"""Turning transcripts into the exact text Jev sees.

Two forms:

* ``render_lines``   -> ``L042| text``           (Pass C state)
* ``render_markers`` -> ``L042| text «C07» ...`` (Pass D / retro-start state)

The line-ID form is the semantic-find cookbook pattern: give every line a handle so a
Choice can point at one. Markers do the same for boundaries.
"""

from __future__ import annotations

from jevcut.models import CutPoint, Sentence


def id_width(count: int) -> int:
    """Zero-pad width for sentence IDs. L000..L999 for normal videos, wider if needed.

    Width is fixed once for a whole transcript so IDs never get renumbered.
    """
    return max(3, len(str(max(count - 1, 0))))


def sentence_id(index: int, width: int = 3) -> str:
    return f"L{index:0{width}d}"


def cut_id(index: int) -> str:
    return f"C{index:02d}"


def render_lines(sentences: list[Sentence]) -> str:
    return "\n".join(f"{s.id}| {s.text}" for s in sentences)


def render_markers(sentences: list[Sentence], cuts: list[CutPoint]) -> str:
    """Render sentences with cut markers interleaved at their real time positions.

    A cut that falls inside a sentence (a mid-sentence pause) is placed between the
    words it actually falls between, not pushed to the sentence edge -- otherwise the
    option list claims a precision the text doesn't show.
    """
    pending = sorted(cuts, key=lambda c: c.t)
    out: list[str] = []
    i = 0

    for s in sentences:
        # Cuts strictly before this sentence starts.
        while i < len(pending) and pending[i].t < s.t0:
            out.append(f"«{pending[i].id}»")
            i += 1

        parts = [f"{s.id}|"]
        if s.words:
            for w in s.words:
                while i < len(pending) and pending[i].t <= w.t0:
                    parts.append(f"«{pending[i].id}»")
                    i += 1
                parts.append(w.text)
        else:
            parts.append(s.text)
        out.append(" ".join(parts))

    while i < len(pending):
        out.append(f"«{pending[i].id}»")
        i += 1

    return "\n".join(out)
