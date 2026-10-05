"""``/api/settings``, ``/api/providers`` and ``/api/secrets`` (docs/ui/API_MAP.md, ADR 0003).

Secrets are write-only: responses carry ``configured`` and the last four characters.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from mosaic.app.deps import principal, services
from mosaic.app.services import Services
from mosaic.core.principal import Principal
from mosaic.core.settings import SettingError
from mosaic.storage import secrets
from mosaic.storage.config import KNOWN_PROVIDERS, ConfigService

router = APIRouter(prefix="/api")
Svc = Depends(services)
Me = Depends(principal)


def _config(svc: Services) -> ConfigService:
    return ConfigService(svc.control)


@router.get("/settings")
def get_settings(svc: Services = Svc, me: Principal = Me) -> dict[str, Any]:
    return {k: {"value": v.value, "source": v.source} for k, v in _config(svc).settings(me).items()}


# Changed only with `mosaic config` on the host: a dev-only switch, and the paths of the
# executables MosAic runs (an API caller must not choose a program to execute).
API_READONLY_SETTINGS = frozenset({"allow_gpl_ffmpeg", "ai.cli.claude_path", "ai.cli.codex_path"})


@router.patch("/settings")
def patch_settings(body: dict[str, Any], svc: Services = Svc, me: Principal = Me) -> dict[str, Any]:
    blocked = sorted(API_READONLY_SETTINGS & set(body))
    if blocked:
        raise HTTPException(403, f"{', '.join(blocked)} can only be changed with mosaic config")
    try:
        _config(svc).set_many(me, body)  # all keys or none
    except SettingError as exc:
        raise HTTPException(422, str(exc)) from exc
    return get_settings(svc, me)


def _providers_json(cfg: ConfigService, me: Principal) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for cap, st in cfg.providers(me).items():
        ch = st.choice
        entry: dict[str, Any] = {
            "provider": ch.provider,
            "model": ch.model,
            "mode": ch.mode,
            "source": st.source,
        }
        if st.needs_key:
            ks = cfg.key_status(me, ch.provider)
            entry["key"] = {"configured": ks.configured, "last4": ks.last4}
        out[cap] = entry
    return out


@router.get("/providers")
def get_providers(svc: Services = Svc, me: Principal = Me) -> dict[str, Any]:
    return _providers_json(_config(svc), me)


class ProviderPatch(BaseModel):
    provider: str
    model: str


@router.patch("/providers")
def patch_providers(
    body: dict[str, ProviderPatch], svc: Services = Svc, me: Principal = Me
) -> dict[str, Any]:
    cfg = _config(svc)
    try:
        cfg.set_providers_many(me, {cap: (c.provider, c.model) for cap, c in body.items()})
    except SettingError as exc:
        raise HTTPException(422, str(exc)) from exc
    return _providers_json(cfg, me)


class SecretBody(BaseModel):
    value: str


@router.put("/secrets/{ref:path}")
def put_secret(
    ref: str, body: SecretBody, svc: Services = Svc, me: Principal = Me
) -> dict[str, Any]:
    """``ref`` is the secret name, e.g. ``ai/anthropic``. Write-only."""
    kind, _, provider = ref.partition("/")
    if kind != "ai" or not provider:
        raise HTTPException(404, "unknown secret")
    try:
        ks = _config(svc).set_key(me, provider, body.value.strip())
    except (SettingError, secrets.SecretError) as exc:
        raise HTTPException(422, secrets.redact(str(exc), body.value)) from None
    return {"configured": ks.configured, "last4": ks.last4}


@router.post("/secrets/{ref:path}/validate")
def validate_secret(ref: str, svc: Services = Svc, me: Principal = Me) -> dict[str, Any]:
    from mosaic.ai.health import check_provider

    kind, _, provider = ref.partition("/")
    if kind != "ai" or not provider:
        raise HTTPException(404, "unknown secret")
    if KNOWN_PROVIDERS.get(provider) == "cli":
        # Installed apps have no key; checking one runs the app, which is not request work.
        raise HTTPException(404, f"{provider} has no key to validate; use `mosaic config ai test`")
    r = check_provider(_config(svc), me, provider)
    return {
        "ok": r.ok,
        "provider": r.provider,
        "model": r.model,
        "message": r.message,
        "latency_ms": r.latency_ms,
    }
