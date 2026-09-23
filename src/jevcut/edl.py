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


#: How much each dimension counts toward the ranking. Placeholders until 014 tunes
#: them: hook leads because the opening decides whether anything else is seen. The
#: original third term, `worth_clipping`, was deleted -- it was flat across 38 clips and
#: was asking the model to aggregate these two, which is code's job. Its 0.2 was
#: redistributed in proportion, leaving the hook:payoff ratio unchanged.
RANK_WEIGHTS = {"hook": 0.625, "payoff": 0.375}
#: Score ranges, for normalising to 0-1 before weighting. A Score is an ordinal level,
#: so this is a ranking convenience and never a claim that the levels are evenly spaced.
SCORE_MAX = {"hook": 3.0, "payoff": 2.0}


def composite(scores: dict) -> float:
    """One number for ordering clips, from judgments made independently.

    Code owns the weights, following the composite-scoring pattern: the model scores
    each dimension on its own and never sees how they are combined, so reweighting
    costs nothing and invalidates no stored judgment.
    """
    return sum(
        weight * min(scores.get(name, 0.0) / SCORE_MAX[name], 1.0)
        for name, weight in RANK_WEIGHTS.items()
    )


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


#: The 9:16 output frame. 1080 wide is what the vertical platforms serve at full quality.
VERTICAL_SIZE = (1080, 1920)

#: The largest centred 9:16 box the frame holds: full height from a landscape source, full
#: width from one that is already narrower. Even sides, because yuv420p needs them.
#: Centred and nothing more -- following the speaker's face is its own job, not built yet.
#: Commas are escaped because the expression sits inside a filtergraph.
VERTICAL_CROP = r"crop=w=trunc(min(iw\,ih*9/16)/2)*2:h=trunc(min(ih\,iw*16/9)/2)*2"


def video_filter(*, vertical: bool = False) -> str | None:
    """The -vf chain for a render, or None when the frame goes through untouched."""
    steps: list[str] = []
    if vertical:
        width, height = VERTICAL_SIZE
        # setsar=1 so players show the 1080x1920 it is, whatever the source's pixel shape.
        steps += [VERTICAL_CROP, f"scale={width}:{height}", "setsar=1"]
    return ",".join(steps) or None


def render_command(
    source: str | Path,
    out: str | Path,
    *,
    render_t0: float,
    pre: float,
    duration: float,
    vf: str | None = None,
) -> list[str]:
    """The ffmpeg invocation for one clip. Separate from running it so it can be tested."""
    return [
        "ffmpeg",
        "-hide_banner",
        "-loglevel",
        "error",
        "-y",
        "-ss",
        f"{render_t0 - pre:.3f}",  # fast, keyframe-snapped
        "-i",
        str(source),
        "-ss",
        f"{pre:.3f}",  # accurate, from there
        "-t",
        f"{duration:.3f}",
        *(["-vf", vf] if vf else []),
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


def render_clip(source: str | Path, clip: Clip, out: str | Path, *, vertical: bool = False) -> Path:
    """Cut one clip with ffmpeg, accurately.

    Re-encodes: stream copy would snap the start to the nearest keyframe, which can be
    seconds away and would silently undo the boundary work. ``vertical`` centre-crops to
    9:16 at 1080x1920.
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

    cmd = render_command(
        source,
        out,
        render_t0=clip.render_t0,
        pre=pre,
        duration=duration,
        vf=video_filter(vertical=vertical),
    )
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


def probe_size(path: str | Path) -> tuple[int, int]:
    """Width and height of the first video stream."""
    result = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-select_streams",
            "v:0",
            "-show_entries",
            "stream=width,height",
            "-of",
            "csv=p=0:s=x",
            str(path),
        ],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(f"ffprobe failed: {result.stderr.strip()[:200]}")
    width, height = result.stdout.strip().split("x")
    return int(width), int(height)


def have_ffmpeg() -> bool:
    for tool in ("ffmpeg", "ffprobe"):
        try:
            subprocess.run([tool, "-version"], capture_output=True, check=True)
        except (OSError, subprocess.CalledProcessError):
            return False
    return True
