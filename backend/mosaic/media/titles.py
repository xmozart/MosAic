"""Title cards (ADR 0079): one modern style, drawn with Pillow in the bundled Geist.

A card is a still image at the output's size: a near-black ground, a title in Geist
SemiBold and an optional subtitle in Geist Regular, centred. The fonts are the Geist
subsets the UI bundles (SIL OFL 1.1, ``fonts/OFL.txt``), never fetched (invariant 15).
Each character is drawn with the subset that covers it; text any subset lacks (Hebrew,
Arabic, CJK...) cannot be drawn, so ``covered`` tells the caller to leave that line out.
"""

from __future__ import annotations

import hashlib
from functools import cache
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

FONTS = Path(__file__).parent / "fonts"
TITLE_STYLE = "title/1"  # the look below; part of every card's chunk key

# Unicode ranges of each bundled subset (fontsource's unicode.json for Geist 5.3.0).
SUBSETS: dict[str, str] = {
    "latin": "U+0000-00FF,U+0131,U+0152-0153,U+02BB-02BC,U+02C6,U+02DA,U+02DC,U+0304,"
    "U+0308,U+0329,U+2000-206F,U+20AC,U+2122,U+2191,U+2193,U+2212,U+2215,U+FEFF,U+FFFD",
    "latin-ext": "U+0100-02BA,U+02BD-02C5,U+02C7-02CC,U+02CE-02D7,U+02DD-02FF,U+0304,"
    "U+0308,U+0329,U+1D00-1DBF,U+1E00-1E9F,U+1EF2-1EFF,U+2020,U+20A0-20AB,U+20AD-20C0,"
    "U+2113,U+2C60-2C7F,U+A720-A7FF",
    "cyrillic": "U+0301,U+0400-045F,U+0490-0491,U+04B0-04B1,U+2116",
    "cyrillic-ext": "U+0460-052F,U+1C80-1C8A,U+20B4,U+2DE0-2DFF,U+A640-A69F,U+FE2E-FE2F",
    "vietnamese": "U+0102-0103,U+0110-0111,U+0128-0129,U+0168-0169,U+01A0-01A1,"
    "U+01AF-01B0,U+0300-0301,U+0303-0304,U+0308-0309,U+0323,U+0329,U+1EA0-1EF9,U+20AB",
}

GROUND = (12, 12, 12)
TITLE_INK = (245, 245, 245)
SUBTITLE_INK = (168, 168, 168)
TITLE_WEIGHT = 600
SUBTITLE_WEIGHT = 400
TITLE_SIZE = 0.075  # of the frame's short side
SUBTITLE_SIZE = 0.036
MAX_WIDTH = 0.8  # of the frame's width
MIN_SCALE = 0.5  # a long title shrinks to half size, then wraps onto a second line


def _ranges(spec: str) -> list[tuple[int, int]]:
    out = []
    for part in spec.split(","):
        a, _, b = part.removeprefix("U+").partition("-")
        out.append((int(a, 16), int(b or a, 16)))
    return out


_RANGES = {name: _ranges(spec) for name, spec in SUBSETS.items()}


def subset_for(ch: str) -> str | None:
    """The bundled subset that draws ``ch``; None when none does."""
    code = ord(ch)
    for name, ranges in _RANGES.items():
        if any(a <= code <= b for a, b in ranges):
            return name
    return None


def covered(text: str) -> bool:
    """Whether the bundled fonts can draw every character of ``text``."""
    return all(subset_for(ch) is not None for ch in text)


@cache
def fonts_digest() -> str:
    """A digest of the bundled font files: a changed font draws a card anew."""
    h = hashlib.sha256()
    for path in sorted(FONTS.glob("*.woff2")):
        h.update(path.name.encode())
        h.update(path.read_bytes())
    return h.hexdigest()[:16]


@cache
def _font(subset: str, size: int, weight: int) -> ImageFont.FreeTypeFont:
    font = ImageFont.truetype(str(FONTS / f"geist-{subset}-wght-normal.woff2"), size)
    font.set_variation_by_axes([weight])
    return font


def _runs(text: str) -> list[tuple[str, str]]:
    """``text`` split into runs drawn by one subset each."""
    runs: list[tuple[str, str]] = []
    for ch in text:
        name = subset_for(ch)
        if name is None:
            raise ValueError(f"no bundled font draws {ch!r}")
        if runs and runs[-1][0] == name:
            runs[-1] = (name, runs[-1][1] + ch)
        else:
            runs.append((name, ch))
    return runs


def _length(text: str, size: int, weight: int) -> float:
    return sum(_font(n, size, weight).getlength(run) for n, run in _runs(text))


def _draw(
    draw: ImageDraw.ImageDraw,
    text: str,
    size: int,
    weight: int,
    baseline: float,
    width: int,
    ink: tuple[int, int, int],
) -> None:
    x = (width - _length(text, size, weight)) / 2
    for name, run in _runs(text):
        font = _font(name, size, weight)
        draw.text((x, baseline), run, font=font, fill=ink, anchor="ls")
        x += font.getlength(run)


def _fit(text: str, base: int, weight: int, room: float) -> tuple[list[str], int]:
    """The lines and size ``text`` is drawn at: one line, shrunk down to half size to
    fit ``room``; else two lines at the size where the longer one fits."""
    size = base
    while size > base * MIN_SCALE and _length(text, size, weight) > room:
        size -= 1
    if _length(text, size, weight) <= room:
        return [text], size
    words = text.split()
    best = [text]
    if len(words) > 1:
        splits = [(" ".join(words[:i]), " ".join(words[i:])) for i in range(1, len(words))]
        best = list(min(splits, key=lambda ab: max(_length(t, base, weight) for t in ab)))
    size = base
    while size > 8 and max(_length(t, size, weight) for t in best) > room:
        size -= 1
    return best, size


def card_image(title: str, subtitle: str, width: int, height: int) -> Image.Image:
    """A title card at ``width``×``height``: the title (one or two lines) and, below it,
    the subtitle, centred on the frame. Both must be ``covered``."""
    img = Image.new("RGB", (width, height), GROUND)
    draw = ImageDraw.Draw(img)
    short = min(width, height)
    room = width * MAX_WIDTH
    lines, size = _fit(title, round(short * TITLE_SIZE), TITLE_WEIGHT, room) if title else ([], 0)
    sub_lines, sub_size = (
        _fit(subtitle, round(short * SUBTITLE_SIZE), SUBTITLE_WEIGHT, room) if subtitle else ([], 0)
    )
    line_gap = size * 1.25
    block = len(lines) * line_gap + (sub_size * 2.2 if sub_lines else 0)
    baseline = (height - block) / 2 + size * 0.95
    for line in lines:
        _draw(draw, line, size, TITLE_WEIGHT, baseline, width, TITLE_INK)
        baseline += line_gap
    if sub_lines:
        baseline += sub_size * 0.9 if lines else 0
        for line in sub_lines:
            _draw(draw, line, sub_size, SUBTITLE_WEIGHT, baseline, width, SUBTITLE_INK)
            baseline += sub_size * 1.4
    return img
