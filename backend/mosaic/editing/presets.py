"""Story presets for the edit wizard (S14 step 2; ADR 0047).

Each card shows a collage of the owner's own footage that suits the story: the preset's
query runs through library search (visual and text), rejected moments are skipped, one
frame per clip. A story without a query (the diary) and any shortfall are filled with the
library's best moments spread over the trip. Only reads; nothing is stored.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from mosaic.editing.request import STORY_PRESETS
from mosaic.library import browse
from mosaic.library import search as lib
from mosaic.storage.models_project import Asset, Segment

# The wizard's cards, in order; the other presets are under Custom.
FEATURED = (
    "cinematic_journey",
    "chronological_diary",
    "adventure_highlights",
    "family_memories",
    "wildlife",
    "funny_moments",
    "high_energy_montage",
)
LABELS = {
    "chronological_diary": "Chronological diary",
    "cinematic_journey": "Cinematic journey",
    "adventure_highlights": "Adventure highlights",
    "family_memories": "Family memories",
    "people_first": "People first",
    "nature": "Nature",
    "wildlife": "Wildlife",
    "food_culture": "Food and culture",
    "city": "City",
    "road_trip": "Road trip",
    "relaxed": "Relaxed",
    "high_energy_montage": "High-energy montage",
    "documentary": "Documentary",
    "funny_moments": "Funny moments",
    "drone_showcase": "Drone showcase",
    "event_recap": "Event recap",
}
QUERIES: dict[str, str | None] = {
    "chronological_diary": None,
    "cinematic_journey": "wide landscape scenery",
    "adventure_highlights": "adventure activity action",
    "family_memories": "people smiling together",
    "people_first": "people faces",
    "nature": "nature landscape water",
    "wildlife": "animals wildlife",
    "food_culture": "food market",
    "city": "city street buildings",
    "road_trip": "road car driving",
    "relaxed": "calm beach sunset",
    "high_energy_montage": "fast action motion",
    "documentary": "people talking",
    "funny_moments": "people laughing",
    "drone_showcase": "aerial drone view",
    "event_recap": "crowd event",
}
COLLAGE = 4
BEST_POOL = 200  # top-quality moments the spread fill picks from


def cards() -> list[dict[str, Any]]:
    return [
        {
            "id": p,
            "label": LABELS[p],
            "description": STORY_PRESETS[p],
            "featured": p in FEATURED,
        }
        for p in (*FEATURED, *(p for p in STORY_PRESETS if p not in FEATURED))
    ]


def collage(s: Session, embedder: Any | None, preset: str, n: int = COLLAGE) -> list[int]:
    """Up to ``n`` sample frame ids, one per clip."""
    if preset not in STORY_PRESETS:
        raise KeyError(preset)
    frames: list[int] = []
    clips: set[int] = set()
    query = QUERIES.get(preset)
    if query:
        found = lib.search(s, embedder, query, "visual", limit=n * 6)
        for item in lib.describe(s, found.hits):
            if item["status"] == "REJECT" or not item["sample_id"]:
                continue
            if item["asset_id"] in clips:
                continue
            clips.add(item["asset_id"])
            frames.append(item["sample_id"])
            if len(frames) == n:
                return frames
    return frames + _spread(s, n - len(frames), clips)


def _spread(s: Session, n: int, skip: set[int]) -> list[int]:
    """The best moment of up to ``n`` clips, evenly spread over the trip's time."""
    if n <= 0:
        return []
    st = browse.status_table()
    rows = list(
        s.execute(
            select(Segment.id, Segment.asset_id, Asset.capture_time)
            .join(Asset, Asset.id == Segment.asset_id)
            .join(st, st.c.asset_id == Asset.id)
            .where(Asset.status == "ok", (st.c.p.is_(None)) | (st.c.p != 3))
            .order_by(Segment.quality.desc().nulls_last(), Segment.id)
            .limit(BEST_POOL)
        )
    )
    best: dict[int, tuple[int, str]] = {}
    for gid, aid, when in rows:
        if aid not in skip and aid not in best:
            best[aid] = (gid, when or "")
    ordered = sorted(best.items(), key=lambda kv: (kv[1][1], kv[0]))
    if len(ordered) > n:
        step = len(ordered) / n
        ordered = [ordered[int(i * step)] for i in range(n)]
    hits = [lib.Hit(gid, aid) for aid, (gid, _) in ordered]
    lib.fill_frames(s, hits)
    return [h.sample_id for h in hits if h.sample_id]
