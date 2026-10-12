"""Edit services shared by the CLI and the API: create, generate (as a job), report."""

from __future__ import annotations

from fractions import Fraction
from typing import Any

from sqlalchemy import func, select

from mosaic.core.clock import now_iso
from mosaic.core.ids import new_ulid
from mosaic.core.principal import Principal
from mosaic.core.time import format_display, parse_rational
from mosaic.editing.request import Category, EditRequest
from mosaic.jobs.executor import Executor
from mosaic.jobs.model import JobSpec, ResourceClass, TaskSpec
from mosaic.library import decisions
from mosaic.library.clip_view import reason_words
from mosaic.library.dispositions import effective
from mosaic.media.pipeline import job_cost_limit
from mosaic.storage.control import ControlDB
from mosaic.storage.models_project import (
    Asset,
    AssetFile,
    DeepReview,
    Edit,
    EditVersion,
    MediaFile,
    Segment,
    VisualObservation,
)
from mosaic.storage.projects import Project

REJECTED_PAGE = 200


class EditNotFoundError(LookupError):
    pass


def edit_ref(edit_id: int) -> str:
    return f"edt_{edit_id:04d}"


def resolve_edit(project: Project, ref: str) -> int:
    """``edt_0001`` (CLI display id) or the edit's ULID (API id) → row id."""
    text = ref.strip()
    with project.db.session() as s:
        if text.startswith("edt_") and text[4:].isdigit():
            found = s.get(Edit, int(text[4:]))
        else:
            found = s.scalar(select(Edit).where(Edit.uid == text.upper()))
    if found is None:
        raise EditNotFoundError(f"no edit {ref!r} in this project")
    return found.id


def create_edit(
    project: Project,
    request: EditRequest,
    control: ControlDB,
    principal: Principal,
    name: str | None = None,
) -> int:
    """The edit with this exact request (re-running ``mosaic edit`` reuses it), or a new
    one, registered in the control DB's edit index. A different ``--variant`` is a
    different request, hence a new take."""
    body = request.model_dump(mode="json")
    with project.write() as s:
        existing = next(
            (e for e in s.scalars(select(Edit).order_by(Edit.id)) if _same(e.request, body)),
            None,
        )
        if existing is None:
            existing = Edit(
                uid=new_ulid(),
                name=name or f"{request.story.replace('_', ' ')} · {request.duration_s} s",
                request=body,
                created_at=now_iso(),
            )
            s.add(existing)
            s.flush()
        edit_id, uid = existing.id, existing.uid
    control.index_edit(principal, uid, project.id)
    return edit_id


def _same(stored: dict[str, Any], body: dict[str, Any]) -> bool:
    """Whether a stored request is this one, once fields added since it was saved take
    their defaults (an M2 request is the same request in M4; ADR 0066)."""
    if stored == body:
        return True
    try:
        return EditRequest.model_validate(stored).model_dump(mode="json") == body
    except ValueError:
        return False


def submit_generate(
    executor: Executor,
    principal: Principal,
    project: Project,
    edit_id: int,
    cost_limit_usd: float | None = None,
) -> int:
    """Generate the edit again. A changed draft is saved first, so regenerating never
    loses the owner's unsaved storyboard changes (ADR 0067)."""
    save_draft(project, edit_id, creator="system", reason="Saved before regenerate")
    return executor.submit(
        principal,
        JobSpec(
            project_id=project.id,
            kind="edit",
            params={"edit_id": edit_id},
            cost_limit_usd=(
                job_cost_limit(principal) if cost_limit_usd is None else cost_limit_usd
            ),
            tasks=[
                TaskSpec(
                    kind="edit.generate",
                    stage="edit",
                    resource_class=ResourceClass.AI_API,
                    params={"edit_id": edit_id},
                    label=f"generating {edit_ref(edit_id)}",
                )
            ],
        ),
    )


def draft_state(project: Project, edit_id: int) -> dict[str, Any]:
    """The edit's draft for S16, timed now (ADR 0067)."""
    from mosaic.editing import draft

    with project.db.session() as s:
        d = draft.load(s, edit_id)
        req, inp = draft.inputs(s, d)
        return draft.as_json(d, draft.timed(s, req, inp, d.board))


def change_draft(project: Project, edit_id: int, action: str, op: Any = None) -> bool:
    """``op`` (an ``draft.Op``), ``undo`` or ``redo``; False when undo or redo had
    nothing to do. Raises ``draft.DraftError`` for an op that does not fit."""
    from mosaic.editing import draft

    timed_on = None
    if action == "op" and isinstance(op, draft.LockShot):
        # A lock keeps the shot's cut as it is now: the server records it (ADR 0068).
        with project.db.session() as s:
            d = draft.load(s, edit_id)
            req, inp = draft.inputs(s, d)
            op = draft.pinned(op, draft.timed(s, req, inp, d.board), d.board)
        timed_on = (d.base.version, d.ops)
    with project.write() as s:
        if action == "op":
            if isinstance(op, draft.LockShot):
                now = draft.load(s, edit_id)
                if (now.base.version, now.ops) != timed_on:
                    raise draft.DraftChangedError("the draft changed while locking; try again")
            draft.add(s, edit_id, op)
            return True
        return draft.undo(s, edit_id) if action == "undo" else draft.redo(s, edit_id)


def save_draft(
    project: Project,
    edit_id: int,
    *,
    creator: str = "user",
    reason: str = "Saved from the storyboard",
) -> int | None:
    """The draft as a new version, with its JSON export (invariant 7); None when the
    edit has no version or its draft no changes. Timed in a read session, then committed
    under the writer (``draft.DraftChangedError`` if it changed in between)."""
    from mosaic.editing import draft
    from mosaic.editing.generate import export_path, version_json, write_export

    with project.db.session() as s:
        if draft.latest(s, edit_id) is None:
            return None
        _, inp = draft.inputs(s, draft.load(s, edit_id))
        t = draft.time_for_save(s, project.id, edit_id, inp)
    if t is None:
        return None
    with project.write() as s:
        row = draft.commit(s, edit_id, t, creator=creator, reason=reason)
        edit = s.get(Edit, edit_id)
        assert edit is not None
        number, payload = row.version, version_json(edit, row)
    write_export(export_path(project.workspace, edit_id, number), payload)
    project.checkpoint()  # snapshots follow edit commits (ARCHITECTURE.md §4)
    return number


def draft_dirty(project: Project, edit_id: int) -> bool:
    from mosaic.editing import draft

    with project.db.session() as s:
        return draft.latest(s, edit_id) is not None and draft.load(s, edit_id).dirty


def submit_regenerate_beat(
    executor: Executor,
    principal: Principal,
    project: Project,
    edit_id: int,
    beat_id: str,
    directive: str | None = None,
) -> int:
    """A fresh take on one beat, keeping its locked shots (ADR 0069); ``directive``:
    ``opening`` or ``ending`` (ADR 0074). A changed draft is saved first;
    ``draft.DraftError`` when the beat has no free slot, ``LookupError`` for an unknown
    edit or beat."""
    from mosaic.editing import draft, regenerate

    with project.db.session() as s:
        regenerate.slots(draft.load(s, edit_id).board, beat_id)  # refuse before saving
    save_draft(project, edit_id, creator="system", reason="Saved before regenerate")
    return executor.submit(
        principal,
        JobSpec(
            project_id=project.id,
            kind="edit",
            params={"edit_id": edit_id, "beat_id": beat_id, "directive": directive},
            cost_limit_usd=job_cost_limit(principal),
            tasks=[
                TaskSpec(
                    kind="edit.regenerate_beat",
                    stage="edit",
                    resource_class=ResourceClass.AI_API,
                    params={"edit_id": edit_id, "beat_id": beat_id, "directive": directive},
                    label=f"regenerating {beat_id} of {edit_ref(edit_id)}",
                )
            ],
        ),
    )


def submit_regenerate(
    executor: Executor,
    principal: Principal,
    project: Project,
    edit_id: int,
    scope: str,
) -> int:
    """Regenerate the story (a new structure from the edit's own clips) or the whole edit,
    keeping the owner's locked shots (ADR 0070). A changed draft is saved first."""
    from mosaic.editing import draft, regenerate

    if scope not in regenerate.SCOPES:
        raise ValueError(f"scope must be one of {', '.join(regenerate.SCOPES)}")
    with project.db.session() as s:
        draft.load(s, edit_id)  # LookupError: no version to regenerate yet
    save_draft(project, edit_id, creator="system", reason="Saved before regenerate")
    return executor.submit(
        principal,
        JobSpec(
            project_id=project.id,
            kind="edit",
            params={"edit_id": edit_id, "scope": scope},
            cost_limit_usd=job_cost_limit(principal),
            tasks=[
                TaskSpec(
                    kind="edit.regenerate",
                    stage="edit",
                    resource_class=ResourceClass.AI_API,
                    params={"edit_id": edit_id, "scope": scope},
                    label=f"regenerating the {'story' if scope == 'story' else 'edit'} of "
                    f"{edit_ref(edit_id)}",
                )
            ],
        ),
    )


def duration_words(seconds: int) -> str:
    """90 → "90 s", 150 → "2:30" (display)."""
    return f"{seconds} s" if seconds < 120 else f"{seconds // 60}:{seconds % 60:02d}"


def set_duration(project: Project, edit_id: int, seconds: int) -> int | None:
    """ "Make it N seconds" (PRODUCT.md §8; M4 acceptance 3; ADR 0071): the storyboard
    re-timed to the new length, with no AI call, saved as a new version. None (nothing
    saved) when the edit is that length and nothing is pending. Unsaved changes are saved
    first as a version of their own, unless a length change is among them: then they all
    go into this one."""
    from mosaic.editing import draft

    with project.db.session() as s:
        d = draft.load(s, edit_id)
        base_s = EditRequest.model_validate(d.base.request).duration_s
        now = draft.request_of(EditRequest.model_validate(d.base.request), d.board).duration_s
    if now == seconds == base_s:
        return None
    pending_length = any(op.get("kind") == "set_duration" for op in d.ops)
    if d.dirty and not pending_length:
        save_draft(project, edit_id, creator="system", reason="Saved before a length change")
    if now != seconds:
        change_draft(project, edit_id, "op", draft.SetDuration(duration_s=seconds))
    return save_draft(project, edit_id, reason=f"Made it {duration_words(seconds)}")


def alternatives(project: Project, edit_id: int, ref: str) -> tuple[list[dict[str, Any]], bool]:
    """What a shot can be replaced with (S16's ShotPopover): the selector's alternatives
    first, with why each was not chosen, then the rest of its beat's pool that the edit
    does not use; only clips that are still candidates. And whether the shot is locked
    (then ``replace_shot`` is refused until it is unlocked)."""
    from mosaic.editing import draft

    with project.db.session() as s:
        d = draft.load(s, edit_id)
        beat, _, sh = d.board.shot(ref)
        by_ref = {c.ref: c for c in draft.inputs(s, d)[1].cands}
    taken = d.board.segments() | set(d.board.excluded)
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    named = [(a["segment_id"], a.get("why_not")) for a in sh.alternatives]
    for seg, why in [*named, *((r, None) for r in beat.pool)]:
        if seg in seen or seg in taken or seg not in by_ref:
            continue
        seen.add(seg)
        c = by_ref[seg]
        out.append(
            {
                "segment_id": seg,
                "asset_id": f"ast_{c.asset_id:04d}",
                "why_not": why,
                "line": c.line(),
                "usable": {"ticks": c.usable_end - c.usable_start, "tb": c.tb},
                "has_speech": c.has_speech,
            }
        )
    return out, sh.locked or bool(sh.absorbed_by)


WEIGHT_STEPS = ("avoid", "less", "neutral", "more", "strong")


def submit_end(
    executor: Executor, principal: Principal, project: Project, edit_id: int, end: str
) -> int:
    """A stronger opening (the first beat) or a different ending (the last), regenerated
    with that directive around their locked shots (PRODUCT.md §8; ADR 0074)."""
    from mosaic.editing import draft

    with project.db.session() as s:
        beats = draft.load(s, edit_id).board.beats
    if not beats:
        raise LookupError("this edit has no beats")
    beat = beats[0] if end == "opening" else beats[-1]
    return submit_regenerate_beat(executor, principal, project, edit_id, beat.beat_id, end)


def more_or_less(
    executor: Executor,
    principal: Principal,
    project: Project,
    edit_id: int,
    category: Category,
    more: bool,
) -> tuple[int, str]:
    """More or less of a content category (PRODUCT.md §8; ADR 0074): its weight moves one
    step (avoid, less, neutral, more, strong) and the whole edit is regenerated with it,
    keeping the owner's locks. Returns the job and the new weight; ``draft.DraftError``
    when the weight cannot move further that way."""
    from mosaic.editing import draft

    with project.db.session() as s:
        d = draft.load(s, edit_id)
        now = draft.request_of(EditRequest.model_validate(d.base.request), d.board)
    current = now.weights.get(category, "neutral")
    i = WEIGHT_STEPS.index(current) + (1 if more else -1)
    if not 0 <= i < len(WEIGHT_STEPS):
        raise draft.DraftError(
            f"{category.replace('_', ' ')} is already {'strongly preferred' if more else 'avoided'}"
        )
    weight = WEIGHT_STEPS[i]
    change_draft(project, edit_id, "op", draft.SetWeight(category=category, weight=weight))
    try:
        return submit_regenerate(executor, principal, project, edit_id, "all"), weight
    except draft.DraftChangedError:
        # Not queued: put the weight back with an op of its own. An undo could take back
        # the owner's change that raced in instead (invariant 10).
        back = draft.SetWeight(category=category, weight=current)
        change_draft(project, edit_id, "op", back)
        raise


def get_version(project: Project, edit_id: int, version: int | None = None) -> EditVersion:
    with project.db.session() as s:
        q = select(EditVersion).where(EditVersion.edit_id == edit_id)
        q = q.where(EditVersion.version == version) if version else q
        row = s.scalar(q.order_by(EditVersion.version.desc()).limit(1))
    if row is None:
        which = f"version {version} of " if version else ""
        raise EditNotFoundError(f"no {which}{edit_ref(edit_id)}; run `mosaic edit` first")
    return row


def _source_file(s: Any, asset_id: int, ticks: int) -> str | None:
    rows = list(
        s.execute(
            select(AssetFile.logical_start_ticks, AssetFile.duration_ticks, MediaFile.rel_path)
            .join(MediaFile, MediaFile.id == AssetFile.media_file_id)
            .where(AssetFile.asset_id == asset_id)
            .order_by(AssetFile.order)
        )
    )
    for start, dur, path in rows:
        if start <= ticks < start + dur:
            return str(path)
    return str(rows[-1][2]) if rows else None


def report(
    project: Project, edit_id: int, version: int | None = None, rejected_offset: int = 0
) -> dict[str, Any]:
    """Selection and rejection report (PRODUCT.md §7): every event with its role, reason,
    alternatives, source and description; every REJECT segment with its reasons (paged)."""
    v = get_version(project, edit_id, version)
    events_out = []
    selections = v.timeline.get("selections", {})
    with project.db.session() as s:
        for e in v.timeline["tracks"][0]["events"]:
            sid = int(e["segment_id"][4:])
            aid = int(e["asset_id"][4:])
            sel = selections.get(e["origin"]["selection_ref"], {})
            # The L3 full-resolution observation, when present, is what selection used.
            obs = s.scalar(select(DeepReview.data).where(DeepReview.segment_id == sid)) or s.scalar(
                select(VisualObservation.data).where(VisualObservation.segment_id == sid)
            )
            tb = parse_rational(e["source_in"]["tb"])
            events_out.append(
                {
                    "event_id": e["event_id"],
                    "beat_id": e.get("beat_id"),
                    "role": e["role"],
                    "segment_id": e["segment_id"],
                    "source_file": _source_file(s, aid, e["source_in"]["ticks"]),
                    "source_in": e["source_in"],
                    "source_out": e["source_out"],
                    "timeline_in": e["timeline_in"],
                    "timeline_out": e["timeline_out"],
                    "display": "photo"
                    if e.get("kind") == "still"
                    else (
                        f"{format_display(Fraction(e['source_in']['ticks']) * tb)}–"
                        f"{format_display(Fraction(e['source_out']['ticks']) * tb)}"
                    ),
                    "reason": sel.get("reason"),
                    "priority": sel.get("priority"),
                    "audio_intent": e["audio"].get("intent"),
                    "alternatives": sel.get("alternatives", []),
                    "description": (obs or {}).get("description"),
                    "interest": (obs or {}).get("interest"),
                    "composition": (obs or {}).get("composition"),
                }
            )
        # The decisions in force (ADR 0042): the owner's, segment or whole clip, override
        # the analysis (invariant 10).
        q = decisions.rejected_segments()
        rejected_rows = list(s.execute(q.offset(rejected_offset).limit(REJECTED_PAGE)))
        rejected_total = s.scalar(select(func.count()).select_from(q.order_by(None).subquery()))
        ids = [sid for sid, _, _ in rejected_rows]
        rows = effective(s, ids)
        starts = {
            g: t
            for g, t in s.execute(
                select(Segment.id, Segment.start_ticks).where(Segment.id.in_(ids))
            )
        }
        page_assets = {aid for _, aid, _ in rejected_rows}
        assets = {a.id: a for a in s.scalars(select(Asset).where(Asset.id.in_(page_assets)))}
        rejected = []
        for sid, aid, source in rejected_rows:
            d = rows.get(sid)
            if source == "clip":
                reasons: list[Any] = [{"code": "clip_rejected"}]
            else:
                reasons = list(d.reasons) if d is not None else []
            a = assets.get(aid)
            rejected.append(
                {
                    "segment_id": f"seg_{sid:06d}",
                    "asset_id": f"ast_{aid:04d}",
                    "source": "user" if source == "clip" else source,
                    "whole_clip": source == "clip",
                    "reasons": reasons,
                    "words": reason_words(reasons),
                    "source_file": _source_file(s, aid, starts.get(sid, 0)),
                    "camera": (a.camera_model or a.profile) if a else None,
                }
            )
    unused_selections = [
        {"selection_ref": ref, **sel} for ref, sel in selections.items() if not sel.get("used")
    ]
    with project.db.session() as s:
        edit = s.get(Edit, edit_id)
        uid = edit.uid if edit else None
    return {
        "edit_id": edit_ref(edit_id),
        "uid": uid,
        "version": v.version,
        "title": v.timeline.get("title"),
        "request": v.request,
        "rate": v.rate,
        "beats": v.beats,
        "metrics": v.metrics,
        "findings": v.findings,
        "events": events_out,
        "not_used": unused_selections,
        "rejected": {"total": rejected_total, "offset": rejected_offset, "items": rejected},
    }


def report_text(r: dict[str, Any]) -> str:
    m = r["metrics"]
    rate = parse_rational(r["rate"])
    ok = "ok" if m["duration_ok"] else "OUT OF TOLERANCE"
    lines = [
        f"{r['edit_id']} v{r['version']}: {r.get('title') or ''}",
        f"  duration {format_display(Fraction(m['total_frames']) / rate)} "
        f"(target {format_display(Fraction(m['target_frames']) / rate)}, "
        f"error {m['duration_error_frames']:+d} frames, {ok})",
        f"  events {m['events']} · mid-word cuts {m['mid_word_cuts']} · dialogue truncations "
        f"{m['dialogue_truncations']} · jump cuts {m['adjacent_jump_cuts']} · REJECT used "
        f"{m['reject_used']} · repeats {m['same_group_within_5']}",
        f"  blocking metrics: {'all zero' if m['blocking_ok'] else 'FAILED'}",
        "",
    ]
    beats = {b["beat_id"]: b for b in r["beats"]}
    current = None
    for e in r["events"]:
        if e["beat_id"] != current:
            current = e["beat_id"]
            b = beats.get(current, {})
            lines.append(f"[{current}] {b.get('title', '')} — {b.get('intent', '')}")
        t = format_display(Fraction(e["timeline_in"]["frames"]) / rate)
        lines.append(
            f"  {t}  {e['event_id']} {e['role']:<12} {e['segment_id']}  {e['source_file']} "
            f"{e['display']}"
        )
        if e.get("description"):
            lines.append(f"        {e['description']}")
        if e.get("reason"):
            lines.append(f"        why: {e['reason']}")
        for alt in e.get("alternatives", []):
            lines.append(f"        instead of {alt['segment_id']}: {alt['why_not']}")
    if r["findings"]:
        lines.append("")
        lines.append("Findings:")
        for f in r["findings"]:
            lines.append(f"  [{f['severity']}] {f['code']}: {f['text']}")
    rej = r["rejected"]
    lines.append("")
    lines.append(f"Rejected segments: {rej['total']}")
    for x in rej["items"][:50]:
        codes = ", ".join(sorted({c["code"] for c in x["reasons"]})) or x["source"]
        lines.append(f"  {x['segment_id']} ({x['asset_id']}): {codes}")
    if rej["total"] > 50:
        lines.append(f"  … {rej['total'] - 50} more (see the JSON report)")
    return "\n".join(lines)
