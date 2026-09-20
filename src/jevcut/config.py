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
    region_pad_s: float = 90.0  # anchor +/- this much becomes a Pass D region

    # --- scan (005) --- PLACEHOLDER until 014
    window_sentences: int = 80
    window_overlap: int = 10
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
    mid_thought_threshold: float = 0.5
    dangling_ref_threshold: float = 0.5
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
