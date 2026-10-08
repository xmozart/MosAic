"""Diagnostics (S23; ADR 0051): the task table, one task's detail, and a redacted bundle.

Everything leaving through here is redacted twice (M2 acceptance 3, invariant 11):
- the values of every key MosAic can load (each provider's secret and the deployment's
  ``MOSAIC_*`` secrets) are replaced wherever they appear;
- strings that look like keys or credentials (``sk-…``, bearer tokens, ``api_key=…``) are
  masked, and mapping keys that name a secret drop their values.
"""

from __future__ import annotations

import contextlib
import io
import json
import os
import re
import zipfile
from collections.abc import Iterable
from importlib.metadata import version
from pathlib import Path
from typing import Any

from sqlalchemy import func, select

from mosaic.core.clock import now_iso
from mosaic.core.paths import app_data_dir
from mosaic.core.principal import Principal
from mosaic.storage.config import ConfigService
from mosaic.storage.control import ControlDB
from mosaic.storage.models_control import Job, Task, TaskEvent, UsageRecord

PAGE = 100
LOG_TAIL_BYTES = 1_000_000
LOG_TOTAL_BYTES = 5_000_000  # the newest logs first, up to this much in a bundle
BUNDLE_TASKS = 2000
BUNDLE_JOBS = 200
REDACTED = "[redacted]"
STATUSES = ("pending", "ready", "leased", "done", "failed", "skipped", "cancelled")

# What runs each task kind (S23's Tool / model column, for tasks without an AI call).
TOOLS = {
    "media.probe": "ffprobe",
    "media.proxy": "ffmpeg",
    "media.visual": "frames · numpy",
    "media.waveform": "ffmpeg",
    "media.telemetry": "gpmf",
    "media.cloud_download": "file copy",
    "media.photo": "pillow",
    "photo.analyze": "pillow",
    "audio.analyze": "whisper",
    "library.embed": "siglip",
    "render.chunk": "ffmpeg",
    "render.assemble": "ffmpeg",
    "system.benchmark": "ffmpeg",
    "storage.clear": "file system",
}
_PATTERNS = (
    re.compile(r"sk-ant-[A-Za-z0-9_\-]{8,}"),
    re.compile(r"\bsk-[A-Za-z0-9_\-]{16,}"),
    re.compile(r"\bAIza[0-9A-Za-z_\-]{20,}"),
    re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._\-]{12,}"),
    re.compile(r"(?i)(api[_-]?key|secret|password|token)(\"?\s*[:=]\s*\"?)[^\s\",;]{6,}"),
    re.compile(r"(?<=://)[^/\s:@]+:[^/\s@]+(?=@)"),  # user:password in a URL
)
# A mapping key that names a secret (its value is dropped): whole names, so token counts
# (``tokens_in``, ``max_tokens``) stay.
_SECRET_NAMES = re.compile(
    r"(?i)^(.*[_-])?(api[_-]?key|secret|password|passwd|token|authorization|cookie|master[_-]?key)$"
)


def known_secrets(control: ControlDB, me: Principal) -> list[str]:
    """Every secret value this computer can load, used only to redact: each provider's
    key (the requesting user's; v1 has one), the deployment's ``MOSAIC_SECRET_*``
    variables, the master key (variable or file) and MosAic's Docker secrets."""
    from mosaic.ai.registry import PROVIDERS
    from mosaic.core.runtime import secret_env
    from mosaic.storage import secrets

    config = ConfigService(control)
    out: set[str] = set()
    for provider in PROVIDERS:
        ref = config.secret_ref(me, provider)
        if not ref:
            continue
        try:
            value = secrets.load(ref)
        except Exception:  # an unreadable store: nothing to redact from it
            value = None
        if value:
            out.add(value)
    for name, value in os.environ.items():
        if secret_env(name) and value:
            out.add(value)
    files = [Path(p) for p in (os.environ.get(secrets.MASTER_FILE_ENV),) if p]
    docker = secrets.docker_dir()
    if docker.is_dir():
        files += sorted(docker.glob("mosaic_*"))
    for f in files:
        with contextlib.suppress(OSError):
            out.add(f.read_text(encoding="utf-8").strip())
    return sorted((v for v in out if len(v) >= 6), key=len, reverse=True)


def redact(text: str, secrets: Iterable[str] = ()) -> str:
    for s in secrets:
        text = text.replace(s, REDACTED)
    for p in _PATTERNS:
        if p.groups >= 2:
            text = p.sub(lambda m: f"{m.group(1)}{m.group(2)}{REDACTED}", text)
        else:
            text = p.sub(REDACTED, text)
    return text


def redact_obj(obj: Any, secrets: Iterable[str] = ()) -> Any:
    secrets = list(secrets)
    if isinstance(obj, dict):
        return {
            k: (
                REDACTED
                if isinstance(k, str) and _SECRET_NAMES.search(k) and v
                else redact_obj(v, secrets)
            )
            for k, v in obj.items()
        }
    if isinstance(obj, list):
        return [redact_obj(v, secrets) for v in obj]
    if isinstance(obj, str):
        return redact(obj, secrets)
    return obj


def _usage(control: ControlDB, task_ids: list[int]) -> dict[int, dict[str, Any]]:
    out: dict[int, dict[str, Any]] = {}
    if not task_ids:
        return out
    with control.db.session() as s:
        rows = s.execute(
            select(
                UsageRecord.task_id,
                func.min(UsageRecord.provider),
                func.min(UsageRecord.model),
                func.sum(UsageRecord.tokens_in),
                func.sum(UsageRecord.tokens_out),
                func.sum(UsageRecord.cost_usd),
                func.count(),
            )
            .where(UsageRecord.task_id.in_(task_ids))
            .group_by(UsageRecord.task_id)
        )
        for tid, provider, model, tin, tout, cost, calls in rows:
            if tid is None:
                continue
            out[tid] = {
                "provider": provider,
                "model": model,
                "tokens_in": int(tin or 0),
                "tokens_out": int(tout or 0),
                "cost_usd": round(float(cost or 0), 6),
                "calls": int(calls),
            }
    return out


def _row(
    t: Task, job_kind: str | None, usage: dict[str, Any] | None, secrets: Iterable[str] = ()
) -> dict[str, Any]:
    return {
        "task_id": t.id,
        "job_id": t.job_id,
        "job_kind": job_kind,
        "project_id": t.project_id,
        "kind": t.kind,
        "stage": t.stage,
        "input": redact(t.label, secrets) if t.label else None,
        "status": t.status,
        "attempts": t.attempts,
        "max_attempts": t.max_attempts,
        "duration_ms": t.duration_ms,
        "created_at": t.created_at,
        "finished_at": t.finished_at,
        "tool": f"{usage['provider']} · {usage['model']}" if usage else TOOLS.get(t.kind),
        "tokens_in": usage["tokens_in"] if usage else None,
        "tokens_out": usage["tokens_out"] if usage else None,
        "cost_usd": usage["cost_usd"] if usage else None,
    }


def task_rows(
    control: ControlDB,
    me: Principal,
    project: str | None = None,
    status: str | None = None,
    cursor: int | None = None,
    limit: int = PAGE,
) -> dict[str, Any]:
    """Newest first; ``cursor`` is the last task id of the previous page."""
    q = select(Task, Job.kind).join(Job, Job.id == Task.job_id)
    if project:
        q = q.where(Task.project_id == project)
    if status:
        q = q.where(Task.status == status)
    if cursor is not None:
        q = q.where(Task.id < cursor)
    with control.db.session() as s:
        rows = list(s.execute(q.order_by(Task.id.desc()).limit(limit + 1)))
        for t, _ in rows:
            s.expunge(t)
    more = len(rows) > limit
    rows = rows[:limit]
    usage = _usage(control, [t.id for t, _ in rows])
    secrets = known_secrets(control, me)
    return {
        "items": [_row(t, kind, usage.get(t.id), secrets) for t, kind in rows],
        "next_cursor": rows[-1][0].id if more and rows else None,
    }


def task_detail(control: ControlDB, me: Principal, task_id: int) -> dict[str, Any] | None:
    with control.db.session() as s:
        found = s.execute(
            select(Task, Job.kind).join(Job, Job.id == Task.job_id).where(Task.id == task_id)
        ).first()
        if found is None:
            return None
        t, kind = found
        events = [
            {"event": e.event, "worker_id": e.worker_id, "detail": e.detail, "at": e.created_at}
            for e in s.scalars(
                select(TaskEvent).where(TaskEvent.task_id == task_id).order_by(TaskEvent.id)
            )
        ]
        s.expunge(t)
    secrets = known_secrets(control, me)
    started = next((e["at"] for e in events if e["event"] in ("started", "leased")), None)
    worker = next((e["worker_id"] for e in reversed(events) if e["worker_id"]), None)
    out = _row(t, kind, _usage(control, [task_id]).get(task_id), secrets)
    out |= {
        "error": redact(t.error, secrets) if t.error else None,
        "params": redact_obj(t.params, secrets),
        "result": redact_obj(t.result, secrets),
        "events": redact_obj(events[-50:], secrets),
        "started_at": started,
        "worker": worker,
        "can_retry": t.status in ("failed", "cancelled"),
        "can_skip": t.status == "failed",
    }
    return out


def _tail(path: Path, n: int) -> str:
    """The last ``n`` bytes, from the first whole line (a cut never leaves part of a
    secret that whole-value redaction could miss)."""
    with open(path, "rb") as f:
        f.seek(0, os.SEEK_END)
        size = f.tell()
        f.seek(max(0, size - n))
        data = f.read()
    if size > n:
        data = data[data.find(b"\n") + 1 :] if b"\n" in data else b""
    return data.decode("utf-8", errors="replace")


def bundle(control: ControlDB, me: Principal, system: dict[str, Any]) -> bytes:
    """A zip for support: system info, settings, recent jobs and tasks, log tails.
    Redacted (see the module docstring); no project database, media or API key."""
    secrets = known_secrets(control, me)
    config = ConfigService(control)
    settings = {k: {"value": v.value, "source": v.source} for k, v in config.settings(me).items()}
    providers = {
        cap: {
            "provider": st.choice.provider,
            "model": st.choice.model,
            "mode": st.choice.mode,
            "source": st.source,
        }
        for cap, st in config.providers(me).items()
    }
    with control.db.session() as s:
        jobs = [
            {
                "job_id": j.id,
                "project_id": j.project_id,
                "kind": j.kind,
                "status": j.status,
                "stage": j.stage,
                "error": j.error,
                "cost_usd": j.cost_usd,
                "created_at": j.created_at,
                "updated_at": j.updated_at,
            }
            for j in s.scalars(select(Job).order_by(Job.id.desc()).limit(BUNDLE_JOBS))
        ]
    tasks = task_rows(control, me, limit=BUNDLE_TASKS)["items"]
    with control.db.session() as s:
        errors = dict(
            s.execute(
                select(Task.id, Task.error).where(
                    Task.id.in_([t["task_id"] for t in tasks]), Task.error.is_not(None)
                )
            ).all()
        )
    for t in tasks:
        t["error"] = errors.get(t["task_id"])
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:

        def put(name: str, data: Any) -> None:
            text = (
                data
                if isinstance(data, str)
                else json.dumps(redact_obj(data, secrets), indent=2, default=str)
            )
            z.writestr(name, redact(text, secrets))

        put(
            "manifest.json",
            {
                "format": "mosaic.diagnostics/1",
                "created_at": now_iso(),
                "version": version("mosaic"),
                "note": "Redacted: API keys and other secrets are removed.",
            },
        )
        put("system.json", system)
        put("settings.json", {"settings": settings, "providers": providers})
        put("jobs.json", jobs)
        put("tasks.json", tasks)
        logs = app_data_dir() / "logs"
        budget = LOG_TOTAL_BYTES
        if logs.is_dir():
            for f in sorted(logs.glob("*.log"), key=lambda x: x.stat().st_mtime, reverse=True):
                if budget <= 0:
                    break
                text = _tail(f, min(LOG_TAIL_BYTES, budget))
                budget -= len(text.encode())
                put(f"logs/{f.name}", text)
    return buf.getvalue()
