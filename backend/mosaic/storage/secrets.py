"""Secret references and storage (ADR 0003, invariant 11).

The control DB stores only a reference such as ``keyring:mosaic/ai/anthropic``. Secrets go
to the OS keyring (macOS Keychain, Windows Credential Manager) on desktop and dev; ``env:``
references exist for server and CI deployments only. Secrets are never logged, written to
files or the DB, or passed on a command line.
"""

from __future__ import annotations

import contextlib
import os

import keyring
from keyring.backend import KeyringBackend
from keyring.errors import KeyringError, PasswordDeleteError

KEYRING_SERVICE = "mosaic"


class SecretError(RuntimeError):
    pass


def keyring_ref(name: str) -> str:
    return f"keyring:{KEYRING_SERVICE}/{name}"


def _parse(ref: str) -> tuple[str, str]:
    scheme, _, rest = ref.partition(":")
    if scheme not in ("keyring", "env") or not rest:
        raise SecretError(f"unsupported secret reference {ref!r}")
    return scheme, rest


def _keyring() -> KeyringBackend:
    from keyring.backends import fail

    backend = keyring.get_keyring()
    if isinstance(backend, fail.Keyring):
        raise SecretError(
            "no OS keyring is available here; on servers use an env: secret reference"
        )
    return backend


def _keyring_error(exc: Exception) -> SecretError:
    # The backend's message may echo inputs; report only the error type.
    return SecretError(
        f"OS keyring error ({type(exc).__name__}); check that the keychain "
        "is unlocked and MosAic may access it"
    )


def store(ref: str, value: str) -> None:
    scheme, rest = _parse(ref)
    if scheme != "keyring":
        raise SecretError("only keyring: references can be written by MosAic")
    if not value or value != value.strip():
        raise SecretError("the secret is empty or has surrounding whitespace")
    service, _, username = rest.partition("/")
    try:
        _keyring().set_password(service, username, value)
    except KeyringError as exc:
        raise _keyring_error(exc) from None


def load(ref: str) -> str | None:
    scheme, rest = _parse(ref)
    if scheme == "env":
        return os.environ.get(rest) or None
    service, _, username = rest.partition("/")
    try:
        value = _keyring().get_password(service, username)
    except KeyringError as exc:
        raise _keyring_error(exc) from None
    return value or None


def delete(ref: str) -> None:
    scheme, rest = _parse(ref)
    if scheme != "keyring":
        return
    service, _, username = rest.partition("/")
    try:
        with contextlib.suppress(PasswordDeleteError):
            _keyring().delete_password(service, username)
    except KeyringError as exc:
        raise _keyring_error(exc) from None


def last4(value: str | None) -> str | None:
    return value[-4:] if value and len(value) >= 8 else None


def redact(text: str, *secrets: str | None) -> str:
    """Remove secret values from text before it is logged or raised."""
    for s in secrets:
        if s:
            text = text.replace(s, "[redacted]")
    return text
