"""Generating an edit in tests (shared by the edit and clip-detail tests)."""

from __future__ import annotations

from mosaic.editing.request import EditRequest
from mosaic.editing.service import create_edit, submit_generate
from mosaic.jobs.executor import LocalExecutor
from mosaic.jobs.store import JobStore
from mosaic.storage.control import ControlDB
from mosaic.storage.projects import Project
from tests.support.runner import run_job


def generate(project: Project, control: ControlDB, request: EditRequest) -> int:
    edit_id = create_edit(project, request, control, control.local_principal)
    job = submit_generate(
        LocalExecutor(JobStore(control.db)), control.local_principal, project, edit_id
    )
    assert run_job(control, job, timeout=600) == "done"
    return edit_id
