from __future__ import annotations

import sys
from fractions import Fraction

import numpy as np
import pytest

from mosaic.audio import loudness
from mosaic.audio.analysis import float_to_ticks, to_ticks


def _sine(db: float, seconds: float = 5, freq: float = 997) -> np.ndarray:
    t = np.arange(int(48000 * seconds)) / 48000
    a = 10 ** (db / 20) * np.sin(2 * np.pi * freq * t)
    return np.stack([a, a], axis=1)


def test_reference_sine_reads_its_level() -> None:
    stats = loudness.analyze(_sine(-20))
    assert stats.integrated_lufs == pytest.approx(-20.0, abs=0.05)
    assert stats.peak_dbfs == pytest.approx(-20.0, abs=0.01)
    assert stats.per_second_lufs[0] == pytest.approx(-20.0, abs=0.01)
    assert stats.clip_fraction == 0


def test_streaming_matches_one_shot() -> None:
    x = np.concatenate([_sine(-30, 2), _sine(-12, 3)])
    one = loudness.analyze(x)
    meter = loudness.LoudnessMeter()
    for i in range(0, len(x), 7_777):
        meter.feed(x[i : i + 7_777])
    two = meter.result()
    assert two.integrated_lufs == pytest.approx(one.integrated_lufs, abs=1e-6)
    assert two.per_second_lufs == pytest.approx(one.per_second_lufs, abs=1e-6)
    assert two.loudness_range > 10  # 18 dB step between the halves


def test_gating_ignores_silence_and_flags_clipping() -> None:
    x = np.concatenate([np.zeros((48000 * 5, 2)), _sine(-20, 5)])
    # Silence is gated out; the few 400 ms blocks straddling the edge pass both gates at
    # about -26 LUFS and lower the mean slightly, as BS.1770 specifies.
    assert loudness.analyze(x).integrated_lufs == pytest.approx(-20.0, abs=0.2)
    clipped = np.clip(_sine(3, 1), -1, 1)
    assert loudness.analyze(clipped).clip_fraction > 0.1


def test_wind_share() -> None:
    rumble = _sine(-20, 2, freq=60)
    voice = _sine(-20, 2, freq=1000)
    assert loudness.analyze(rumble).wind[0] > 0.9
    assert loudness.analyze(voice).wind[0] < 0.05


def test_float_seconds_become_integer_ticks_at_the_boundary() -> None:
    tb = Fraction(1, 90000)
    assert float_to_ticks(Fraction(600), 1.25, tb) == 601 * 90000 + 22500
    assert isinstance(float_to_ticks(Fraction(0), 0.1, tb), int)
    assert to_ticks(Fraction(1, 3), Fraction(1, 30000)) == 10000


def test_av_shim_lets_faster_whisper_import_without_pyav() -> None:
    from mosaic.ai.adapters.faster_whisper import av_shim

    av_shim.install()
    import faster_whisper

    assert faster_whisper.WhisperModel
    with pytest.raises(RuntimeError, match="ADR 0009"):
        sys.modules["av"].open  # noqa: B018
