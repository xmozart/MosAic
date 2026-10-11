"""Content categories of a clip (PRODUCT.md §4 content weights; S14 step 3; ADR 0072).

Derived, deterministically and without an AI call, from what analysis already knows: the
vision observation's structured fields (shot type, people, camera motion), words in its
subjects and description, speech, the source frame rate, and the owner's own tags. A
category is a hint for weighting and ordering, never a fact shown as a title
(invariant 16).
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from fractions import Fraction
from typing import Any, get_args

from sqlalchemy import select
from sqlalchemy.orm import Session

from mosaic.core.time import parse_rational
from mosaic.editing.request import Category
from mosaic.storage.models_project import (
    Asset,
    ClipTag,
    DeepReview,
    Segment,
    VisualObservation,
)

CATEGORIES: tuple[str, ...] = get_args(Category)  # PRODUCT.md's order

# Words in the observation's subjects and description: whole words (or their plural),
# or any word starting with a ``stem*``.
WORDS: dict[str, tuple[str, ...]] = {
    "reactions": ("laugh*", "smil*", "react*", "cheer*", "surpris*", "excit*", "clap*", "wave at"),
    "landscapes": (
        "landscape",
        "mountain",
        "valley",
        "scenery",
        "vista",
        "hill",
        "desert",
        "forest",
        "jungle",
        "canyon",
        "meadow",
        "volcano",
        "glacier",
        "coast",
    ),
    "wildlife": (
        "animal",
        "bird",
        "monkey",
        "toucan",
        "parrot",
        "dolphin",
        "whale",
        "fish",
        "turtle",
        "deer",
        "elephant",
        "lion",
        "tiger",
        "giraffe",
        "zebra",
        "bear",
        "sloth",
        "lizard",
        "iguana",
        "crocodile",
        "snake",
        "insect",
        "butterfl*",
        "wildlife",
        "horse",
        "cow",
        "goat",
        "sheep",
        "camel",
        "dog",
        "cat",
    ),
    "architecture": (
        "building",
        "temple",
        "church",
        "cathedral",
        "mosque",
        "tower",
        "bridge",
        "architecture",
        "castle",
        "palace",
        "ruin",
        "monument",
        "skyscraper",
        "facade",
    ),
    "food": (
        "food",
        "meal",
        "dish",
        "restaurant",
        "cafe",
        "coffee",
        "dinner",
        "lunch",
        "breakfast",
        "dessert",
        "drink",
        "cook",
        "plate",
        "fruit",
        "street food",
    ),
    "culture": (
        "market",
        "dance",
        "festival",
        "museum",
        "tradition",
        "ceremony",
        "musician",
        "music",
        "art",
        "craft",
        "parade",
        "costume",
        "ritual",
        "bazaar",
        "souk",
    ),
    "action": (
        "surf",
        "jump",
        "swim",
        "dive",
        "diving",
        "snorkel",
        "hike",
        "climb",
        "ride",
        "riding",
        "sport",
        "cycl*",
        "kayak",
        "ski",
        "run",
        "zipline",
        "paraglid*",
        "skate",
        "race",
    ),
    "humor": ("funny", "joke", "silly", "goofy", "prank"),
    "transport": (
        "car",
        "bus",
        "train",
        "boat",
        "ferry",
        "plane",
        "airplane",
        "airport",
        "aircraft",
        "road",
        "highway",
        "vehicle",
        "taxi",
        "tuk",
        "motorbike",
        "jet",
        "helicopter",
    ),
    "sunsets": ("sunset", "sunrise", "golden hour", "dusk", "dawn"),
    "water": (
        "water",
        "sea",
        "ocean",
        "lake",
        "river",
        "waterfall",
        "beach",
        "pool",
        "wave",
        "lagoon",
        "bay",
        "harbor",
        "harbour",
        "reef",
        "stream",
    ),
    "night": ("night", "neon", "stars", "fireworks", "lit up", "illuminat*"),
    "city": ("city", "street", "urban", "downtown", "traffic", "skyline", "alley", "square"),
    "natural_sound": ("waterfall", "waves", "rain", "birdsong", "river", "surf", "wind"),
    "timelapse": ("timelapse", "time-lapse", "time lapse"),
}


def _word(w: str) -> str:
    """``stem*`` matches any word starting so; others a whole word, or its regular plural:
    ``-es`` after s, x, z, ch, sh and o (bus, dish, volcano), ``-ies`` for a consonant
    and y (city), else ``-s``; so "ski" never matches "skies", nor "car" "cares"."""
    if w.endswith("*"):
        return re.escape(w[:-1]) + r"\w*"
    if w.endswith(("s", "x", "z", "ch", "sh", "o")):
        return re.escape(w) + r"(?:es)?\b"
    if len(w) > 1 and w.endswith("y") and w[-2] not in "aeiou":
        return re.escape(w[:-1]) + r"(?:y|ies)\b"
    return re.escape(w) + r"s?\b"


_PATTERNS = {
    cat: re.compile(r"\b(?:" + "|".join(_word(w) for w in words) + r")", re.I)
    for cat, words in WORDS.items()
}
SLOW_MOTION_FPS = Fraction(100)  # high-frame-rate sources are conformed to slow motion


def classify(
    obs: Mapping[str, Any],
    *,
    has_speech: bool = False,
    rate: str | None = None,
    tags: Iterable[str] = (),
    photo: bool = False,
) -> frozenset[str]:
    """The categories one clip belongs to."""
    out: set[str] = set()
    shot = obs.get("shot_type")
    people = obs.get("people")
    if people in ("one", "few", "group", "crowd"):
        out.add("people")
    if shot == "aerial":
        out.add("drone")
    elif shot == "pov":
        out.add("pov")
    elif shot == "selfie":
        out.update(("selfies", "people"))
    if shot in ("establishing_wide", "wide") and people in (None, "none"):
        out.add("landscapes")
    if obs.get("camera_motion") == "vehicle":
        out.add("transport")
    if obs.get("camera_motion") == "tracking":
        out.add("action")
    if has_speech:
        out.add("conversations")
    if rate:
        try:
            if parse_rational(rate) >= SLOW_MOTION_FPS:
                out.add("slow_motion")
        except (ValueError, ZeroDivisionError):
            pass
    if photo:
        out.add("photos")
    text = " ".join([str(obs.get("description") or ""), *map(str, obs.get("subjects") or [])])
    if text.strip():
        out.update(cat for cat, pat in _PATTERNS.items() if pat.search(text))
    for tag in tags:
        t = tag.strip().lower().replace(" ", "_")
        if t in CATEGORIES:
            out.add(t)
    return frozenset(out)


# Content weights as a score bonus in retrieval; "avoid" is a filter, not a score.
WEIGHT_BONUS = {"less": -1.0, "neutral": 0.0, "more": 1.0, "strong": 2.0}


def weight_bonus(cats: Iterable[str], weights: Mapping[str, str]) -> float:
    """The clip's share of the owner's content weights: the strongest preference and the
    strongest dislike among its categories, so one clip is never counted twice up."""
    marks = [WEIGHT_BONUS[weights[c]] for c in cats if weights.get(c) in WEIGHT_BONUS]
    if not marks:
        return 0.0
    return max(0.0, *marks) + min(0.0, *marks)


def avoided(cats: Iterable[str], weights: Mapping[str, str]) -> bool:
    return any(weights.get(c) == "avoid" for c in cats)


BATCH = 200  # clips read together (invariant 13)


def library_counts(session: Session) -> list[dict[str, Any]]:
    """S14 step 3's order (its acceptance: "category ordering comes from library tag
    frequency"): every category with the number of clips that have it, most first,
    PRODUCT.md's order among equals. A clip has a category when any of its segments
    does, or its owner tagged it so; photos count as "photos". Every analysable clip
    counts, rejected ones included: this is what the library holds, not what an edit
    would use."""
    counts = dict.fromkeys(CATEGORIES, 0)
    q = (
        select(Asset.id, Asset.kind, Asset.rate)
        .where(Asset.kind.in_(("video", "photo", "live_photo")), Asset.status == "ok")
        .order_by(Asset.id)
    )
    for part in session.execute(q.execution_options(yield_per=BATCH)).partitions():
        batch: list[tuple[int, str, str | None]] = [(r[0], r[1], r[2]) for r in part]
        ids = [r[0] for r in batch]
        segs: dict[int, list[tuple[int | None, bool]]] = {}
        for sid, aid, speech in session.execute(
            select(Segment.id, Segment.asset_id, Segment.has_speech).where(
                Segment.asset_id.in_(ids)
            )
        ):
            segs.setdefault(aid, []).append((sid, speech))
        in_batch = select(Segment.id).where(Segment.asset_id.in_(ids))
        obs = {
            sid: data
            for sid, data in session.execute(
                select(VisualObservation.segment_id, VisualObservation.data).where(
                    VisualObservation.segment_id.in_(in_batch)
                )
            )
        }
        obs |= {
            sid: data
            for sid, data in session.execute(
                select(DeepReview.segment_id, DeepReview.data).where(
                    DeepReview.segment_id.in_(in_batch)
                )
            )
        }
        tags: dict[int, list[str]] = {}
        for aid, tag in session.execute(
            select(ClipTag.asset_id, ClipTag.tag).where(ClipTag.asset_id.in_(ids))
        ):
            tags.setdefault(aid, []).append(tag)
        for aid, kind, rate in batch:
            found: set[str] = set()
            photo = kind in ("photo", "live_photo")
            for seg_id, speech in segs.get(aid, []) or [(None, False)]:
                found |= classify(
                    obs.get(seg_id, {}) if seg_id is not None else {},
                    has_speech=speech,
                    rate=rate,
                    tags=tags.get(aid, []),
                    photo=photo,
                )
            for cat in found:
                counts[cat] += 1
    order = {c: i for i, c in enumerate(CATEGORIES)}
    return [
        {"category": c, "clips": counts[c]}
        for c in sorted(CATEGORIES, key=lambda c: (-counts[c], order[c]))
    ]
