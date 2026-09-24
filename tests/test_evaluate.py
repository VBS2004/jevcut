"""Scoring against labels (012): matching, the boundary ranges, negatives, and chance."""

from __future__ import annotations

import json

import pytest

from jevcut.edl import Clip, write_edl
from jevcut.evaluate import (
    agreement,
    chance_recall,
    edl_for,
    iou,
    match,
    score_set,
    score_video,
    summary,
)


def _clip(t0: float, t1: float, n: int = 1) -> Clip:
    return Clip(
        id=f"clip{n:03d}",
        anchor_id="L000",
        kind="story",
        t0=t0,
        t1=t1,
        render_t0=t0 - 0.2,
        render_t1=t1 + 0.2,
        start_cut="C00",
        end_cut="C01",
    )


def _label(**video) -> dict:
    return {
        "video": {"url": "u?v=abc", "genre": "talk", "duration_s": 600.0, **video},
        "clips": [
            {
                "id": "a",
                "start": 100,
                "start_range": [98, 104],
                "end": 150,
                "end_range": [148, 155],
            },
            {
                "id": "b",
                "start": 300,
                "start_range": [300, 301],
                "end": 340,
                "end_range": [339, 345],
            },
        ],
        "negatives": [{"start": 400, "end": 500, "why": "screen demo"}],
    }


def test_iou():
    assert iou((0, 10), (0, 10)) == 1.0
    assert iou((0, 10), (5, 15)) == pytest.approx(5 / 15)
    assert iou((0, 10), (20, 30)) == 0.0


def test_matching_is_one_to_one_and_needs_more_than_half():
    labeled = [(100, 150)]
    # Two predictions over the same label: only the better one counts.
    assert match([(101, 151), (100, 150)], labeled) == [(1, 0)]
    # Exactly half an overlap is not a match.
    assert match([(100, 125)], [(100, 150)]) == []


def test_a_video_scores_hits_misses_ranges_and_negatives(tmp_path):
    edl = tmp_path / "edl.json"
    # A hit inside both ranges, a hit with the start out of range, one clip on the negative.
    write_edl([_clip(101, 151, 1), _clip(295, 340, 2), _clip(410, 470, 3)], edl)
    s = score_video(_label(), edl)
    assert (s.predicted, s.labeled, s.matched) == (3, 2, 2)
    assert s.in_range == 1
    assert s.on_negative == 1
    assert s.start_errors == [1, 5]
    assert s.missed == []


def test_an_also_ok_pick_is_not_a_false_positive_nor_a_hit(tmp_path):
    label = _label()
    label["also_ok"] = [
        {"id": "c", "start": 200, "start_range": [200, 200], "end": 260, "end_range": [260, 260]}
    ]
    edl = tmp_path / "edl.json"
    write_edl([_clip(101, 151, 1), _clip(202, 258, 2)], edl)
    s = score_video(label, edl)
    assert (s.matched, s.acceptable) == (1, 1)
    assert s.precision == 1.0
    assert s.recall == 0.5  # recall counts required clips only


def test_a_miss_is_named(tmp_path):
    edl = tmp_path / "edl.json"
    write_edl([_clip(101, 151)], edl)
    assert score_video(_label(), edl).missed == ["b"]


def test_chance_is_low_for_sparse_clips_and_seeded():
    labeled = [(100, 150), (300, 340)]
    a = chance_recall([50.0, 50.0], labeled, 3600.0)
    assert 0.0 <= a < 0.1
    assert a == chance_recall([50.0, 50.0], labeled, 3600.0)


def test_pooled_summary_weights_by_clip_not_by_video(tmp_path):
    edl = tmp_path / "edl.json"
    write_edl([_clip(101, 151)], edl)
    one = score_video(_label(), edl)  # 1 of 2 found
    empty = tmp_path / "empty.json"
    write_edl([], empty)
    none = score_video(_label(), empty)  # 0 of 2 found
    assert summary([one, none])["recall"] == 0.25


def test_the_set_finds_runs_by_media_name_and_skips_missing(tmp_path):
    media = tmp_path / "talk.mp4"
    labels = tmp_path / "labels"
    labels.mkdir()
    (labels / "abc.json").write_text(json.dumps(_label(local_path=str(media))))
    (labels / "xyz.json").write_text(json.dumps(_label(local_path=str(tmp_path / "gone.mp4"))))
    run = edl_for(_label(local_path=str(media)))
    assert run == tmp_path / "talk-clips" / "edl.json"
    run.parent.mkdir()
    write_edl([_clip(101, 151)], run)

    scores, skipped = score_set(labels)
    assert len(scores) == 1 and scores[0].matched == 1
    assert len(skipped) == 1 and "xyz.json" in skipped[0]


def test_two_labelers_agreement_is_the_noise_floor():
    a = _label()
    b = _label()
    b["clips"] = [
        {"id": "x", "start": 103, "start_range": [103, 103], "end": 150, "end_range": [150, 150]},
        {"id": "y", "start": 500, "start_range": [500, 500], "end": 540, "end_range": [540, 540]},
        {"id": "z", "start": 700, "start_range": [700, 700], "end": 740, "end_range": [740, 740]},
    ]
    r = agreement(a, b)
    assert (r["a"], r["b"], r["matched"]) == (2, 3, 1)
    assert r["agree_a"] == 0.5
    assert r["start_deltas"] == [3] and r["end_deltas"] == [0]


def test_summary_reports_how_long_the_clips_run(tmp_path):
    # "Short" is in the spec, so length is reported beside where the edges land.
    edl = tmp_path / "edl.json"
    write_edl([_clip(100, 130, 1), _clip(300, 350, 2), _clip(500, 520, 3)], edl)
    s = summary([score_video(_label(), edl)])
    assert s["duration_median"] == 30.0
    assert s["label_duration_median"] == 45.0
