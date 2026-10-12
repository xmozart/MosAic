"""Comparing and reverting versions (S18; M4 "version compare (event list diff and
side-by-side preview), and revert"; ADR 0083).

A revert never changes history: it makes a new version equal to the chosen one - the same
timeline, beats, request and key - so its render reuses every chunk and, when an
identical render exists, the whole file (M4 acceptance 5). A compare lists what changed
between two versions' shots, matched by their storyboard refs, which stay with a shot
across versions.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from mosaic.core.clock import now_iso
from mosaic.editing import draft, findings
from mosaic.editing.service import source_file
from mosaic.editing.titles import shot_events
from mosaic.storage import provenance
from mosaic.storage.models_project import Edit, EditDraftOp, EditVersion
from mosaic.storage.projects import Project


class RevertError(ValueError):
    """Nothing to revert (the version is already the latest); the message is for the owner."""


def _version(s: Session, edit_id: int, version: int) -> EditVersion:
    row = s.scalar(
        select(EditVersion).where(EditVersion.edit_id == edit_id, EditVersion.version == version)
    )
    if row is None:
        raise LookupError(f"no version {version}")
    return row


def revert(project: Project, edit_id: int, version: int) -> int:
    """A new version equal to ``version``; the storyboard's unsaved changes are dropped
    (they were on the version being left)."""
    from mosaic.editing.generate import export_path, version_json, write_export

    with project.write() as s:
        target = _version(s, edit_id, version)
        latest = draft.latest(s, edit_id)
        assert latest is not None
        if latest.version == target.version:
            raise RevertError(f"v{version} is already the latest version")
        prov = provenance.record(
            s,
            provenance.ProvenanceInfo(
                kind="edit", algorithm_version="revert/1", input_keys=[target.key]
            ),
        )
        row = EditVersion(
            edit_id=edit_id,
            version=latest.version + 1,
            parent_version=latest.version,
            creator="user",
            reason=f"Reverted to v{target.version}",
            key=target.key,
            request=target.request,
            rate=target.rate,
            beats=target.beats,
            timeline=target.timeline,
            metrics=target.metrics | {"reverted_from": target.version},
            findings=target.findings,
            provenance_id=prov,
            created_at=now_iso(),
        )
        s.add(row)
        s.execute(delete(EditDraftOp).where(EditDraftOp.edit_id == edit_id))
        s.flush()
        findings.record(s, row)
        edit = s.get(Edit, edit_id)
        assert edit is not None
        draft.follow(edit, row)
        number, payload = row.version, version_json(edit, row)
    write_export(export_path(project.workspace, edit_id, number), payload)
    project.checkpoint()  # snapshots follow edit commits (ARCHITECTURE.md §4)
    return number


def _shots(v: EditVersion) -> list[dict[str, Any]]:
    return shot_events(v.timeline["tracks"][0]["events"])


def _common_order(a: list[str], b: list[str]) -> set[str]:
    """The refs in the longest run of ``a``'s order that ``b`` keeps (LCS)."""
    n, m = len(a), len(b)
    table = [[0] * (m + 1) for _ in range(n + 1)]
    for i in range(n - 1, -1, -1):
        for j in range(m - 1, -1, -1):
            table[i][j] = (
                table[i + 1][j + 1] + 1 if a[i] == b[j] else max(table[i + 1][j], table[i][j + 1])
            )
    keep: set[str] = set()
    i = j = 0
    while i < n and j < m:
        if a[i] == b[j]:
            keep.add(a[i])
            i, j = i + 1, j + 1
        elif table[i + 1][j] >= table[i][j + 1]:
            i += 1
        else:
            j += 1
    return keep


def compare(project: Project, edit_id: int, a: int, b: int) -> dict[str, Any]:
    """What changed from version ``a`` to ``b``, in ``b``'s order then the removed ones:
    ``replaced`` (another clip in the shot's place), ``trimmed`` (the same clip, another
    range or length), ``moved`` (out of the order the two share), ``added``, ``removed``.
    Each change has the shot's ref, both events, the timeline frame it is at and whether
    it moved (a replaced or trimmed shot may have moved too)."""
    with project.db.session() as s:
        va, vb = _version(s, edit_id, a), _version(s, edit_id, b)
        sa, sb = _shots(va), _shots(vb)
        changes = diff(sa, sb, a, b)
        _describe(s, changes, va, vb)
    return {
        "a": a,
        "b": b,
        "duration_a": va.timeline["duration"],
        "duration_b": vb.timeline["duration"],
        "changes": changes,
        "same": not changes and va.timeline == vb.timeline,
    }


def _describe(s: Session, changes: list[dict[str, Any]], va: EditVersion, vb: EditVersion) -> None:
    """S18's words for each change: the clip's file name, its length and its beat's title
    in each version (display only; the frames are exact)."""

    for side, v in (("a", va), ("b", vb)):
        events = {e["event_id"]: e for e in v.timeline["tracks"][0]["events"]}
        titles = {b["beat_id"]: b["title"] for b in v.beats}
        for c in changes:
            e = events.get(c[f"event_{side}"]) if c[f"event_{side}"] else None
            path = (
                source_file(
                    s, int(str(e["asset_id"]).removeprefix("ast_")), e["source_in"]["ticks"]
                )
                if e and e.get("asset_id")
                else None
            )
            c[f"file_{side}"] = path.rsplit("/", 1)[-1] if path else None
            c[f"frames_{side}"] = (
                e["timeline_out"]["frames"] - e["timeline_in"]["frames"] if e else None
            )
            c[f"beat_{side}"] = titles.get(e.get("beat_id")) if e else None


def diff(
    sa: list[dict[str, Any]], sb: list[dict[str, Any]], a: int, b: int
) -> list[dict[str, Any]]:
    """The shot-level changes from events ``sa`` (version ``a``) to ``sb`` (``b``)."""
    ref_a = {e["origin"]["selection_ref"]: e for e in sa}
    ref_b = {e["origin"]["selection_ref"]: e for e in sb}
    common = [r for r in (e["origin"]["selection_ref"] for e in sa) if r in ref_b]
    kept_order = _common_order(common, [r for r in ref_b if r in ref_a])
    moved = {r for r in common if r not in kept_order}
    changes: list[dict[str, Any]] = []

    def change(kind: str, ref: str, ea: dict[str, Any] | None, eb: dict[str, Any] | None) -> None:
        at = (eb or ea or {})["timeline_in"]["frames"]
        changes.append(
            {
                "kind": kind,
                "ref": ref,
                "event_a": ea["event_id"] if ea else None,
                "event_b": eb["event_id"] if eb else None,
                "segment_a": ea["segment_id"] if ea else None,
                "segment_b": eb["segment_id"] if eb else None,
                "frame": at,
                "in_version": b if eb else a,
                # Out of the order the two versions share (also for a replaced or trimmed
                # shot): which of two swapped shots "moved" is the longest common order's
                # choice.
                "moved": ref in moved,
            }
        )

    for eb in sb:
        ref = eb["origin"]["selection_ref"]
        ea = ref_a.get(ref)
        if ea is None:
            change("added", ref, None, eb)
        elif ea["segment_id"] != eb["segment_id"]:
            change("replaced", ref, ea, eb)
        elif (ea["source_in"], ea["source_out"]) != (eb["source_in"], eb["source_out"]):
            change("trimmed", ref, ea, eb)
        elif ref in moved:
            change("moved", ref, ea, eb)
    for ea in sa:
        if ea["origin"]["selection_ref"] not in ref_b:
            change("removed", ea["origin"]["selection_ref"], ea, None)
    return changes
