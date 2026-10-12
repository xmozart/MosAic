"""Stills on the timeline (MEDIA_SUPPORT.md §3; ADR 0075): a photo as a canvas of the
output's shape, which the still chunk pans and zooms over.

The canvas is made with Pillow from the photo decoded in display orientation (EXIF
applied: no sideways stills), larger than the output so the motion has room:

- a photo within a third of the output's shape fills it (a centre crop: 4:3 and 3:2
  photos in a 16:9 edit);
- otherwise it sits whole on a blurred, darkened copy of itself that fills the frame
  (the blurred fill), never stretched and never with bars. The blur is Pillow's Gaussian
  blur on a small copy: FFmpeg's ``boxblur`` is GPL and is never used.

The original is only read (invariant 1).
"""

from __future__ import annotations

from fractions import Fraction
from pathlib import Path

from PIL import Image, ImageEnhance, ImageFilter

from mosaic.media.photo import open_image

CANVAS_SCALE = Fraction(3, 2)  # canvas / output: room to pan and zoom without upscaling
MAX_CANVAS_LONG_SIDE = 6144
# A photo within a third of the output's shape fills it: 4:3 and 3:2 photos fill a 16:9
# edit (Ken Burns crops), a portrait photo gets the blurred fill (ADR 0075).
COVER_WITHIN = Fraction(4, 3) * Fraction(101, 100)  # a 1 % margin: 4000×3008 still fills
BLUR_SMALL = 96  # the blurred fill is made from a copy this many pixels on its short side
BLUR_RADIUS = 6
FILL_BRIGHTNESS = 0.6


def canvas_size(out_w: int, out_h: int) -> tuple[int, int]:
    """Even, ``CANVAS_SCALE`` × the output, the long side capped."""
    w, h = Fraction(out_w) * CANVAS_SCALE, Fraction(out_h) * CANVAS_SCALE
    long_side = max(w, h)
    if long_side > MAX_CANVAS_LONG_SIDE:
        w, h = w * MAX_CANVAS_LONG_SIDE / long_side, h * MAX_CANVAS_LONG_SIDE / long_side
    return 2 * round(w / 2), 2 * round(h / 2)


def covers(img_w: int, img_h: int, out_w: int, out_h: int) -> bool:
    a, b = Fraction(img_w, img_h), Fraction(out_w, out_h)
    return (a / b if a >= b else b / a) <= COVER_WITHIN


def _cover(img: Image.Image, w: int, h: int) -> Image.Image:
    scale = max(w / img.width, h / img.height)
    rw, rh = max(w, round(img.width * scale)), max(h, round(img.height * scale))
    big = img.resize((rw, rh), Image.Resampling.LANCZOS)
    left, top = (rw - w) // 2, (rh - h) // 2
    return big.crop((left, top, left + w, top + h))


def canvas(path: Path, out_w: int, out_h: int) -> Image.Image:
    """The photo at ``path`` as an RGB canvas of the output's shape (see the module)."""
    w, h = canvas_size(out_w, out_h)
    img, _ = open_image(path, short_side=min(w, h))
    img = img.convert("RGB")
    if covers(img.width, img.height, out_w, out_h):
        return _cover(img, w, h)
    small_scale = BLUR_SMALL / min(img.width, img.height)
    small = img.resize(
        (max(1, round(img.width * small_scale)), max(1, round(img.height * small_scale))),
        Image.Resampling.BILINEAR,
    )
    fill = _cover(small, max(1, w // 8), max(1, h // 8)).filter(
        ImageFilter.GaussianBlur(BLUR_RADIUS)
    )
    fill = ImageEnhance.Brightness(fill.resize((w, h), Image.Resampling.BILINEAR)).enhance(
        FILL_BRIGHTNESS
    )
    scale = min(w / img.width, h / img.height)
    fg = img.resize(
        (max(1, round(img.width * scale)), max(1, round(img.height * scale))),
        Image.Resampling.LANCZOS,
    )
    fill.paste(fg, ((w - fg.width) // 2, (h - fg.height) // 2))
    return fill


def motion_exprs(motion: dict[str, object], frames: int) -> tuple[str, str, str]:
    """``zoompan``'s zoom, x and y over output frame ``on`` for ``motion`` (start and end
    rectangles in thousandths of the canvas, with an easing); the rectangles keep the
    output's shape, so one zoom serves both axes."""
    start, end = motion["start"], motion["end"]
    if not isinstance(start, dict) or not isinstance(end, dict):
        raise ValueError("a still's motion needs start and end rectangles")
    if start["w"] != start["h"] or end["w"] != end["h"]:
        # In thousandths of the frame, so equal w and h keep the frame's shape.
        raise ValueError("a still's rectangles keep the frame's shape (w equals h)")
    last = max(1, frames - 1)
    t = f"(on/{last})"
    p = f"((1-cos(PI*{t}))/2)" if motion.get("easing") == "ease_in_out" else t

    def lerp(key: str) -> str:
        a, b = int(start[key]), int(end[key])
        return f"({a}+({b - a})*{p})"

    zoom = f"(1000/{lerp('w')})"
    x = f"(iw*{lerp('x')}/1000)"
    y = f"(ih*{lerp('y')}/1000)"
    return zoom, x, y
