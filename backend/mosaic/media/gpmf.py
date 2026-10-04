"""GoPro GPMF telemetry (KLV) parser — gyro for the shake metric (MEDIA_SUPPORT.md §2).

GPMF is a nested Key-Length-Value format: an 8-byte header (4-char key, 1-char type,
1-byte struct size, 2-byte big-endian repeat count) followed by data padded to 4 bytes.
Type ``\\0`` means nested KLV. Only what shake needs is read: ``GYRO`` samples (3 axes),
their ``SCAL`` divisor and the ``STMP``/payload timing. Written in-house from the public
GPMF specification (https://github.com/gopro/gpmf-parser, Apache-2.0 documentation).
"""

from __future__ import annotations

import struct
from collections.abc import Iterator
from dataclasses import dataclass
from fractions import Fraction

_FORMATS = {
    "b": "b",
    "B": "B",
    "s": "h",
    "S": "H",
    "l": "i",
    "L": "I",
    "f": "f",
    "d": "d",
    "j": "q",
    "J": "Q",
}


@dataclass(frozen=True)
class KLV:
    key: str
    type: str
    size: int
    repeat: int
    data: bytes

    @property
    def nested(self) -> bool:
        return self.type == "\x00"

    def values(self) -> list[tuple[float, ...]]:
        """Decode numeric samples; each sample is a tuple of ``size // elem`` values."""
        fmt = _FORMATS.get(self.type)
        if fmt is None:
            return []
        elem = struct.calcsize(fmt)
        if self.size % elem:
            return []
        per = self.size // elem
        out = []
        for i in range(self.repeat):
            chunk = self.data[i * self.size : (i + 1) * self.size]
            if len(chunk) < self.size:
                break
            out.append(tuple(float(v) for v in struct.unpack(f">{per}{fmt}", chunk)))
        return out


def iter_klv(buf: bytes, offset: int = 0, end: int | None = None) -> Iterator[KLV]:
    end = len(buf) if end is None else end
    while offset + 8 <= end:
        key_b = buf[offset : offset + 4]
        if key_b == b"\x00\x00\x00\x00":
            break
        typ = chr(buf[offset + 4])
        size = buf[offset + 5]
        repeat = struct.unpack(">H", buf[offset + 6 : offset + 8])[0]
        length = size * repeat
        start = offset + 8
        stop = start + length
        if stop > end:
            break
        yield KLV(key_b.decode("latin-1"), typ, size, repeat, buf[start:stop])
        offset = start + ((length + 3) & ~3)


def walk(buf: bytes) -> Iterator[list[KLV]]:
    """Yield each innermost stream (``STRM``) as its list of KLV entries."""
    for item in iter_klv(buf):
        if item.key == "DEVC" and item.nested:
            for strm in iter_klv(item.data):
                if strm.key == "STRM" and strm.nested:
                    yield list(iter_klv(strm.data))


def gyro_samples(payload: bytes) -> list[tuple[float, float, float]]:
    """Gyro samples in rad/s from one GPMF payload (one per telemetry packet, ~1 s)."""
    out: list[tuple[float, float, float]] = []
    for entries in walk(payload):
        keys = {e.key: e for e in entries}
        gyro = keys.get("GYRO")
        if gyro is None:
            continue
        scal_entry = keys.get("SCAL")
        scal = scal_entry.values()[0][0] if scal_entry and scal_entry.values() else 1.0
        if scal == 0:
            continue  # corrupt scale: no usable data in this stream
        for sample in gyro.values():
            if len(sample) >= 3:
                out.append((sample[0] / scal, sample[1] / scal, sample[2] / scal))
    return out


def encode(key: str, typ: str, size: int, values: bytes, repeat: int) -> bytes:
    """Build one KLV entry (for tests and fixtures)."""
    head = key.encode("latin-1") + typ.encode("latin-1") + bytes([size]) + struct.pack(">H", repeat)
    pad = (-len(values)) % 4
    return head + values + b"\x00" * pad


def shake_per_second(
    samples: list[tuple[float, float, float]], duration: Fraction, smooth_s: float = 0.5
) -> list[float]:
    """Camera shake from gyro (rad/s): RMS of angular velocity after removing its smooth
    component (intentional pans), one value per whole second of ``seconds``.

    Samples are assumed evenly spaced over the file (GoPro writes a fixed gyro rate)."""
    import numpy as np

    if not samples or duration <= 0:
        return []
    seconds = float(duration)  # transient, inside this function only
    g = np.asarray(samples, dtype=np.float64)
    rate = len(g) / seconds
    k = max(1, round(rate * smooth_s))
    kernel = np.ones(k) / k
    smooth = np.stack([np.convolve(g[:, i], kernel, mode="same") for i in range(3)], axis=1)
    resid = np.linalg.norm(g - smooth, axis=1)
    out = []
    for s in range(int(seconds) + (1 if seconds % 1 else 0)):
        chunk = resid[int(s * rate) : int((s + 1) * rate)]
        if len(chunk):
            out.append(float(np.sqrt((chunk**2).mean())))
    return out
