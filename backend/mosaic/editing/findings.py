"""Findings on an edit's versions (PRODUCT.md §7 step 9, S17; ADR 0081).

Every version's critic findings (deterministic, and the AI critic's after a generation)
are recorded as rows when the version is made. A finding about a shot carries the
storyboard ops that fix it. Applying findings adds their ops to the draft and saves it
as a child version; ignoring one only marks it. The owner's draft must be clean first:
a fix is never folded into changes the owner has not saved.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from mosaic.core.clock import now_iso
from mosaic.core.ids import new_ulid
from mosaic.storage.models_project import EditFinding, EditVersion
from mosaic.storage.projects import Project


class FindingError(ValueError):
    """A finding that cannot be applied or ignored now; the message is for the owner."""


class FindingStateError(FindingError):
    """The edit moved on (a newer version or unsaved draft changes): 409."""


def record(s: Session, row: EditVersion) -> None:
    """Rows for ``row``'s findings (its ``findings`` JSON), in their order."""
    for i, f in enumerate(row.findings or []):
        s.add(
            EditFinding(
                uid=new_ulid(),
                edit_id=row.edit_id,
                version=row.version,
                seq=i,
                source=f.get("source", "critic"),
                code=f["code"],
                severity=f["severity"],
                frame=int(f["frame"]),
                event_id=f.get("event_id"),
                text=str(f["text"])[:500],
                ops=f.get("ops") or None,
                status="open",
                applied_in_version=None,
                created_at=now_iso(),
            )
        )


def as_json(f: EditFinding) -> dict[str, Any]:
    return {
        "finding_id": f.uid,
        "version": f.version,
        "source": f.source,
        "code": f.code,
        "severity": f.severity,
        "frame": f.frame,
        "event_id": f.event_id,
        "text": f.text,
        "can_apply": bool(f.ops),
        "status": f.status,
        "applied_in_version": f.applied_in_version,
    }


def of_version(s: Session, edit_id: int, version: int) -> list[EditFinding]:
    return list(
        s.scalars(
            select(EditFinding)
            .where(EditFinding.edit_id == edit_id, EditFinding.version == version)
            .order_by(EditFinding.seq)
        )
    )


def _rows(s: Session, edit_id: int, uids: list[str]) -> list[EditFinding]:
    rows = list(
        s.scalars(
            select(EditFinding).where(EditFinding.edit_id == edit_id, EditFinding.uid.in_(uids))
        )
    )
    if len(rows) != len(set(uids)):
        raise LookupError("no such finding")
    return sorted(rows, key=lambda f: f.seq)


def ignore(project: Project, edit_id: int, uids: list[str]) -> int:
    """Mark open findings ignored; returns how many changed."""
    with project.write() as s:
        rows = _rows(s, edit_id, uids)
        changed = 0
        for f in rows:
            if f.status == "open":
                f.status = "ignored"
                changed += 1
        return changed


def apply(project: Project, edit_id: int, uids: list[str]) -> tuple[int, list[str]]:
    """Apply the open findings ``uids`` (of the latest version) as one child version.
    Returns the new version and the findings that could not be applied (their shot
    changed or is locked now).

    Atomic: the fixed storyboard is timed outside the writer, then one write transaction
    checks the draft is still clean, adds the ops, commits the version and marks the
    findings applied - a failure leaves the draft and the findings as they were."""
    from mosaic.editing import draft
    from mosaic.editing.generate import export_path, version_json, write_export
    from mosaic.editing.request import EditRequest
    from mosaic.editing.resolve import rejected_segments
    from mosaic.storage.models_project import Edit

    with project.db.session() as s:
        rows = _rows(s, edit_id, uids)
        latest = draft.latest(s, edit_id)
        if latest is None:
            raise LookupError("this edit has no version yet")
        if any(f.version != latest.version for f in rows):
            raise FindingStateError("These findings are about an older version.")
        d = draft.load(s, edit_id)
        if d.dirty:
            raise FindingStateError("Save or discard your storyboard changes first.")
        board = d.board
        todo: list[tuple[str, str, list[Any]]] = []  # (uid, code, ops)
        skipped: list[str] = []
        for f in rows:
            if f.status != "open" or not f.ops:
                skipped.append(f.uid)
                continue
            try:  # all of a finding's ops apply, or none of them
                ops = [draft.OP.validate_python(op) for op in f.ops]
                trial = board
                for op in ops:
                    trial = draft.apply(trial, op)
            except (draft.DraftError, LookupError, ValueError):
                skipped.append(f.uid)
                continue
            board = trial
            todo.append((f.uid, f.code, ops))
        if not todo:
            raise FindingError("None of these findings can be applied now.")
        ops_json = [op.model_dump(mode="json") for _, _, ops in todo for op in ops]
        fixed = draft.Draft(d.base, board, ops_json, can_undo=True, can_redo=False)
        _, inp = draft.inputs(s, fixed)
        rejected = rejected_segments(s)
        done = draft.timed(s, EditRequest.model_validate(d.base.request), inp, board, rejected)
        timed = draft.Timed(
            fixed, done, draft.draft_key(project.id, d.base, ops_json, inp, rejected)
        )
    codes = sorted({code.replace("_", " ") for _, code, _ in todo})
    with project.write() as s:
        now = draft.load(s, edit_id)
        if now.base.version != d.base.version or now.dirty:
            raise FindingStateError("The storyboard changed; try again.")
        for _, _, ops in todo:
            for op in ops:
                draft.add(s, edit_id, op)
        row = draft.commit(
            s, edit_id, timed, creator="user", reason=("Applied: " + ", ".join(codes))[:200]
        )
        for f in _rows(s, edit_id, [uid for uid, _, _ in todo]):
            f.status = "applied"
            f.applied_in_version = row.version
        edit = s.get(Edit, edit_id)
        assert edit is not None
        version, payload = row.version, version_json(edit, row)
    write_export(export_path(project.workspace, edit_id, version), payload)
    project.checkpoint()  # snapshots follow edit commits (ARCHITECTURE.md §4)
    return version, skipped
