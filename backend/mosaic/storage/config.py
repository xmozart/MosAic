"""App configuration service (ADR 0003): settings, provider profiles and secret references.

One service behind both the ``mosaic config`` CLI and the ``/settings``, ``/providers`` and
``/secrets`` API, so the later UI (S1, S22) uses exactly the same rules.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlalchemy import delete, select

from mosaic.core.clock import now_iso
from mosaic.core.principal import Principal, check
from mosaic.core.settings import (
    CAPABILITIES,
    LOCAL_MODELS,
    PROVIDER_CAPABILITIES,
    ProviderChoice,
    SettingError,
    coerce,
    default_provider,
    default_settings,
)
from mosaic.storage import secrets
from mosaic.storage.control import ControlDB
from mosaic.storage.models_control import ProviderProfile, SecretRef, UserPreference

KNOWN_PROVIDERS: dict[str, str] = {
    # provider → mode. Cloud providers need a key; adapters are added when chosen (ADR 0003).
    "anthropic": "cloud",
    "claude-cli": "cli",  # sends data to the provider but needs no key (ADR 0014)
    "codex-cli": "cli",
    "fake": "local",
    "faster-whisper": "local",
    "siglip-onnx": "local",
}


@dataclass(frozen=True)
class SettingValue:
    value: Any
    source: str  # default|user


@dataclass(frozen=True)
class ProviderStatus:
    choice: ProviderChoice
    source: str  # default|user
    needs_key: bool


@dataclass(frozen=True)
class KeyStatus:
    provider: str
    ref: str | None
    configured: bool
    last4: str | None
    error: str | None = None


class NotConfiguredError(RuntimeError):
    """A required setting or key is missing; the message says which command fixes it."""


def secret_name(provider: str) -> str:
    return f"ai/{provider}"


class ConfigService:
    def __init__(self, control: ControlDB) -> None:
        self.control = control

    # ------------------------------------------------------------------ settings

    def settings(self, principal: Principal) -> dict[str, SettingValue]:
        check(principal, "settings.read", "app")
        out = {k: SettingValue(v, "default") for k, v in default_settings().items()}
        with self.control.db.session() as s:
            for row in s.scalars(
                select(UserPreference).where(UserPreference.user_id == principal.user_id)
            ):
                if row.key in out:
                    out[row.key] = SettingValue(row.value, "user")
        return out

    def get(self, principal: Principal, key: str) -> Any:
        values = self.settings(principal)
        if key not in values:
            raise SettingError(f"unknown setting {key!r}")
        return values[key].value

    def set(self, principal: Principal, key: str, value: Any) -> SettingValue:
        check(principal, "settings.write", key)
        typed = coerce(key, value)
        with self.control.db.session() as s:
            s.merge(
                UserPreference(
                    user_id=principal.user_id, key=key, value=typed, updated_at=now_iso()
                )
            )
        return SettingValue(typed, "user")

    def set_many(self, principal: Principal, values: dict[str, Any]) -> None:
        """Validate every key first, then write all of them or none (``None`` resets)."""
        for key in values:
            check(principal, "settings.write", key)
        typed = {k: (None if v is None else coerce(k, v)) for k, v in values.items()}
        for key in typed:
            coerce(key, default_settings().get(key, ""))  # key must exist even for a reset
        with self.control.db.session() as s:
            for key, value in typed.items():
                if value is None:
                    s.execute(
                        delete(UserPreference).where(
                            UserPreference.user_id == principal.user_id, UserPreference.key == key
                        )
                    )
                else:
                    s.merge(
                        UserPreference(
                            user_id=principal.user_id, key=key, value=value, updated_at=now_iso()
                        )
                    )

    def reset(self, principal: Principal, key: str) -> SettingValue:
        check(principal, "settings.write", key)
        coerce(key, default_settings().get(key, ""))  # validates the key exists
        with self.control.db.session() as s:
            s.execute(
                delete(UserPreference).where(
                    UserPreference.user_id == principal.user_id, UserPreference.key == key
                )
            )
        return SettingValue(default_settings()[key], "default")

    # ----------------------------------------------------------------- providers

    def providers(self, principal: Principal) -> dict[str, ProviderStatus]:
        check(principal, "providers.read", "app")
        with self.control.db.session() as s:
            rows = {
                r.capability: r
                for r in s.scalars(
                    select(ProviderProfile).where(ProviderProfile.user_id == principal.user_id)
                )
            }
        out: dict[str, ProviderStatus] = {}
        for cap in CAPABILITIES:
            row = rows.get(cap)
            if row is not None:
                choice = ProviderChoice(cap, row.provider, row.model, row.mode)
                source = "user"
            else:
                choice, source = default_provider(cap), "default"
            out[cap] = ProviderStatus(choice, source, choice.mode == "cloud")
        return out

    def provider(self, principal: Principal, capability: str) -> ProviderChoice:
        if capability not in CAPABILITIES:
            raise SettingError(f"unknown capability {capability!r}")
        return self.providers(principal)[capability].choice

    def validate_provider(self, capability: str, provider: str, model: str) -> list[str]:
        """The capabilities a ``set_provider`` call would change; raises if invalid."""
        if capability == "all":
            caps = [c for c in CAPABILITIES if default_provider(c).mode == "cloud"]
        else:
            caps = [capability]
        for cap in caps:
            if cap not in CAPABILITIES:
                raise SettingError(
                    f"unknown capability {cap!r}; use one of {', '.join(CAPABILITIES)} or all"
                )
        if provider not in KNOWN_PROVIDERS:
            raise SettingError(
                f"no adapter for provider {provider!r} yet; available: "
                f"{', '.join(sorted(KNOWN_PROVIDERS))}"
            )
        if not model.strip():
            raise SettingError("model must not be empty")
        local = LOCAL_MODELS.get(provider)
        if local is not None and model.strip() not in local:
            raise SettingError(f"{provider} supports models {', '.join(local)}")
        unsupported = [c for c in caps if c not in PROVIDER_CAPABILITIES.get(provider, ())]
        if unsupported:
            raise SettingError(
                f"{provider} cannot serve {', '.join(unsupported)}; it serves "
                f"{', '.join(PROVIDER_CAPABILITIES.get(provider, ())) or 'nothing'}"
            )
        return caps

    def set_provider(
        self, principal: Principal, capability: str, provider: str, model: str
    ) -> list[ProviderChoice]:
        check(principal, "providers.write", capability)
        caps = self.validate_provider(capability, provider, model)
        mode = KNOWN_PROVIDERS[provider]
        out = []
        with self.control.db.session() as s:
            for cap in caps:
                s.merge(
                    ProviderProfile(
                        user_id=principal.user_id,
                        capability=cap,
                        provider=provider,
                        model=model.strip(),
                        mode=mode,
                        updated_at=now_iso(),
                    )
                )
                out.append(ProviderChoice(cap, provider, model.strip(), mode))
        return out

    # ------------------------------------------------------------------- secrets

    def secret_ref(self, principal: Principal, provider: str) -> str | None:
        with self.control.db.session() as s:
            row = s.get(SecretRef, (principal.user_id, secret_name(provider)))
            return row.ref if row else None

    def set_key(self, principal: Principal, provider: str, value: str) -> KeyStatus:
        """Store a provider key in the OS keyring; the DB keeps only the reference."""
        check(principal, "secrets.write", provider)
        if KNOWN_PROVIDERS.get(provider) != "cloud":
            raise SettingError(f"provider {provider!r} does not use a key")
        ref = secrets.keyring_ref(secret_name(provider))
        secrets.store(ref, value)
        with self.control.db.session() as s:
            s.merge(
                SecretRef(
                    user_id=principal.user_id,
                    name=secret_name(provider),
                    ref=ref,
                    updated_at=now_iso(),
                )
            )
        return KeyStatus(provider, ref, True, secrets.last4(value))

    def reset_key(self, principal: Principal, provider: str) -> None:
        check(principal, "secrets.write", provider)
        ref = self.secret_ref(principal, provider)
        if ref is None:
            return
        secrets.delete(ref)
        with self.control.db.session() as s:
            s.execute(
                delete(SecretRef).where(
                    SecretRef.user_id == principal.user_id, SecretRef.name == secret_name(provider)
                )
            )

    def set_providers_many(self, principal: Principal, choices: dict[str, tuple[str, str]]) -> None:
        """Validate every ``capability → (provider, model)`` and write them in one session."""
        planned = []
        for cap, (provider, model) in choices.items():
            check(principal, "providers.write", cap)
            for c in self.validate_provider(cap, provider, model):
                planned.append((c, provider, model.strip(), KNOWN_PROVIDERS[provider]))
        with self.control.db.session() as s:
            for cap, provider, model, mode in planned:
                s.merge(
                    ProviderProfile(
                        user_id=principal.user_id,
                        capability=cap,
                        provider=provider,
                        model=model,
                        mode=mode,
                        updated_at=now_iso(),
                    )
                )

    def key_status(self, principal: Principal, provider: str) -> KeyStatus:
        ref = self.secret_ref(principal, provider)
        if ref is None:
            return KeyStatus(provider, None, False, None)
        try:
            value = secrets.load(ref)
        except secrets.SecretError as exc:
            return KeyStatus(provider, ref, False, None, str(exc))
        return KeyStatus(provider, ref, value is not None, secrets.last4(value))

    def key_for(self, principal: Principal, provider: str) -> str:
        """The secret for ``provider``, or ``NotConfiguredError`` naming the fix."""
        ref = self.secret_ref(principal, provider)
        if ref is None:
            raise NotConfiguredError(
                f"not configured: no API key for {provider}; run "
                f"`mosaic config ai set-key --provider {provider}`"
            )
        value = secrets.load(ref)
        if value is None:
            raise NotConfiguredError(
                f"not configured: the {provider} key is missing from the keyring; run "
                f"`mosaic config ai set-key --provider {provider}`"
            )
        return value
