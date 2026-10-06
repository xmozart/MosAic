"""Clip detail words: reasons and quality grades (ADR 0043)."""

from __future__ import annotations

from mosaic.library.clip_view import _grade, reason_words


def test_reasons_read_as_words_once_each() -> None:
    reasons = [
        {"code": "too_dark", "status": "MAYBE", "source": "rule"},
        {"code": "too_dark", "status": "MAYBE", "source": "ai"},
        {"code": "brand_new_issue", "status": "MAYBE", "source": "ai"},
        "not a dict",
    ]
    assert reason_words(reasons) == ["Too dark", "Brand new issue"]


def test_grades_cover_the_scale() -> None:
    assert [_grade(x) for x in (None, 0.0, 0.3, 0.6, 0.84, 0.9, 1.0)] == [
        None,
        "Poor",
        "Fair",
        "Good",
        "Good",
        "Excellent",
        "Excellent",
    ]


def test_quality_words_from_realistic_metrics() -> None:
    from mosaic.library.clip_view import grades

    clip = {
        "sharpness": [(120.0, 0.7), (110.0, 0.6)],
        "shake": [(0.4, 0.9)],  # optical flow says shaky ...
        "shake_gyro": [(0.1, 0.2)],  # ... but the gyro, when present, is the measure
        "exposure_mean": [(110.0, None), (118.0, None)],  # 0–255
        "clip_low": [(0.01, None)],
        "clip_high": [(0.0, None)],
        "lufs_integrated": [(-24.0, None)],
        "wind": [(0.6, None)],
    }
    words = grades(clip, has_audio=True)
    assert words == {
        "sharpness": "Good",
        "steadiness": "Good",
        "exposure": "Excellent",
        "audio": "Good",
    }
    spoken = grades({**clip, "speech": [(1.0, None)]}, has_audio=True)
    assert spoken["audio"] == "Excellent", "voices are not wind"
    assert grades({}, has_audio=False) == dict.fromkeys(words, None)
