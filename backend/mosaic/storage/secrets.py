"""Secret references and storage (ADR 0003, invariant 11).

The control DB stores only a reference such as ``keyring:mosaic/ai/anthropic``. Backends:

- ``keyring:`` — the OS keyring (macOS Keychain, Windows Credential Manager): desktop, dev.
- ``file:`` — server mode (ADR 0036): an encrypted file in the app data folder, keyed by the
  install master key (``MOSAIC_MASTER_KEY`` or ``MOSAIC_MASTER_KEY_FILE``). Each value is a
  Fernet token (AES-128-CBC + HMAC-SHA256) under a key derived with scrypt.
- ``env:`` and ``docker:`` — keys the deployment provides, read-only: an environment
  variable, or a Docker secret file in ``/run/secrets``.

Secrets are never logged, written to project files, the DB or exports, or passed on a
command line (invariant 11).
"""

from __future__ import annotations

import base64
import binascii
import contextlib
import hashlib
import json
import logging
import os
import re
import tempfile
import threading
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import keyring
from keyring.backend import KeyringBackend
from keyring.errors import KeyringError, PasswordDeleteError

log = logging.getLogger(__name__)

KEYRING_SERVICE = "mosaic"


class SecretError(RuntimeError):
    pass


def keyring_ref(name: str) -> str:
    return f"keyring:{KEYRING_SERVICE}/{name}"


SCHEMES = ("keyring", "env", "docker", "file")
WRITABLE = ("keyring", "file")
DOCKER_DIR = "/run/secrets"
MASTER_ENV = "MOSAIC_MASTER_KEY"
MASTER_FILE_ENV = "MOSAIC_MASTER_KEY_FILE"
MIN_MASTER = 32
_SAFE = re.compile(r"^[A-Za-z0-9_.-]{1,128}$")


def _parse(ref: str) -> tuple[str, str]:
    scheme, _, rest = ref.partition(":")
    if scheme not in SCHEMES or not rest:
        raise SecretError(f"unsupported secret reference {ref!r}")
    return scheme, rest


def file_ref(name: str) -> str:
    return f"file:{name}"


def env_name(name: str) -> str:
    """``ai/anthropic`` → ``MOSAIC_SECRET_AI_ANTHROPIC``."""
    return "MOSAIC_SECRET_" + re.sub(r"[^A-Za-z0-9]", "_", name).upper()


def docker_name(name: str) -> str:
    """``ai/anthropic`` → ``mosaic_ai_anthropic`` (a file in ``/run/secrets``)."""
    return "mosaic_" + re.sub(r"[^A-Za-z0-9]", "_", name).lower()


def deployment_ref(name: str) -> str | None:
    """A key the deployment provides for ``name``, if any: a Docker secret, else an
    environment variable (server and CI; never written by MosAic)."""
    if (_docker_dir() / docker_name(name)).is_file():
        return f"docker:{docker_name(name)}"
    if os.environ.get(env_name(name)):
        return f"env:{env_name(name)}"
    return None


def writable_ref(name: str) -> str:
    """Where a key typed into MosAic is kept: the OS keyring on desktop, the encrypted
    file on a server (which needs the install master key)."""
    from mosaic.core.runtime import server_mode

    if not server_mode():
        return keyring_ref(name)
    _master()  # fail early, naming the fix
    return file_ref(name)


def _docker_dir() -> Path:
    return Path(os.environ.get("MOSAIC_DOCKER_SECRETS_DIR", DOCKER_DIR))


def _master() -> bytes:
    value = os.environ.get(MASTER_ENV, "")
    path = os.environ.get(MASTER_FILE_ENV, "")
    if not value and path:
        try:
            value = Path(path).read_text(encoding="utf-8").strip()
        except OSError as exc:
            raise SecretError(f"the master key file can't be read ({type(exc).__name__})") from None
    if len(value) < MIN_MASTER:
        raise SecretError(
            "keys can't be saved on this server yet: set MOSAIC_MASTER_KEY (or "
            f"MOSAIC_MASTER_KEY_FILE, e.g. a Docker secret) to {MIN_MASTER}+ random "
            "characters, or provide the key as a MOSAIC_SECRET_… variable or Docker secret"
        )
    return value.encode()


def _store_path() -> Path:
    from mosaic.core.paths import app_data_dir

    return app_data_dir() / "secrets.enc.json"


# Environment variables that hold secrets. Child processes that never need them (installed
# AI apps, FFmpeg) don't get them (invariant 11); the worker does. Prefixes end with "_".
SECRET_ENV = (MASTER_ENV, MASTER_FILE_ENV, "MOSAIC_SECRET_")

_store_lock = threading.Lock()
_fernets: dict[tuple[str, bytes], Any] = {}


def secret_env(name: str) -> bool:
    return any(name == e or (e.endswith("_") and name.startswith(e)) for e in SECRET_ENV)


def scrubbed_env() -> dict[str, str]:
    """This process's environment without MosAic's secrets, for child processes that never
    need them (FFmpeg, probes, installed AI apps)."""
    return {k: v for k, v in os.environ.items() if not secret_env(k)}


def _fernet(salt: bytes) -> Any:
    from cryptography.fernet import Fernet
    from cryptography.hazmat.primitives.kdf.scrypt import Scrypt

    master = _master()
    cache_key = (hashlib.sha256(master).hexdigest(), salt)
    f = _fernets.get(cache_key)
    if f is None:  # scrypt is deliberately slow: derive once per master key and file
        key = Scrypt(salt=salt, length=32, n=2**15, r=8, p=1).derive(master)
        f = _fernets[cache_key] = Fernet(base64.urlsafe_b64encode(key))
    return f


DAMAGED = "the encrypted key file is damaged; enter the key again"


def _read_store() -> dict[str, Any]:
    p = _store_path()
    if not p.is_file():
        return {"version": 1, "salt": base64.b64encode(os.urandom(16)).decode(), "entries": {}}
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        salt = base64.b64decode(data["salt"], validate=True)
        if not isinstance(data["entries"], dict) or len(salt) < 16:
            raise ValueError("bad store")
    except (OSError, ValueError, KeyError, TypeError, binascii.Error):
        raise SecretError(DAMAGED) from None  # never the file's content
    return dict(data)


def _write_store(data: dict[str, Any]) -> None:
    """Atomic and private: a fresh 0600 temp file in the same folder, fsynced, renamed."""
    p = _store_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=p.parent, prefix=".secrets.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, p)
    except BaseException:
        with contextlib.suppress(OSError):
            os.unlink(tmp)
        raise


@contextlib.contextmanager
def _exclusive() -> Iterator[None]:
    """One writer at a time: threads of this process, and other MosAic processes."""
    from mosaic.storage.locks import locked

    p = _store_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    with _store_lock, locked(p.with_name(p.name + ".lock")):
        yield


def _file_store(name: str, value: str) -> None:
    with _exclusive():
        try:
            data = _read_store()
        except SecretError:
            # Damaged: keep it aside (never deleted) and start a fresh store, so entering
            # the key again — as the message says — works.
            p = _store_path()
            os.replace(p, p.with_name(f"{p.name}.damaged-{time.time_ns()}"))
            log.warning("the encrypted key file was damaged; kept aside, starting a new one")
            data = _read_store()
        token = _fernet(base64.b64decode(data["salt"])).encrypt(value.encode())
        data["entries"][name] = token.decode()
        _write_store(data)


def _file_load(name: str) -> str | None:
    from cryptography.fernet import InvalidToken

    data = _read_store()
    token = data["entries"].get(name)
    if token is None:
        return None
    try:
        value: str = _fernet(base64.b64decode(data["salt"])).decrypt(token.encode()).decode()
    except InvalidToken:
        raise SecretError(
            "the saved key can't be decrypted: the master key changed. Enter the key again."
        ) from None
    except (ValueError, AttributeError):
        raise SecretError(DAMAGED) from None
    return value


def _file_delete(name: str) -> None:
    with _exclusive():
        data = _read_store()
        if data["entries"].pop(name, None) is not None:
            _write_store(data)


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
    if scheme not in WRITABLE:
        raise SecretError("keys from the deployment (env:, docker:) are read-only")
    if not value or value != value.strip():
        raise SecretError("the secret is empty or has surrounding whitespace")
    if scheme == "file":
        _file_store(rest, value)
        return
    service, _, username = rest.partition("/")
    try:
        _keyring().set_password(service, username, value)
    except KeyringError as exc:
        raise _keyring_error(exc) from None


def load(ref: str) -> str | None:
    scheme, rest = _parse(ref)
    if scheme == "env":
        return os.environ.get(rest) or None
    if scheme == "docker":
        if not _SAFE.match(rest):
            raise SecretError("invalid Docker secret name")
        try:
            return (_docker_dir() / rest).read_text(encoding="utf-8").strip() or None
        except FileNotFoundError:
            return None
        except OSError as exc:
            raise SecretError(f"the Docker secret can't be read ({type(exc).__name__})") from None
    if scheme == "file":
        return _file_load(rest)
    service, _, username = rest.partition("/")
    try:
        value = _keyring().get_password(service, username)
    except KeyringError as exc:
        raise _keyring_error(exc) from None
    return value or None


def delete(ref: str) -> None:
    scheme, rest = _parse(ref)
    if scheme == "file":
        _file_delete(rest)
        return
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
