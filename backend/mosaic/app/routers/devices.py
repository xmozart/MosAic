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
from mosaic.library.devices import device_rows, set_lut, set_offset, submit_time_refresh
from mosaic.media.lut import LutError
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
    lut_path: str | None = Field(default=None, min_length=1, max_length=4096)
    clear_lut: bool = False

    @model_validator(mode="after")
    def _one(self) -> DeviceChange:
        actions = [
            self.clock_offset_ms is not None,
            self.accept_suggestion,
            self.lut_path is not None,
            self.clear_lut,
        ]
        if sum(actions) != 1:
            raise ValueError(
                "give exactly one of clock_offset_ms, accept_suggestion, lut_path or clear_lut"
            )
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
        with project.db.session() as s:
            missing = [ch.id for ch in body.devices if s.get(Device, ch.id) is None]
        if missing:
            raise HTTPException(404, f"no device {missing[0]}")  # before any change
        changed = 0
        luts = 0
        for ch in body.devices:
            if ch.lut_path is None and not ch.clear_lut:
                continue
            try:
                set_lut(project, ch.id, ch.lut_path)
            except LookupError:
                raise HTTPException(404, f"no device {ch.id}") from None
            except LutError as exc:
                raise HTTPException(422, str(exc)) from None
            luts += 1
        with project.write() as s:
            for ch in body.devices:
                if ch.lut_path is not None or ch.clear_lut:
                    continue
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
    return {
        "devices": rows,
        "assets_updated": changed,
        "refresh_job": job,
        # A LUT changes proxies and renders: the owner re-runs the analysis to apply it
        # (not started here, since it may include AI calls).
        "reanalysis_needed": luts > 0,
    }
