"""Devices: clock offsets and LUTs (docs/ui/API_MAP.md; S6, S21; ADR 0027).

Changing an offset rewrites corrected capture times at once, so day grouping follows
immediately. A small job then rebuilds captures and summaries; no analysis is redone.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field, model_validator

from mosaic.app.deps import principal, services
from mosaic.app.routers.edits import _project
from mosaic.app.services import Services
from mosaic.core.principal import Principal, check
from mosaic.library.devices import device_rows, set_offset, submit_time_refresh
from mosaic.storage.models_project import Device, DeviceSuggestion

router = APIRouter(prefix="/api")
Svc = Depends(services)
Me = Depends(principal)

MAX_OFFSET_MS = 7 * 24 * 3600 * 1000


class DeviceChange(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: int
    clock_offset_ms: int | None = Field(default=None, ge=-MAX_OFFSET_MS, le=MAX_OFFSET_MS)
    accept_suggestion: bool = False

    @model_validator(mode="after")
    def _one(self) -> DeviceChange:
        if (self.clock_offset_ms is not None) == self.accept_suggestion:
            raise ValueError("give exactly one of clock_offset_ms or accept_suggestion")
        return self


class DevicesBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    devices: list[DeviceChange] = Field(max_length=500)


@router.get("/projects/{pid}/devices")
def get_devices(pid: str, svc: Services = Svc, me: Principal = Me) -> dict[str, Any]:
    check(me, "devices.read", pid)
    with _project(svc, me, pid) as project, project.db.session() as s:
        return {"devices": device_rows(s)}


@router.get("/projects/{pid}/devices/suggestions")
def get_suggestions(pid: str, svc: Services = Svc, me: Principal = Me) -> dict[str, Any]:
    check(me, "devices.read", pid)
    with _project(svc, me, pid) as project, project.db.session() as s:
        rows = device_rows(s)
    return {"suggestions": [r for r in rows if r["suggestion"] is not None]}


@router.put("/projects/{pid}/devices")
def put_devices(
    pid: str, body: DevicesBody, svc: Services = Svc, me: Principal = Me
) -> dict[str, Any]:
    check(me, "devices.write", pid)
    with _project(svc, me, pid, write=True) as project:
        changed = 0
        with project.write() as s:
            for ch in body.devices:
                if s.get(Device, ch.id) is None:
                    raise HTTPException(404, f"no device {ch.id}")
                if ch.accept_suggestion:
                    sg = s.get(DeviceSuggestion, ch.id)
                    if sg is None:
                        raise HTTPException(409, f"device {ch.id} has no suggestion")
                    changed += set_offset(s, ch.id, sg.offset_ms, "accepted", sg.utc_offset_min)
                elif ch.clock_offset_ms is not None:
                    changed += set_offset(s, ch.id, ch.clock_offset_ms, "user")
        job = submit_time_refresh(svc.executor, me, project) if changed else None
        with project.db.session() as s:
            rows = device_rows(s)
    return {"devices": rows, "assets_updated": changed, "refresh_job": job}
