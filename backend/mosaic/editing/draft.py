"""An edit's draft (ARCHITECTURE.md §13; S16; ADR 0067): the latest version's storyboard
with the owner's changes applied, as an undoable op log.

The storyboard is the plan's beats with their picks in order (dropped ones included),
each with its stable ``ref``. An op changes the storyboard, never a position: the draft
is timed by ``resolve`` like any edit (invariant 5), with no AI call. Saving makes an
immutable ``user`` version and clears the draft; so does starting a render of the draft.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Annotated, Any, Literal, get_args

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, model_validator
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from mosaic.ai.prompts.planner.schema_v2 import Beat as PlanBeat
from mosaic.ai.prompts.planner.schema_v2 import Output as PlanOut
from mosaic.ai.prompts.selector.schema_v2 import Length
from mosaic.core.clock import now_iso
from mosaic.core.keys import artifact_key
from mosaic.editing import solver
from mosaic.editing.request import Category, EditRequest, Weight
from mosaic.editing.resolve import EditInputs, Resolved, rejected_segments, resolve
from mosaic.editing.retrieval import Candidate, parse_ref
from mosaic.storage import provenance
from mosaic.storage.models_project import Edit, EditDraftOp, EditVersion


class DraftError(ValueError):
    """An op that does not fit the storyboard (unknown shot, a locked shot changed)."""


class UnknownBeatError(DraftError, LookupError):
    """No beat with that id in the edit."""


# ------------------------------------------------------------------- storyboard


class SourceTime(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ticks: int = Field(ge=0)
    tb: str


class TimelineTime(BaseModel):
    model_config = ConfigDict(extra="forbid")

    frames: int = Field(ge=1)
    rate: str


class Pin(BaseModel):
    """A locked shot's exact cut (ADR 0068): which segment, its source range in the
    source's time base and its length at the timeline rate (invariant 3)."""

    model_config = ConfigDict(extra="forbid")

    segment_id: str
    source_in: SourceTime
    source_out: SourceTime
    duration: TimelineTime

    @model_validator(mode="after")
    def _range(self) -> Pin:
        if self.source_out.tb != self.source_in.tb:
            raise ValueError("a pin's in and out share one time base")
        still = self.source_in.tb == "1/1" and self.source_in.ticks == 0  # ADR 0075
        if self.source_out.ticks < self.source_in.ticks or (
            self.source_out.ticks == self.source_in.ticks and not still
        ):
            raise ValueError("a pin's out point is after its in point")
        return self


class BoardShot(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ref: str
    segment_id: str
    role: str
    priority: int
    length: str
    audio_intent: str
    reason: str
    alternatives: list[dict[str, str]] = Field(default_factory=list)
    locked: bool = False
    pin: Pin | None = None
    # Part of another shot's locked cut (two segments of one take, cut as one).
    absorbed_by: str | None = None


class BoardBeat(BaseModel):
    model_config = ConfigDict(extra="forbid")

    beat_id: str
    title: str
    intent: str
    share_percent: int
    pool: list[str]
    shots: list[BoardShot]


class Board(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str
    beats: list[BoardBeat]
    user_order: bool = False  # the owner rearranged it: its order, not the chronology's
    # Segments the owner took out (removed or replaced): never brought back as a spare.
    excluded: list[str] = Field(default_factory=list)
    duration_s: int | None = None  # the length asked for, when the owner changed it (M4.4b)
    # Content weights the owner changed since the base version (M4.4c): neutral resets.
    weight_changes: dict[Category, Weight] = Field(default_factory=dict)

    def exclude(self, segment_id: str) -> None:
        self.excluded = sorted({*self.excluded, segment_id})

    def shot(self, ref: str) -> tuple[BoardBeat, int, BoardShot]:
        for beat in self.beats:
            for i, sh in enumerate(beat.shots):
                if sh.ref == ref:
                    return beat, i, sh
        raise DraftError(f"no shot {ref!r} in this edit")

    def beat(self, beat_id: str) -> tuple[int, BoardBeat]:
        for i, beat in enumerate(self.beats):
            if beat.beat_id == beat_id:
                return i, beat
        raise UnknownBeatError(f"no beat {beat_id!r} in this edit")

    def segments(self) -> set[str]:
        return {sh.segment_id for b in self.beats for sh in b.shots}


def board_of(v: EditVersion) -> Board:
    """A version's storyboard. Versions from M4 on store it with their beats; older ones
    are rebuilt from their selections (the selector's picks, in its order)."""
    timeline = v.timeline
    locked = {
        ref
        for e in timeline["tracks"][0]["events"]
        if e["origin"].get("locked")
        for ref in (e["origin"]["selection_ref"], *e["origin"].get("merged", []))
    }
    beats = []
    for b in v.beats:
        if "shots" in b:
            shots = [BoardShot.model_validate(sh) for sh in b["shots"]]
        else:
            picks = [
                (ref, sel)
                for ref, sel in timeline["selections"].items()
                if sel["beat_id"] == b["beat_id"] and sel.get("alternative_to") is None
            ]
            picks.sort(key=lambda p: int(p[0].rsplit("#", 1)[1]))
            shots = [
                BoardShot(
                    ref=ref,
                    segment_id=sel["segment_id"],
                    role=sel["role"],
                    priority=sel["priority"],
                    length=sel["length"],
                    audio_intent=sel["audio_intent"],
                    reason=sel["reason"],
                    alternatives=sel.get("alternatives", []),
                    locked=ref in locked,
                )
                for ref, sel in picks
            ]
        beats.append(
            BoardBeat(
                beat_id=b["beat_id"],
                title=b["title"],
                intent=b["intent"],
                share_percent=b["share_percent"],
                pool=b["pool"],
                shots=shots,
            )
        )
    return Board(
        title=timeline.get("title") or "Edit",
        beats=beats,
        user_order=timeline.get("order") == "user",
        excluded=timeline.get("excluded", []),
    )


# --------------------------------------------------------------------------- ops


class MoveShot(BaseModel):
    """Move a shot to ``index`` in ``beat_id`` (its own beat or another)."""

    model_config = ConfigDict(extra="forbid")
    kind: Literal["move_shot"] = "move_shot"
    ref: str
    beat_id: str
    index: int = Field(ge=0)


class MoveBeat(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: Literal["move_beat"] = "move_beat"
    beat_id: str
    index: int = Field(ge=0)


class RemoveShot(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: Literal["remove_shot"] = "remove_shot"
    ref: str


class LockShot(BaseModel):
    """Lock (or unlock) a shot: a hard constraint on every later change (invariant 10).
    The server fills ``pin`` (the shot's cut as the draft times it now) and ``absorb``
    (picks cut together with it) when it records the op (ADR 0068)."""

    model_config = ConfigDict(extra="forbid")
    kind: Literal["lock_shot"] = "lock_shot"
    ref: str
    locked: bool = True
    pin: Pin | None = None
    absorb: list[str] = Field(default_factory=list)


class SetDuration(BaseModel):
    """A new length for the edit ("Make it 90 seconds"): the storyboard is re-timed to it
    with no AI call (PRODUCT.md §8; ADR 0071)."""

    model_config = ConfigDict(extra="forbid")
    kind: Literal["set_duration"] = "set_duration"
    duration_s: int = Field(ge=5, le=4 * 3600)


class SetWeight(BaseModel):
    """More or less of a content category (PRODUCT.md §8; ADR 0074): the request's weight
    for it, from the next timing or regeneration on."""

    model_config = ConfigDict(extra="forbid")
    kind: Literal["set_weight"] = "set_weight"
    category: Category
    weight: Weight


class PaceBeat(BaseModel):
    """Make a beat faster (shorter shots) or slower (longer ones): every free shot's
    length moves one step; locked shots keep their cut."""

    model_config = ConfigDict(extra="forbid")
    kind: Literal["pace_beat"] = "pace_beat"
    beat_id: str
    faster: bool = True


LENGTHS: tuple[str, ...] = get_args(Length)  # short → hold, the selector's length classes


class ReplaceShot(BaseModel):
    """Replace a shot's segment with one of its alternatives or its beat's pool."""

    model_config = ConfigDict(extra="forbid")
    kind: Literal["replace_shot"] = "replace_shot"
    ref: str
    segment_id: str


Op = Annotated[
    MoveShot | MoveBeat | RemoveShot | LockShot | ReplaceShot | SetDuration | PaceBeat | SetWeight,
    Field(discriminator="kind"),
]
OP: TypeAdapter[Op] = TypeAdapter(Op)


def apply(board: Board, op: Op) -> Board:
    """The storyboard after ``op``; ``board`` is left as it was."""
    out = board.model_copy(deep=True)
    if isinstance(op, MoveShot):
        beat, i, sh = out.shot(op.ref)
        if sh.absorbed_by:
            raise DraftError(f"this shot is part of {sh.absorbed_by}: move that one")
        _, target = out.beat(op.beat_id)
        beat.shots.pop(i)
        target.shots.insert(min(op.index, len(target.shots)), sh)
        out.user_order = True
    elif isinstance(op, MoveBeat):
        i, beat = out.beat(op.beat_id)
        out.beats.pop(i)
        out.beats.insert(min(op.index, len(out.beats)), beat)
        out.user_order = True
    elif isinstance(op, RemoveShot):
        beat, i, sh = out.shot(op.ref)
        if sh.locked or sh.absorbed_by:
            raise DraftError("this shot is locked: unlock it to remove it")
        beat.shots.pop(i)
        out.exclude(sh.segment_id)
    elif isinstance(op, SetDuration):
        out.duration_s = op.duration_s
    elif isinstance(op, SetWeight):
        out.weight_changes = {**out.weight_changes, op.category: op.weight}
    elif isinstance(op, PaceBeat):
        _, beat = out.beat(op.beat_id)
        step = -1 if op.faster else 1
        # Locked cuts are the owner's; dialogue runs to the end of its sentence anyway.
        free = [
            sh
            for sh in beat.shots
            if not (sh.locked or sh.absorbed_by) and sh.audio_intent != "dialogue"
        ]
        if not free:
            raise DraftError(f"{beat.title} has no free shot to pace: they are locked or speech")
        moved = False
        for sh in free:
            i = min(len(LENGTHS) - 1, max(0, LENGTHS.index(sh.length) + step))
            moved |= LENGTHS[i] != sh.length
            sh.length = LENGTHS[i]
        if not moved:
            raise DraftError(
                f"{beat.title} is already as {'fast' if op.faster else 'slow'} as it gets"
            )
    elif isinstance(op, LockShot):
        _, _, sh = out.shot(op.ref)
        if sh.absorbed_by:
            raise DraftError(f"this shot is part of {sh.absorbed_by}: lock or unlock that one")
        if op.locked and op.pin is not None and op.pin.segment_id != sh.segment_id:
            raise DraftError("this shot changed since it was timed; lock it again")
        sh.locked = op.locked
        sh.pin = op.pin if op.locked else None
        for beat in out.beats:
            for other in beat.shots:
                if op.locked and other.ref in op.absorb:
                    other.absorbed_by = op.ref
                elif not op.locked and other.absorbed_by == op.ref:
                    other.absorbed_by = None
    else:
        beat, _, sh = out.shot(op.ref)
        if sh.locked or sh.absorbed_by:
            raise DraftError("this shot is locked: unlock it to replace it")
        offered = {a["segment_id"] for a in sh.alternatives} | set(beat.pool)
        if op.segment_id not in offered:
            raise DraftError(f"{op.segment_id} is not an alternative for this shot")
        if op.segment_id in out.segments():
            raise DraftError(f"{op.segment_id} is already in this edit")
        before = sh.segment_id
        sh.alternatives = [a for a in sh.alternatives if a["segment_id"] != op.segment_id]
        sh.alternatives.insert(0, {"segment_id": before, "why_not": "Replaced by you"})
        sh.segment_id = op.segment_id
        sh.reason = "Chosen by you"
        out.exclude(before)
        out.excluded = [x for x in out.excluded if x != op.segment_id]  # swapped back
    return out


# ------------------------------------------------------------------------- draft


@dataclass(frozen=True)
class Draft:
    base: EditVersion
    board: Board
    ops: list[dict[str, Any]]  # applied, in order
    can_undo: bool
    can_redo: bool

    @property
    def dirty(self) -> bool:
        return bool(self.ops)


def latest(s: Session, edit_id: int) -> EditVersion | None:
    return s.scalar(
        select(EditVersion)
        .where(EditVersion.edit_id == edit_id)
        .order_by(EditVersion.version.desc())
        .limit(1)
    )


def _rows(s: Session, edit_id: int, base: int) -> list[EditDraftOp]:
    return list(
        s.scalars(
            select(EditDraftOp)
            .where(EditDraftOp.edit_id == edit_id, EditDraftOp.base_version == base)
            .order_by(EditDraftOp.seq)
        )
    )


def load(s: Session, edit_id: int) -> Draft:
    """The draft on the latest version. Ops on an older version are stale (a version
    was made since) and no longer count. ``LookupError`` when the edit has no version."""
    base = latest(s, edit_id)
    if base is None:
        raise LookupError("this edit has no versions yet")
    rows = _rows(s, edit_id, base.version)
    board = board_of(base)
    applied = []
    for r in rows:
        if r.undone:
            continue
        board = apply(board, OP.validate_python(r.op))
        applied.append(r.op)
    return Draft(
        base,
        board,
        applied,
        can_undo=bool(applied),
        can_redo=any(r.undone for r in rows),
    )


def add(s: Session, edit_id: int, op: Op) -> None:
    """Apply ``op`` to the draft (``DraftError`` when it does not fit). Redo history and
    stale ops are dropped, as an editor's undo stack does."""
    current = load(s, edit_id)
    apply(current.board, op)  # refuse before writing
    base = current.base.version
    s.execute(
        delete(EditDraftOp).where(
            EditDraftOp.edit_id == edit_id,
            (EditDraftOp.base_version != base) | EditDraftOp.undone.is_(True),
        )
    )
    s.flush()
    seq = (
        s.scalar(select(func.max(EditDraftOp.seq)).where(EditDraftOp.edit_id == edit_id)) or 0
    ) + 1
    s.add(
        EditDraftOp(
            edit_id=edit_id,
            base_version=base,
            seq=seq,
            op=op.model_dump(mode="json"),
            undone=False,
            created_at=now_iso(),
        )
    )


def undo(s: Session, edit_id: int) -> bool:
    base = latest(s, edit_id)
    if base is None:
        return False
    applied = [r for r in _rows(s, edit_id, base.version) if not r.undone]
    if not applied:
        return False
    applied[-1].undone = True
    return True


def redo(s: Session, edit_id: int) -> bool:
    base = latest(s, edit_id)
    if base is None:
        return False
    undone = [r for r in _rows(s, edit_id, base.version) if r.undone]
    if not undone:
        return False
    undone[0].undone = False
    return True


def board_shots(
    board: Board, by_ref: dict[str, Candidate], rate: str
) -> tuple[PlanOut, list[solver.Shot], list[str]]:
    """The storyboard as a plan and solver shots. A pick whose segment is no longer a
    candidate (re-analysed, or rejected by the owner since) is left out, with a note."""
    plan = PlanOut(
        title=board.title,
        beats=[
            PlanBeat(
                beat_id=b.beat_id,
                title=b.title,
                intent=b.intent,
                share_percent=b.share_percent,
                candidates=b.pool,
            )
            for b in board.beats
        ],
    )
    shots: list[solver.Shot] = []
    notes: list[str] = []
    absorbed: list[tuple[str, solver.Shot]] = []
    for bi, b in enumerate(board.beats):
        for oi, sh in enumerate(b.shots):
            cand = by_ref.get(sh.segment_id)
            if cand is None:
                notes.append(f"{sh.segment_id} is no longer available; left out")
                continue
            pin = None
            if sh.pin is not None:
                p = sh.pin
                if (p.segment_id, p.source_in.tb, p.duration.rate) == (
                    sh.segment_id,
                    cand.tb,
                    rate,
                ):
                    pin = (p.source_in.ticks, p.source_out.ticks, p.duration.frames)
                else:  # re-analysed, or another frame rate: kept, cut afresh
                    notes.append(f"{sh.ref}: locked, but its cut no longer applies; re-cut")
            shot = solver.Shot(
                cand=cand,
                beat_id=b.beat_id,
                beat_index=bi,
                order=oi,
                role=sh.role,
                priority=sh.priority,
                length=sh.length,
                audio_intent=(
                    "natural_sound"
                    if sh.audio_intent == "dialogue" and not cand.has_speech
                    else sh.audio_intent
                ),
                reason=sh.reason,
                alternatives=list(sh.alternatives),
                locked=sh.locked,
                ref=sh.ref,
                pin=pin,
            )
            if sh.absorbed_by:
                absorbed.append((sh.absorbed_by, shot))
            else:
                shots.append(shot)
    lockers = {sh.selection_ref: sh for sh in shots}
    for locker_ref, shot in absorbed:
        locker = lockers.get(locker_ref)
        if locker is not None and locker.pin is not None:
            locker.absorbed.append(shot)  # timed as part of the locked cut
        else:  # its locked shot is gone or no longer pinned: timed on its own
            notes.append(f"{shot.selection_ref}: no longer part of {locker_ref}")
            shots.append(shot)
    shots.sort(key=lambda sh: (sh.beat_index, sh.order))
    return plan, shots, notes


def request_of(req: EditRequest, board: Board) -> EditRequest:
    """The request the storyboard is timed to: its own length and content weights, where
    the owner changed them since the base version."""
    update: dict[str, Any] = {}
    if board.duration_s is not None and board.duration_s != req.duration_s:
        update["duration_s"] = board.duration_s
    if board.weight_changes:
        update["weights"] = {**req.weights, **board.weight_changes}
    if not update:
        return req
    return EditRequest.model_validate({**req.model_dump(mode="json"), **update})


def inputs(s: Session, d: Draft) -> tuple[EditRequest, EditInputs]:
    """The request the draft is timed to (its own length) and the candidates for it: one
    candidate set for timing, saving and reloading, since retrieval depends on the
    length (ADR 0071)."""
    from mosaic.editing.generate import edit_inputs

    req = request_of(EditRequest.model_validate(d.base.request), d.board)
    return req, edit_inputs(s, req, locked_segments(d.board))


def locked_segments(board: Board) -> frozenset[int]:
    """The segment ids of the storyboard's locked shots and the picks absorbed into them:
    they stay candidates whatever the content weights say (invariant 10)."""
    ids = (
        parse_ref(sh.segment_id)
        for b in board.beats
        for sh in b.shots
        if sh.locked or sh.absorbed_by
    )
    return frozenset(i for i in ids if i is not None)


def timed(
    s: Session,
    req: EditRequest,
    inp: EditInputs,
    board: Board,
    rejected: set[int] | None = None,
) -> Resolved:
    """The storyboard timed like any edit (``resolve``), with no AI call, to its own
    length when the owner changed it."""
    req = request_of(req, board)
    plan, shots, notes = board_shots(board, {c.ref: c for c in inp.cands}, inp.rate)
    done = resolve(
        s,
        req,
        inp,
        plan,
        shots,
        rejected_segments(s) if rejected is None else rejected,
        user_order=board.user_order,
        excluded=set(board.excluded),
    )
    done.metrics["solver"]["notes"] = notes + done.metrics["solver"]["notes"]
    # The version keeps the whole storyboard, absorbed picks included.
    shots_by_beat = {b.beat_id: b.shots for b in board.beats}
    for b in done.beats:
        b["shots"] = [sh.model_dump(mode="json") for sh in shots_by_beat.get(b["beat_id"], [])]
    if board.excluded:
        done.timeline["excluded"] = list(board.excluded)
    return done


def _digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


def pinned(op: LockShot, done: Resolved, board: Board) -> LockShot:
    """``op`` with the pin the shot has in ``done`` (``board`` timed now): its event's
    source range and frames, and the picks the refiner cut together with it."""
    if not op.locked:
        return op.model_copy(update={"pin": None, "absorb": []})
    _, _, sh = board.shot(op.ref)
    rate = done.timeline["rate"]
    for e in done.timeline["tracks"][0]["events"]:
        refs = [e["origin"]["selection_ref"], *e["origin"].get("merged", [])]
        if op.ref in refs:
            pin = Pin(
                segment_id=sh.segment_id,
                source_in=SourceTime.model_validate(e["source_in"]),
                source_out=SourceTime.model_validate(e["source_out"]),
                duration=TimelineTime(
                    frames=e["timeline_out"]["frames"] - e["timeline_in"]["frames"], rate=rate
                ),
            )
            return op.model_copy(update={"pin": pin, "absorb": [r for r in refs if r != op.ref]})
    # Not in the edit now (dropped to fit): locked, so the solver keeps it, but not pinned.
    return op.model_copy(update={"pin": None, "absorb": []})


def draft_key(
    project_id: str,
    base: EditVersion,
    ops: list[dict[str, Any]],
    inp: EditInputs,
    rejected: set[int],
) -> str:
    """The key of the version a draft saves as: everything its timing depends on
    (invariant 9) - the base, the ops, the candidates, the rate, the rejections and the
    algorithm version."""
    from mosaic.editing.generate import EDIT_VERSION

    return artifact_key(
        "edit.draft",
        project_id=project_id,
        inputs={
            "base": base.key,
            "ops": _digest(ops),
            "candidates": inp.digest,
            "rate": inp.rate,
            "rejected": _digest(sorted(rejected)),
        },
        version=f"draft/1+{EDIT_VERSION}",
    )


@dataclass(frozen=True)
class Timed:
    """A draft timed for saving, read outside the writer."""

    draft: Draft
    done: Resolved
    key: str


class DraftChangedError(RuntimeError):
    """The draft changed between timing it and saving it."""


def time_for_save(s: Session, project_id: str, edit_id: int, inp: EditInputs) -> Timed | None:
    """The draft timed for a save (None when it has no changes). ``inp``: the edit's
    inputs, read in this session."""
    d = load(s, edit_id)
    if not d.dirty:
        return None
    req = EditRequest.model_validate(d.base.request)
    rejected = rejected_segments(s)
    done = timed(s, req, inp, d.board, rejected)
    return Timed(d, done, draft_key(project_id, d.base, d.ops, inp, rejected))


def commit(
    s: Session,
    edit_id: int,
    t: Timed,
    *,
    creator: str = "user",
    reason: str = "Saved from the storyboard",
    extra_metrics: dict[str, Any] | None = None,
    input_keys: list[str] | None = None,
) -> EditVersion:
    """``t`` as a new immutable version; the draft then starts again from it. Refused
    (``DraftChangedError``) when a version or op came in since ``t`` was timed.
    ``extra_metrics`` and ``input_keys`` add to the version's metrics and provenance."""
    from mosaic.editing.generate import EDIT_VERSION

    now = load(s, edit_id)
    if now.base.version != t.draft.base.version or now.ops != t.draft.ops:
        raise DraftChangedError("the draft changed while it was being saved; try again")
    d, done = t.draft, t.done
    prov = provenance.record(
        s,
        provenance.ProvenanceInfo(
            kind="edit",
            algorithm_version=EDIT_VERSION,
            input_keys=[d.base.key, t.key, *(input_keys or [])],
        ),
    )
    metrics = (
        done.metrics
        | {
            "preliminary": d.base.metrics.get("preliminary", False),
            "draft": {"base_version": d.base.version, "ops": len(d.ops)},
        }
        | (extra_metrics or {})
    )
    row = EditVersion(
        edit_id=edit_id,
        version=d.base.version + 1,
        parent_version=d.base.version,
        creator=creator,
        reason=reason,
        key=t.key,
        request=request_of(EditRequest.model_validate(d.base.request), t.draft.board).model_dump(
            mode="json"
        ),
        rate=d.base.rate,
        beats=done.beats,
        timeline=done.timeline,
        metrics=metrics,
        findings=[f.as_json() for f in done.findings],
        provenance_id=prov,
        created_at=now_iso(),
    )
    s.add(row)
    edit = s.get(Edit, edit_id)
    if edit is not None and edit.request.get("duration_s") != row.request["duration_s"]:
        # The edit's request is its current one: a later regeneration keeps the length,
        # and a default name follows it (ADR 0071).
        old_s, new_s = edit.request.get("duration_s"), row.request["duration_s"]
        if edit.name.endswith(f" · {old_s} s"):
            edit.name = f"{edit.name[: -len(f' · {old_s} s')]} · {new_s} s"
        edit.request = {**edit.request, "duration_s": new_s}
    if edit is not None and edit.request.get("weights", {}) != row.request.get("weights", {}):
        edit.request = {**edit.request, "weights": row.request.get("weights", {})}  # ADR 0074
    s.execute(delete(EditDraftOp).where(EditDraftOp.edit_id == edit_id))
    s.flush()
    return row


def as_json(d: Draft, done: Resolved) -> dict[str, Any]:
    """The draft for S16: its storyboard, undo state and how it times now."""
    return {
        "base_version": d.base.version,
        "dirty": d.dirty,
        "ops": len(d.ops),
        "can_undo": d.can_undo,
        "can_redo": d.can_redo,
        "board": d.board.model_dump(mode="json"),
        "duration": done.timeline["duration"],
        "target": {
            "frames": done.metrics.get("target_frames"),
            "rate": done.timeline["rate"],
        },
        "timeline": done.timeline,
        "metrics": done.metrics,
        "findings": [f.as_json() for f in done.findings],
    }


__all__ = [
    "OP",
    "Board",
    "Draft",
    "DraftError",
    "Op",
    "add",
    "apply",
    "as_json",
    "board_of",
    "commit",
    "load",
    "redo",
    "time_for_save",
    "timed",
    "undo",
]
