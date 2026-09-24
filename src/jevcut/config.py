"""All tunables in one place.

Issue 014 sweeps most of these. Anything marked PLACEHOLDER is a guess that has not been
evaluated on our own data yet -- do not mistake it for a finding.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path

# Hard limits from https://docs.typesafe.ai/models.md for jev-1.13.
CONTEXT_TOTAL_TOKENS = 64_000
CONTEXT_STATE_PLUS_QUESTION_TOKENS = 32_000
MAX_CHOICE_OPTIONS = 255
PRICE_PER_INPUT_TOKEN = 0.042 / 1_000_000  # output tokens are free


@dataclass
class Config:
    # --- model ---
    # "openrouter" -> POST /api/alpha/decisions with typesafe/jev-1.13 (OPENROUTER_API_KEY)
    # "typesafe"   -> the first-party SDK (TYPESAFE_API_KEY)
    backend: str = "openrouter"
    # None takes the backend's default, which is a pinned version in both cases -- never
    # an alias, because an alias moves and a threshold tuned against one version is not
    # valid on the next. The `model` the response reports is logged per call.
    model_id: str | None = None
    timeout_s: float = 120.0

    # --- response cache (004) ---
    # `live` calls on a miss and stores; `replay` fails loudly on one; `refresh`
    # overwrites; `off` disables. Replay is what makes a config comparison mean
    # anything: the repair loop branches on thresholds, so ordinary answer variance
    # sends clips down different paths and two identical runs disagree.
    # Off by default: a library that silently writes a disk cache surprises its caller,
    # and in tests it is worse than surprising -- a stub's answer gets stored and served
    # to the next test that happens to ask the same thing, which looks like a logic bug
    # anywhere but here. The CLI opts in.
    cache_mode: str = "off"
    cache_dir: str = "runs/cache"
    max_retries: int = 5
    # Optional, OpenRouter leaderboards only.
    openrouter_referer: str | None = None
    openrouter_title: str | None = None

    # --- ingest (002) ---
    sentence_gap_s: float = 0.7  # silence that forces a sentence break
    max_sentence_words: int = 40  # longer than this gets split at its largest pause
    no_speech_threshold: float = 0.6  # drop ASR segments above this

    # --- cut points (003) ---
    pause_cut_s: float = 0.35  # silence that becomes a candidate cut
    merge_window_s: float = 0.2  # candidates closer than this collapse into one
    min_cut_spacing_s: float = 2.0  # thinning target: one candidate every 2-4s
    region_pad_s: float = 90.0  # anchor +/- this much is what `jevcut region` prints

    # --- scan (005) --- PLACEHOLDER until 014
    window_sentences: int = 80
    # Overlap is seam insurance for a moment straddling a boundary, and a moment's length
    # is measured in seconds -- so this must be too. Counted in sentences it shrinks on
    # fast speech, exactly where moments are densest. 60s matches the old 10-sentence
    # default at the documented 600-sentences-per-hour density.
    window_overlap_s: float = 60.0
    max_anchors_per_window: int = 3
    contains_moment_threshold: float = 0.6
    anchor_removal_s: float = 20.0  # neighbourhood dropped before re-asking a window
    # Cross-window dedupe radius. Separate from anchor_removal_s on purpose: one governs
    # "don't re-elect the same moment" inside a window, the other "these two windows found
    # the same moment". Sharing a knob means 014 cannot tune either without moving both.
    anchor_dedupe_s: float = 20.0
    min_tail_window: int = 20  # shorter trailing windows are merged into the previous one
    scan_concurrency: int = 8

    # --- gates (007/008) --- PLACEHOLDER until 014
    # Set from the observed distribution on one 48-minute talk, where a human rated
    # every surviving clip good. Not tuned to make clips appear: 0.5 was a guess, and
    # these questions answer "kind of" for every excerpt of continuous speech -- measured
    # medians 0.66 and 0.68 with a spread of ~0.12, so a 0.5 cut rejects nearly
    # everything. Still placeholders until 014 has a real labelled set; n=5, one video.
    mid_thought_threshold: float = 0.75
    dangling_ref_threshold: float = 0.75
    standalone_threshold: float = 0.4  # this one is positive: low means the viewer is lost
    # Two bars, not one. These questions answer "kind of" for every excerpt, so a
    # middling score is a good reason to try widening and a bad reason to throw the clip
    # away. Repair on the low bar, reject on the high one -- found when a looser reject
    # bar let a clip pass before the repair loop had improved its opening.
    repair_threshold: float = 0.5
    # A plain midpoint, deliberately not fitted to the four audience votes seen so far.
    # Measured on 96 clips from a solo talk and a panel: the two pure votes score 0.54 and
    # 0.67 and are caught; two votes that move on to a spoken lesson score 0.45-0.49 and
    # ship, which reads as right because their point reaches a later viewer; one of 92
    # other clips is flagged (0.52), a moderator question that ends before anyone
    # answers. Evidence is thin -- four positives, two videos.
    needs_room_threshold: float = 0.5
    #: Separated perfectly on the pilot set (17 of 17 ads above, 0 of 236 content texts;
    #: content peaked at 0.05, ads at a 0.95 median), so the bar is not delicate.
    promotion_threshold: float = 0.5
    payoff_floor: float = 0.5  # Score expectation; level 0 is "never returns to it"
    duration_band_s: tuple[float, float] = (25.0, 75.0)

    # --- live (016) --- PLACEHOLDER until 014
    live_buffer_s: float = 90.0
    live_tick_s: float = 4.0
    live_context_s: float = 60.0
    live_arm_threshold: float = 0.70
    live_release_threshold: float = 0.40
    live_release_ticks: int = 3
    live_cooldown_s: float = 20.0

    # --- budget (018) ---
    max_tokens_per_video: int = 2_000_000
    max_requests_per_video: int = 500

    weights: dict[str, float] = field(
        default_factory=lambda: {  # PLACEHOLDER until 014
            "hook": 1.0,
            "payoff": 1.0,
            "standalone": 0.8,
            "p_moment": 0.5,
            "anchor_confidence": 0.3,
        }
    )

    @property
    def model(self) -> str:
        from jevcut.backends import BACKEND_DEFAULT_MODEL

        return self.model_id or BACKEND_DEFAULT_MODEL[self.backend]

    def to_dict(self) -> dict:
        d = asdict(self)
        d["duration_band_s"] = list(self.duration_band_s)
        return d

    def to_json(self, path: str | Path) -> None:
        Path(path).write_text(json.dumps(self.to_dict(), indent=2))

    @classmethod
    def from_dict(cls, d: dict) -> Config:
        d = dict(d)
        if "duration_band_s" in d:
            d["duration_band_s"] = tuple(d["duration_band_s"])
        known = {f for f in cls.__dataclass_fields__}
        unknown = set(d) - known
        if unknown:
            raise ValueError(f"unknown config keys: {sorted(unknown)}")
        return cls(**d)

    @classmethod
    def from_json(cls, path: str | Path) -> Config:
        return cls.from_dict(json.loads(Path(path).read_text()))
