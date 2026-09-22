"""The EDL, and turning it into files a human can watch.

The EDL is the handoff: one entry per clip, human-editable, and a re-render reads it
back without touching the API. That matters more than it sounds -- it is what makes a
human's correction visible as data rather than as an argument about prompt wording, and
it is how the eval in M2 gets clips to rate.

Two timestamps per edge, on purpose. `t0`/`t1` are the *measured* boundary and are what
the metrics score. `render_t0`/`render_t1` are nudged into the surrounding silence and
are what ffmpeg cuts. Folding the render nudge back into the measurement would flatter
every number in the eval.
"""

from __future__ import annotations

import json
import subprocess
from dataclasses import asdict, dataclass, field
from pathlib import Path

#: Fast-seek to this far before the clip, then seek the remainder accurately. Input
#: seeking alone lands on a keyframe, which for a system claiming boundary precision is
#: not acceptable; output seeking alone decodes the whole file from zero. This is both.
PRE_SEEK_S = 5.0


@dataclass(slots=True)
class Clip:
    id: str
    anchor_id: str
    kind: str
    t0: float
    t1: float
    render_t0: float
    render_t1: float
    start_cut: str
    end_cut: str
    text: str = ""
    scores: dict = field(default_factory=dict)
    rank: int = 0

    @property
    def duration(self) -> float:
        return self.t1 - self.t0

    def to_dict(self) -> dict:
        return asdict(self)


def write_edl(clips: list[Clip], path: str | Path, *, source: str = "") -> None:
    Path(path).write_text(
        json.dumps(
            {"source": source, "clips": [c.to_dict() for c in clips]},
            indent=2,
        )
    )


def read_edl(path: str | Path) -> tuple[str, list[Clip]]:
    """Read an EDL back, including one a human has edited by hand."""
    data = json.loads(Path(path).read_text())
    return data.get("source", ""), [Clip(**c) for c in data["clips"]]


def render_clip(source: str | Path, clip: Clip, out: str | Path) -> Path:
    """Cut one clip with ffmpeg, accurately.

    Re-encodes: stream copy would snap the start to the nearest keyframe, which can be
    seconds away and would silently undo the boundary work.
    """
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    pre = min(PRE_SEEK_S, clip.render_t0)

    # A clip on the last sentence has its tail nudged past the final word, and the media
    # can end first. ffmpeg would quietly return a short file, which reads downstream as
    # a boundary error rather than as running out of material. Clamp it here: this is the
    # only layer that knows how long the source actually is.
    end = min(clip.render_t1, probe_duration(source))
    duration = end - clip.render_t0
    if duration <= 0:
        raise ValueError(
            f"clip {clip.id} has no duration ({duration:.3f}s) -- "
            f"it may start at or past the end of {source}"
        )

    cmd = [
        "ffmpeg",
        "-hide_banner",
        "-loglevel",
        "error",
        "-y",
        "-ss",
        f"{clip.render_t0 - pre:.3f}",  # fast, keyframe-snapped
        "-i",
        str(source),
        "-ss",
        f"{pre:.3f}",  # accurate, from there
        "-t",
        f"{duration:.3f}",
        "-c:v",
        "libx264",
        "-preset",
        "veryfast",
        "-crf",
        "20",
        "-pix_fmt",
        "yuv420p",
        "-c:a",
        "aac",
        "-b:a",
        "160k",
        "-movflags",
        "+faststart",
        str(out),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"ffmpeg failed on {clip.id}: {result.stderr.strip()[:400]}")
    return out


def probe_duration(path: str | Path) -> float:
    """Measured duration of a rendered file, for checking the render against the EDL."""
    result = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=nw=1:nk=1",
            str(path),
        ],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(f"ffprobe failed: {result.stderr.strip()[:200]}")
    return float(result.stdout.strip())


def have_ffmpeg() -> bool:
    for tool in ("ffmpeg", "ffprobe"):
        try:
            subprocess.run([tool, "-version"], capture_output=True, check=True)
        except (OSError, subprocess.CalledProcessError):
            return False
    return True
