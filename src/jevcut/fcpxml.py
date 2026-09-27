"""The EDL as a timeline an editor can open.

`edl.json` is jevcut's own format: the renderer reads it back, and a human can edit it,
but no NLE knows what it is. The mp4s are finished goods -- fine to post, useless to
adjust. Between "a number in a JSON file" and "a rendered file" there was nothing an
editor could actually work with, which is the gap this closes: one FCPXML, importable by
Premiere, Resolve and Final Cut, with every clip laid out and trimmable.

It points at the *source* video, not at the rendered mp4s, so a clip keeps its handles:
an editor who wants two more seconds at the head drags for them instead of asking for a
re-render. One project (sequence) per clip, because each clip ships as its own Short --
a single timeline with all of them in a row would be one thing to cut apart again.

The times written are `render_t0`/`render_t1`, the ones ffmpeg cuts, so the timeline and
the mp4s agree. The measured boundary (`t0`/`t1`) rides along as a marker on each clip,
since that is the judgment being handed over and an editor moving a cut should be able
to see what the model actually chose.

Frames, not seconds, are the unit: FCPXML times are rationals on the format's frame grid,
and a time that does not land on it is a file some importers reject and others silently
round. Everything here converts through `Fraction` for that reason -- see `_timecode`.
"""

from __future__ import annotations

import subprocess
import xml.etree.ElementTree as ET
from fractions import Fraction
from pathlib import Path
from xml.dom import minidom

from jevcut.edl import Clip

#: FCPXML version to declare. 1.9 is old enough that Premiere, Resolve and Final Cut all
#: read it, and new enough to carry everything used here. Newer versions add features
#: this exporter does not use, and each one narrows the set of apps that will open it.
FCPXML_VERSION = "1.9"

#: Fall back to this when ffprobe cannot name a frame rate (an audio-only or malformed
#: input). 25 is a safe grid: whole-number, and every importer handles it.
DEFAULT_FPS = Fraction(25)

#: Clip names are truncated to this. Premiere shows the sequence name in a narrow column,
#: and the full sentence belongs in the marker, which is not truncated.
NAME_CHARS = 48


def _timecode(seconds: float, frame_duration: Fraction) -> str:
    """A time in seconds as an FCPXML rational, snapped to the frame grid.

    FCPXML wants "N/Ds" (or "Ns" when D is 1) and expects times to be whole multiples of
    the format's frameDuration. Passing a decimal like 12.5s through instead is what
    makes an importer either reject the file or round it somewhere you did not choose.
    """
    frames = round(Fraction(seconds).limit_denominator(1_000_000) / frame_duration)
    total = frames * frame_duration
    if total.denominator == 1:
        return f"{total.numerator}s"
    return f"{total.numerator}/{total.denominator}s"


def clip_name(clip: Clip) -> str:
    """A name an editor can scan in a bin: rank first, then the clip's own words."""
    text = " ".join(clip.text.split())
    if len(text) > NAME_CHARS:
        text = text[: NAME_CHARS - 1].rstrip() + "\u2026"
    return f"{clip.rank:02d} {text}" if text else f"{clip.rank:02d} {clip.id}"


def to_fcpxml(
    clips: list[Clip],
    source: str | Path,
    *,
    fps: Fraction,
    size: tuple[int, int],
    duration: float,
    has_audio: bool = True,
) -> str:
    """Build the FCPXML document. Pure: every fact about the media is passed in.

    `duration` is the source's, not a clip's -- an asset shorter than the clips that
    reference it is the one structural error an importer cannot recover from.
    """
    frame_duration = 1 / fps
    width, height = size
    source_path = Path(source).resolve()

    fcpxml = ET.Element("fcpxml", version=FCPXML_VERSION)
    resources = ET.SubElement(fcpxml, "resources")
    ET.SubElement(
        resources,
        "format",
        id="r1",
        frameDuration=_timecode(float(frame_duration), frame_duration),
        width=str(width),
        height=str(height),
        colorSpace="1-1-1 (Rec. 709)",
    )
    asset = ET.SubElement(
        resources,
        "asset",
        id="r2",
        name=source_path.stem,
        start="0s",
        duration=_timecode(duration, frame_duration),
        format="r1",
        hasVideo="1",
        videoSources="1",
        **({"hasAudio": "1", "audioSources": "1", "audioChannels": "2"} if has_audio else {}),
    )
    # as_uri() percent-encodes and gets the Windows drive-letter form right
    # (file:///C:/...), which a hand-built "file://" + path does not.
    ET.SubElement(asset, "media-rep", kind="original-media", src=source_path.as_uri())

    library = ET.SubElement(fcpxml, "library")
    event = ET.SubElement(library, "event", name=f"jevcut — {source_path.stem}")
    for clip in clips:
        _append_project(event, clip, frame_duration=frame_duration, duration=duration)

    body = ET.tostring(fcpxml, encoding="unicode")
    pretty = minidom.parseString(body).documentElement.toprettyxml(indent="    ")
    return f'<?xml version="1.0" encoding="UTF-8"?>\n<!DOCTYPE fcpxml>\n{pretty}'


def _append_project(
    event: ET.Element, clip: Clip, *, frame_duration: Fraction, duration: float
) -> None:
    """One project per clip: a sequence holding that clip's span of the source."""
    # Clamp to the asset: a clip whose tail was nudged past the final word can otherwise
    # claim media that does not exist, which importers read as a corrupt file.
    start = max(0.0, min(clip.render_t0, duration))
    end = max(start, min(clip.render_t1, duration))
    span = _timecode(end - start, frame_duration)

    project = ET.SubElement(event, "project", name=clip_name(clip))
    sequence = ET.SubElement(
        project,
        "sequence",
        format="r1",
        duration=span,
        tcStart="0s",
        tcFormat="NDF",
        audioLayout="stereo",
        audioRate="48k",
    )
    spine = ET.SubElement(sequence, "spine")
    asset_clip = ET.SubElement(
        spine,
        "asset-clip",
        ref="r2",
        name=clip_name(clip),
        offset="0s",
        start=_timecode(start, frame_duration),
        duration=span,
        format="r1",
        tcFormat="NDF",
    )
    if clip.text.strip():
        ET.SubElement(asset_clip, "note").text = " ".join(clip.text.split())
    # The measured boundary, as a marker at its offset inside the clip. Placed only when
    # it differs from the render edge; a marker at 0s on every clip is noise.
    measured = max(start, min(clip.t0, end))
    if abs(measured - start) >= float(frame_duration):
        ET.SubElement(
            asset_clip,
            "marker",
            start=_timecode(measured - start, frame_duration),
            duration=_timecode(float(frame_duration), frame_duration),
            value=f"measured start ({clip.start_cut})",
        )


def probe_frame_rate(path: str | Path) -> Fraction:
    """The source's frame rate, as the exact rational ffprobe reports.

    Kept exact on purpose: 30000/1001 is not 29.97, and rounding it here is what puts
    every later timecode a frame further out of step the longer the video runs.
    """
    result = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-select_streams",
            "v:0",
            "-show_entries",
            "stream=r_frame_rate",
            "-of",
            "default=nw=1:nk=1",
            str(path),
        ],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(f"ffprobe failed: {result.stderr.strip()[:200]}")
    rate = result.stdout.strip()
    try:
        fps = Fraction(rate)
    except (ValueError, ZeroDivisionError):
        return DEFAULT_FPS
    return fps if fps > 0 else DEFAULT_FPS


def has_audio_stream(path: str | Path) -> bool:
    """Whether the source carries audio, so the asset does not promise a stream it lacks."""
    result = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "a:0", "-show_entries",
         "stream=index", "-of", "default=nw=1:nk=1", str(path)],
        capture_output=True,
        text=True,
    )
    return result.returncode == 0 and bool(result.stdout.strip())


def write_fcpxml(clips: list[Clip], path: str | Path, *, source: str | Path) -> Path:
    """Probe the source, build the document, write it. Returns the path written."""
    from jevcut.edl import probe_duration, probe_size

    document = to_fcpxml(
        clips,
        source,
        fps=probe_frame_rate(source),
        size=probe_size(source),
        duration=probe_duration(source),
        has_audio=has_audio_stream(source),
    )
    out = Path(path)
    out.write_text(document, encoding="utf-8")
    return out
