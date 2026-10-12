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


def as_json(f: EditFinding, fix: str | None = None) -> dict[str, Any]:
    """A finding for S17; ``fix``: its suggested fix in words (``fix_text``)."""
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
        "fix": fix,
        "status": f.status,
        "applied_in_version": f.applied_in_version,
    }


def fix_text(s: Session, ops: list[Any] | None) -> str | None:
    """A finding's fix in the owner's words (S17's "suggested fix"): "Replace it with
    DSC_0932.MOV", "Remove it". None when it has nothing to apply."""
    from mosaic.editing.retrieval import parse_ref
    from mosaic.editing.service import source_file
    from mosaic.storage.models_project import Segment

    words: list[str] = []
    for op in ops or []:
        kind = op.get("kind")
        if kind == "replace_shot":
            sid = parse_ref(str(op.get("segment_id", "")))
            seg = s.get(Segment, sid) if sid is not None else None
            path = source_file(s, seg.asset_id, seg.usable_start_ticks) if seg else None
            words.append(f"Replace it with {path.rsplit('/', 1)[-1]}" if path else "Replace it")
        elif kind == "remove_shot":
            words.append("Remove it")
        elif kind == "pace_beat":
            words.append("Make the beat faster" if op.get("faster", True) else "Slow the beat")
        else:
            words.append("Change the storyboard")
    return "; ".join(dict.fromkeys(words)) or None


ISSUES = ("blocking", "warning")  # S17 "Issue"; info is a "Suggestion"


def beats_with_issues(s: Session, row: EditVersion) -> list[str]:
    """The beats (in story order) holding an open issue that has no fix on version
    ``row``: what "Regenerate with fixes" regenerates (ADR 0089)."""
    beat_of = {
        e["event_id"]: e.get("beat_id")
        for e in row.timeline["tracks"][0]["events"]
        if e.get("beat_id")
    }
    hit = {
        beat_of[f.event_id]
        for f in of_version(s, row.edit_id, row.version)
        if f.status == "open" and not f.ops and f.severity in ISSUES and f.event_id in beat_of
    }
    return [str(b["beat_id"]) for b in row.beats if b["beat_id"] in hit]


def of_version(s: Session, edit_id: int, version: int) -> list[EditFinding]:
    return list(
        s.scalars(
            select(EditFinding)
            .where(EditFinding.edit_id == edit_id, EditFinding.version == version)
            .order_by(EditFinding.seq)
        )
    )


def applied_in(s: Session, edit_id: int, version: int) -> list[EditFinding]:
    """Findings of earlier versions whose fix made ``version`` (S17's "Applied in vN")."""
    return list(
        s.scalars(
            select(EditFinding)
            .where(EditFinding.edit_id == edit_id, EditFinding.applied_in_version == version)
            .order_by(EditFinding.version, EditFinding.seq)
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
