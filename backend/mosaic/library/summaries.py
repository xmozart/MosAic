"""Hierarchical summaries (ARCHITECTURE.md §8 stage 14): shot → scene → day → trip.

- **Shot** and **scene** (one recording) summaries are composed from the segments'
  observations (L3 review over L2 vision), without AI. They are cheap and rebuilt on
  every run.
- **Day** and **trip** summaries are written by the ``summarizer`` model, with the trip
  context. A day sees one compact line per recording, and the trip sees one line per day,
  so no call ever receives the whole library (ARCHITECTURE.md §17). Each is keyed on its
  input lines, the context, the prompt and the model, so a summary is re-asked only when
  something it depends on changed. Changing the trip context therefore re-runs these
  calls and nothing else (PRODUCT.md §3).

Times in summaries are for display, apart from ``span``, which is exact.
"""

from __future__ import annotations

import re
from collections import Counter
from datetime import date, timedelta
from fractions import Fraction
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from mosaic.ai.client import AIClient
from mosaic.ai.prompts.summary.schema_v1 import Output
from mosaic.ai.registry import task_check_ready, task_choice
from mosaic.core.keys import artifact_key, digest
from mosaic.core.modes import task_mode
from mosaic.core.time import format_display, parse_rational
from mosaic.editing.retrieval import capture_dates, trip_day
from mosaic.jobs.context import TaskContext
from mosaic.jobs.model import JobSpec, ResourceClass, TaskSpec
from mosaic.jobs.registry import SkipTask, task
from mosaic.library import dispositions as _dispositions  # noqa: F401 - registers first
from mosaic.library.context import TripContext
from mosaic.library.context import load as load_context
from mosaic.library.dispositions import effective
from mosaic.media import inventory
from mosaic.storage import provenance
from mosaic.storage.config import NotConfiguredError
from mosaic.storage.models_project import (
    Asset,
    DeepReview,
    Segment,
    Shot,
    Summary,
    VisualObservation,
)

PROMPT = ("summary", 1)
SUMMARY_VERSION = "summaries/1"
MAX_TOKENS = 1500
MAX_DAY_ITEMS = 80  # recordings per day call; the most interesting are kept beyond that
MAX_TEXT = 400  # characters of a shot or scene summary
SCENE_HIGHLIGHTS = 3
INTEREST = {"high": 3, "medium": 2, "low": 1}
_REF = re.compile(r"seg_\d{6}")


def ref(segment_id: int) -> str:
    return f"seg_{segment_id:06d}"


def _clip(text: str, n: int = MAX_TEXT) -> str:
    return text if len(text) <= n else text[: n - 1].rstrip() + "…"


def _observations(session: Session, ids: list[int]) -> dict[int, dict[str, Any]]:
    obs = {
        o.segment_id: o.data
        for o in session.scalars(
            select(VisualObservation).where(VisualObservation.segment_id.in_(ids))
        )
    }
    obs |= {  # L3 (full resolution) supersedes L2
        r.segment_id: r.data
        for r in session.scalars(select(DeepReview).where(DeepReview.segment_id.in_(ids)))
    }
    return obs


def _rank(o: dict[str, Any]) -> int:
    return INTEREST.get(str(o.get("interest")), 0)


def _compose(segs: list[Segment], obs: dict[int, dict[str, Any]]) -> dict[str, Any] | None:
    """Text, subjects and highlights of a run of segments, from their observations."""
    seen = [g for g in segs if g.id in obs]
    if not seen:
        return None
    descriptions = list(dict.fromkeys(str(obs[g.id].get("description", "")) for g in seen))
    subjects = Counter(s for g in seen for s in obs[g.id].get("subjects", [])[:3])
    best = sorted(seen, key=lambda g: (-_rank(obs[g.id]), g.start_ticks))[:SCENE_HIGHLIGHTS]
    # The most interesting descriptions, in time order.
    keep = {str(obs[g.id].get("description", "")) for g in best}
    text = " ".join(d for d in descriptions if d in keep) or descriptions[0]
    return {
        "text": _clip(text),
        "subjects": [s for s, _ in subjects.most_common(6)],
        "interest": max(_rank(obs[g.id]) for g in seen),
        "highlights": [ref(g.id) for g in best],
        "notes": {ref(g.id): _clip(str(obs[g.id].get("description", "")), 160) for g in best},
    }


class _Writer:
    def __init__(self, ctx: TaskContext, trip: TripContext) -> None:
        self.ctx = ctx
        self.trip = trip
        with ctx.write() as s:
            self.prov = provenance.record(
                s, provenance.ProvenanceInfo(kind="summary", algorithm_version=SUMMARY_VERSION)
            )

    def put(
        self,
        s: Session,
        level: str,
        ref_: int,
        text: str,
        data: dict[str, Any],
        key: str,
        prov: int | None = None,
    ) -> None:
        s.execute(delete(Summary).where(Summary.level == level, Summary.ref == ref_))
        s.add(
            Summary(
                level=level,
                ref=ref_,
                text=text,
                data=data,
                key=key,
                context_digest=self.trip.digest(),
                provenance_id=prov or self.prov,
            )
        )


def _scene_line(asset: Asset, scene: dict[str, Any], tb: Fraction) -> str:
    start = (asset.capture_time or "")[11:16] or "--:--"
    length = format_display(Fraction(asset.duration_ticks or 0) * tb)
    notes = "; ".join(f"{r} ({n})" for r, n in scene["notes"].items())
    subjects = ", ".join(scene["subjects"]) or "-"
    return f"{start} · ast_{asset.id:04d} · {length}: {scene['text']} [{subjects}] Clips: {notes}"


def compose_local(
    ctx: TaskContext, writer: _Writer, first: date | None
) -> dict[int, list[tuple[str, int]]]:
    """Shot and scene summaries, asset by asset. Returns day → (line, interest). Days are
    numbered from ``first`` exactly as the editor numbers them."""
    with ctx.project.db.session() as s:
        assets = list(
            s.scalars(
                select(Asset)
                .where(Asset.kind == "video", Asset.status == "ok")
                .order_by(Asset.capture_time, Asset.id)
            )
        )
    days: dict[int, list[tuple[str, int]]] = {}
    live_shots: set[int] = set()
    live_scenes: set[int] = set()
    for asset in assets:
        ctx.check_cancelled()
        if asset.tb is None:
            continue
        tb = parse_rational(asset.tb)
        with ctx.write() as s:
            segs = list(
                s.scalars(
                    select(Segment)
                    .where(Segment.asset_id == asset.id)
                    .order_by(Segment.start_ticks)
                )
            )
            disp = effective(s, [g.id for g in segs])
            segs = [g for g in segs if not (g.id in disp and disp[g.id].status == "REJECT")]
            obs = _observations(s, [g.id for g in segs])
            shots = list(s.scalars(select(Shot).where(Shot.asset_id == asset.id)))
            for sh in shots:
                part = _compose([g for g in segs if g.shot_id == sh.id], obs)
                if part is None:
                    continue
                live_shots.add(sh.id)
                writer.put(
                    s,
                    "shot",
                    sh.id,
                    part["text"],
                    {k: part[k] for k in ("subjects", "highlights")},
                    "",
                )
            scene = _compose(segs, obs)
            if scene is None:
                continue
            live_scenes.add(asset.id)
            writer.put(
                s,
                "scene",
                asset.id,
                scene["text"],
                {
                    "subjects": scene["subjects"],
                    "highlights": scene["highlights"],
                    "span": {"ticks": asset.duration_ticks or 0, "tb": asset.tb},
                },
                "",
            )
        day = trip_day(asset.capture_time, Fraction(0), first)
        days.setdefault(day, []).append((_scene_line(asset, scene, tb), scene["interest"]))
    with ctx.write() as s:  # summaries of shots and recordings that no longer exist
        for level, live in (("shot", live_shots), ("scene", live_scenes)):
            stale = [
                r
                for r in s.scalars(select(Summary.ref).where(Summary.level == level))
                if r not in live
            ]
            for chunk in range(0, len(stale), 500):
                s.execute(
                    delete(Summary).where(
                        Summary.level == level, Summary.ref.in_(stale[chunk : chunk + 500])
                    )
                )
    return days


def day_items(entries: list[tuple[str, int]]) -> str:
    """At most ``MAX_DAY_ITEMS`` lines, the most interesting kept, in time order."""
    if len(entries) > MAX_DAY_ITEMS:
        ranked = sorted(range(len(entries)), key=lambda i: (-entries[i][1], i))
        keep = set(ranked[:MAX_DAY_ITEMS])
        entries = [e for i, e in enumerate(entries) if i in keep]
    return "\n".join(line for line, _ in entries)


def check_highlights(answer: Any, items: str) -> list[str]:
    known = set(_REF.findall(items))
    bad = [h for h in answer.highlights if h not in known]
    if bad:
        return [f"highlights {', '.join(bad)} are not in the notes; use only listed seg_ refs"]
    if len(set(answer.highlights)) != len(answer.highlights):
        return ["highlights repeat a clip; list each clip once"]
    return []


def day_label(day: int, first: date | None) -> str:
    if day == 0 or first is None:
        return "the recordings without a date"
    return f"day {day} ({(first + timedelta(days=day - 1)).isoformat()})"


@task("library.summaries", checkpoint=True)
def summaries_task(ctx: TaskContext) -> dict[str, Any]:
    if task_mode(ctx).l3 and not ctx.params.get("final"):
        # Thorough: the deep review stage ends with summaries over the reviewed clips;
        # summarizing the L2 descriptions first would only be asked again.
        raise SkipTask("summaries follow the deep review")
    with ctx.project.db.session() as s:
        trip = load_context(s)
        # Days are numbered from all videos, exactly as retrieval and deepen do.
        assets = list(s.scalars(select(Asset).where(Asset.kind == "video")))
        first = min(capture_dates(assets).values(), default=None)
        del assets
        stored = {
            (level, ref_): key
            for level, ref_, key in s.execute(
                select(Summary.level, Summary.ref, Summary.key).where(
                    Summary.level.in_(("day", "trip"))
                )
            )
        }
    writer = _Writer(ctx, trip)
    ctx.set_stage("summaries")
    days = compose_local(ctx, writer, first)
    result: dict[str, Any] = {"days": len(days), "asked": 0, "unchanged": 0}
    try:
        task_check_ready(ctx, "summarizer")
    except NotConfiguredError as exc:
        result["skipped"] = f"day and trip summaries skipped: {exc}"
        return result
    choice = task_choice(ctx, "summarizer")
    client = AIClient(ctx)

    def summarize(level: str, ref_: int, label: str, items: str) -> tuple[str, list[str]]:
        key = artifact_key(
            "summary",
            project_id=ctx.project.id,
            inputs={"items": digest(items), "label": label},
            config={"model": [choice.provider, choice.model], "context": trip.digest()},
            version=f"{PROMPT[0]}/v{PROMPT[1]}+{SUMMARY_VERSION}",
        )
        if stored.get((level, ref_)) == key:
            result["unchanged"] += 1
            with ctx.project.db.session() as s:
                row = s.scalar(select(Summary).where(Summary.level == level, Summary.ref == ref_))
                assert row is not None
                return row.text, list(row.data.get("highlights", []))
        context = {"trip_context": trip.prompt_text(), "level": label, "items": items}
        answer_ = client.structured(
            "summarizer",
            *PROMPT,
            context,
            max_tokens=MAX_TOKENS,
            validate=lambda a: check_highlights(a, items),
        )
        answer = answer_.data
        assert isinstance(answer, Output)
        with ctx.write() as s:
            if load_context(s).digest() != trip.digest():
                # The context changed while this ran; that save started a newer run.
                raise SkipTask("the trip context changed; a newer run summarizes")
            writer.put(
                s,
                level,
                ref_,
                answer.summary,
                {"themes": answer.themes, "highlights": answer.highlights},
                key,
                answer_.provenance_id,
            )
        result["asked"] += 1
        return answer.summary, answer.highlights

    lines = []
    for day in sorted(days):
        ctx.check_cancelled()
        label = day_label(day, first)
        text, highlights = summarize("day", day, label, day_items(days[day]))
        clips = f" Clips: {', '.join(highlights)}" if highlights else ""
        lines.append(f"{label[0].upper()}{label[1:]}: {text}{clips}")
    with ctx.write() as s:
        s.execute(delete(Summary).where(Summary.level == "day", Summary.ref.not_in(list(days))))
        if not days:
            s.execute(delete(Summary).where(Summary.level == "trip"))
    if days:
        summarize("trip", 0, "the whole trip", "\n".join(lines))
    return result


def submit_summaries(executor: Any, principal: Any, project: Any) -> int:
    """Re-run summaries only (after a trip context change; PRODUCT.md §3)."""
    from mosaic.media.pipeline import job_cost_limit

    return int(
        executor.submit(
            principal,
            JobSpec(
                project_id=project.id,
                kind="summaries",
                cost_limit_usd=job_cost_limit(principal),
                tasks=[summaries_spec()],
            ),
        )
    )


def summaries_spec(deps: list[int | tuple[str, int]] | None = None) -> TaskSpec:
    """The summaries task that ends a chain (``final``: it runs in every mode)."""
    return TaskSpec(
        kind="library.summaries",
        stage="summaries",
        resource_class=ResourceClass.AI_API,
        params={"final": True},
        label="summaries",
        deps=deps or [],
    )


# The project stage is registered by ``library.review``, after "deep review": summaries
# come last, so a summarizer failure never cancels an analysis stage.
SUMMARIES_STAGE = inventory.StageDef(
    "summaries", "library.summaries", ResourceClass.AI_API, after=("dispositions",), level=2
)
