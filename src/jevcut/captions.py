"""Burned-in captions, from the word timings the transcript already has.

A caption line is a few words, shown from when its first word is spoken, and the word
being said is highlighted as it goes. All of it is arithmetic on ``Word.t0``/``t1``: no
model is involved, and nothing here re-times or re-words what ASR produced.

Output is an ASS subtitle file for ffmpeg's ``ass`` filter (libass). ASS rather than SRT
because it carries the styling -- size, outline, position -- and per-word colour, and
those have to follow the frame: a line that fits 16:9 runs off the edge of a 9:16 crop.
"""

from __future__ import annotations

from dataclasses import dataclass

from jevcut.models import Transcript, Word

#: A pause this long ends a line, so a caption does not sit on screen through silence
#: waiting for words that belong to the next thought.
MAX_GAP_S = 0.6
#: How long a line stays up after its last word, unless the next line starts sooner.
#: Snapping it away on the last syllable is hard to read.
HOLD_S = 0.5
#: A word ending in one of these ends its line: a caption that straddles two sentences
#: reads as one run-on thought.
SENTENCE_END = (".", "?", "!")

WHITE = "&H00FFFFFF"  # ASS colours are &HAABBGGRR, alpha 00 = opaque
BLACK = "&H00000000"
HIGHLIGHT = "&H00FFFF&"  # yellow, in the inline \c form (&HBBGGRR&)

#: U+2060 WORD JOINER: zero-width, and it breaks up "\N", "\h" and "\{" so a backslash
#: in a transcript word cannot turn into a line break or an override.
WORD_JOINER = "\u2060"


@dataclass(frozen=True, slots=True)
class Layout:
    """Caption geometry for one frame size, in that frame's pixels."""

    width: int
    height: int
    font_size: int
    margin_v: int
    margin_h: int
    max_words: int
    max_chars: int


def layout_for(width: int, height: int) -> Layout:
    """Size and place captions for the frame they are burned into.

    Font size follows the frame height, so a 360p preview and a 1080p render look the
    same. The limits per line follow its width: at these sizes a bold sans glyph averages
    a little over half its font size, so the character caps below keep a line inside the
    side margins, and libass wraps if an unusually wide word still overflows.
    """
    if height > width:
        # Vertical: big and few, three words, which is what vertical viewers read at a
        # glance. Lifted to three quarters of the way down, clear of the caption,
        # buttons and progress bar the platforms overlay on the bottom fifth.
        return Layout(
            width=width,
            height=height,
            font_size=round(height * 0.042),
            margin_v=round(height * 0.25),
            margin_h=round(width * 0.06),
            max_words=3,
            max_chars=18,
        )
    # Landscape: a conventional subtitle line near the bottom, up to six words.
    return Layout(
        width=width,
        height=height,
        font_size=round(height * 0.06),
        margin_v=round(height * 0.07),
        margin_h=round(width * 0.05),
        max_words=6,
        max_chars=36,
    )


def clip_words(transcript: Transcript, t0: float, t1: float) -> list[Word]:
    """The words spoken inside [t0, t1), re-based so ``t0`` is zero.

    A word belongs to the clip when its midpoint does: one the cut slices through at the
    edge is mostly outside and would caption a sound nobody hears. Edges are clamped to
    the span, so no caption starts before the clip or runs past it.
    """
    words: list[Word] = []
    for sentence in transcript.between(t0, t1):
        for w in sentence.words:
            text = " ".join(w.text.split())  # ASR leaves leading spaces and stray newlines
            if not text or not t0 <= (w.t0 + w.t1) / 2 < t1:
                continue
            words.append(
                Word(
                    text=text,
                    t0=max(w.t0, t0) - t0,
                    t1=min(w.t1, t1) - t0,
                    speaker=w.speaker,
                )
            )
    return words


def group_lines(words: list[Word], layout: Layout) -> list[list[Word]]:
    """Split words into caption lines: a few at a time, never across a sentence end, a
    long pause or a change of speaker."""
    lines: list[list[Word]] = []
    line: list[Word] = []
    for w in words:
        if line:
            prev = line[-1]
            too_long = len(" ".join(x.text for x in [*line, w])) > layout.max_chars
            if (
                len(line) >= layout.max_words
                or too_long
                or w.t0 - prev.t1 > MAX_GAP_S
                or prev.text.endswith(SENTENCE_END)
                or w.speaker != prev.speaker
            ):
                lines.append(line)
                line = []
        line.append(w)
    if line:
        lines.append(line)
    return lines


def escape_text(text: str) -> str:
    """Make a word safe as ASS dialogue text.

    ``{...}`` is an override block and would swallow the word, so braces are escaped
    (libass renders ``\\{`` as a literal brace). A backslash cannot be escaped in ASS --
    ``\\\\`` renders as two -- so a zero-width word joiner goes after it instead, which
    stops it combining with the next character. Backslashes first, so the ones added for
    the braces are not themselves broken up.
    """
    text = text.replace("\\", "\\" + WORD_JOINER)
    return text.replace("{", "\\{").replace("}", "\\}")


def _timestamp(t: float) -> str:
    cs = max(0, round(t * 100))
    return f"{cs // 360000}:{cs // 6000 % 60:02d}:{cs // 100 % 60:02d}.{cs % 100:02d}"


def to_ass(words: list[Word], width: int, height: int, *, shift: float = 0.0) -> str:
    """An ASS file captioning ``words`` (already re-based to the clip) on a frame of
    ``width`` x ``height``.

    Each line is written once per word, with that word highlighted, so the highlight
    moves as it is spoken. The events are back to back, so the line does not flicker.

    ``shift`` moves every event later. The render needs it: ffmpeg's filters run before
    the accurate output seek discards its lead-in, so they see the clip start at
    ``pre`` seconds, not at zero.
    """
    layout = layout_for(width, height)
    outline = max(1, round(layout.font_size * 0.08))
    header = [
        "[Script Info]",
        "ScriptType: v4.00+",
        f"PlayResX: {width}",
        f"PlayResY: {height}",
        "WrapStyle: 0",
        "ScaledBorderAndShadow: yes",
        "",
        "[V4+ Styles]",
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, "
        "BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, "
        "BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding",
        # Bold white with a heavy black outline: legible over any footage without the
        # box a background would draw. Alignment 2 is bottom centre.
        f"Style: Default,Arial,{layout.font_size},{WHITE},{WHITE},{BLACK},{BLACK},"
        f"-1,0,0,0,100,100,0,0,1,{outline},0,2,"
        f"{layout.margin_h},{layout.margin_h},{layout.margin_v},1",
        "",
        "[Events]",
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
    ]

    events: list[str] = []
    lines = group_lines(words, layout)
    for i, line in enumerate(lines):
        start = line[0].t0
        end = line[-1].t1 + HOLD_S
        if i + 1 < len(lines):
            end = min(end, lines[i + 1][0].t0)
        texts = [escape_text(w.text) for w in line]
        for j in range(len(line)):
            w_start = start if j == 0 else line[j].t0
            w_end = line[j + 1].t0 if j + 1 < len(line) else end
            if w_end <= w_start:
                continue  # overlapping ASR timings; the next word's event covers it
            text = " ".join(
                f"{{\\c{HIGHLIGHT}}}{t}{{\\r}}" if k == j else t for k, t in enumerate(texts)
            )
            events.append(
                f"Dialogue: 0,{_timestamp(w_start + shift)},{_timestamp(w_end + shift)},"
                f"Default,,0,0,0,,{text}"
            )
    return "\n".join([*header, *events]) + "\n"


def escape_filter_path(path: str) -> str:
    """Escape a path for use as a filter option inside an ffmpeg filtergraph.

    Two levels, innermost first: the option value, where ``\\ ' :`` are special, then
    the graph description, where ``\\ ' [ ] , ;`` are. A temp dir or output dir with a
    colon or a comma in it would otherwise split the filter apart.
    """
    for special in ("\\':", "\\'[],;"):
        path = "".join("\\" + c if c in special else c for c in path)
    return path
