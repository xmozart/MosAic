"""Loudness and audio-quality statistics (ARCHITECTURE.md §8 stage 7), ITU-R BS.1770-4.

``LoudnessMeter`` consumes 48 kHz stereo float chunks with filter state carried across
chunks, so memory stays constant whatever the asset length (invariant 13). Positions are
sample indices or whole seconds; the caller converts them to ticks.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import numpy.typing as npt
from scipy import signal

F64 = npt.NDArray[np.float64]

RATE = 48_000
SUB = 4_800  # 100 ms sub-block; a 400 ms gating block is 4 consecutive sub-blocks
ABS_GATE = -70.0
CLIP = 0.989  # −0.1 dBFS

# BS.1770 K-weighting at 48 kHz: high-shelf pre-filter, then RLB high-pass.
_SHELF_B = np.array([1.53512485958697, -2.69169618940638, 1.19839281085285])
_SHELF_A = np.array([1.0, -1.69065929318241, 0.73248077421585])
_HP_B = np.array([1.0, -2.0, 1.0])
_HP_A = np.array([1.0, -1.99004745483398, 0.99007225036621])
_WIND_SOS = signal.butter(4, 150, btype="lowpass", fs=RATE, output="sos")


def lufs(mean_square: float) -> float:
    return -0.691 + 10.0 * float(np.log10(max(mean_square, 1e-12)))


@dataclass(frozen=True)
class AudioStats:
    integrated_lufs: float
    loudness_range: float  # LU, 10th–95th percentile of gated 400 ms loudness
    peak_dbfs: float  # sample peak
    clip_fraction: float  # fraction of samples at or above −0.1 dBFS
    per_second_lufs: list[float]  # 1 s momentary loudness, one value per whole second
    wind: list[float]  # per second: share of energy below 150 Hz (0..1)


@dataclass
class LoudnessMeter:
    """Streaming BS.1770 meter for 48 kHz stereo."""

    _zi_shelf: F64 = field(default_factory=lambda: np.zeros((2, 2)))
    _zi_hp: F64 = field(default_factory=lambda: np.zeros((2, 2)))
    _zi_wind: F64 = field(
        default_factory=lambda: np.zeros((_WIND_SOS.shape[0], 2))
    )  # sosfilt state
    _carry: F64 = field(default_factory=lambda: np.zeros((0, 2)))
    _sub_power: list[float] = field(default_factory=list)  # K-weighted, channel-summed
    _sub_energy: list[float] = field(default_factory=list)  # raw mono energy
    _sub_low: list[float] = field(default_factory=list)  # <150 Hz mono energy
    _peak: float = 0.0
    _clipped: int = 0
    _samples: int = 0

    def feed(self, stereo: F64) -> None:
        x = np.concatenate([self._carry, np.asarray(stereo, dtype=np.float64)])
        whole = len(x) // SUB * SUB
        self._carry = x[whole:]
        x = x[:whole]
        if not len(x):
            return
        self._samples += len(x)
        self._peak = max(self._peak, float(np.abs(x).max()))
        self._clipped += int((np.abs(x) >= CLIP).sum())
        y = np.empty_like(x)
        for ch in range(2):
            a, self._zi_shelf[:, ch] = signal.lfilter(
                _SHELF_B, _SHELF_A, x[:, ch], zi=self._zi_shelf[:, ch]
            )
            y[:, ch], self._zi_hp[:, ch] = signal.lfilter(_HP_B, _HP_A, a, zi=self._zi_hp[:, ch])
        mono = x.mean(axis=1)
        low, self._zi_wind = signal.sosfilt(_WIND_SOS, mono, zi=self._zi_wind)
        n = len(x) // SUB
        self._sub_power += list((y**2).sum(axis=1).reshape(n, SUB).mean(axis=1))
        self._sub_energy += list((mono**2).reshape(n, SUB).sum(axis=1))
        self._sub_low += list((low**2).reshape(n, SUB).sum(axis=1))

    def result(self) -> AudioStats:
        if len(self._carry):  # complete the final partial sub-block with silence
            self.feed(np.zeros((SUB - len(self._carry), 2)))
        subs = np.asarray(self._sub_power)
        blocks = (
            np.convolve(subs, np.ones(4) / 4, mode="valid")
            if len(subs) >= 4
            else np.asarray([subs.mean() if len(subs) else 0.0])
        )
        loud = np.array([lufs(p) for p in blocks])
        above = blocks[loud > ABS_GATE]
        if len(above):
            rel = lufs(float(above.mean())) - 10.0
            gated = blocks[(loud > ABS_GATE) & (loud > rel)]
            integrated = lufs(float(gated.mean())) if len(gated) else -70.0
        else:
            integrated = -70.0
        st = loud[loud > ABS_GATE]
        lra = float(np.percentile(st, 95) - np.percentile(st, 10)) if len(st) > 1 else 0.0
        per_second, wind = [], []
        for s0 in range(0, len(subs), 10):
            per_second.append(lufs(float(subs[s0 : s0 + 10].mean())))
            energy = sum(self._sub_energy[s0 : s0 + 10])
            low = sum(self._sub_low[s0 : s0 + 10])
            wind.append(low / energy if energy > 1e-9 else 0.0)
        total = max(self._samples * 2, 1)
        return AudioStats(
            integrated_lufs=integrated,
            loudness_range=lra,
            peak_dbfs=20.0 * float(np.log10(max(self._peak, 1e-9))),
            clip_fraction=self._clipped / total,
            per_second_lufs=per_second,
            wind=wind,
        )


def analyze(stereo: F64) -> AudioStats:
    meter = LoudnessMeter()
    x = np.asarray(stereo, dtype=np.float64)
    if x.ndim == 1:
        x = np.stack([x, x], axis=1)
    meter.feed(x)
    return meter.result()
