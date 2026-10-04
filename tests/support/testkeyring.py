"""Keyring backends for tests, so tests never touch the real OS keychain."""

from __future__ import annotations

import json
import os
from pathlib import Path

from keyring.backend import KeyringBackend
from keyring.errors import PasswordDeleteError


class MemoryKeyring(KeyringBackend):
    priority = 1  # type: ignore[assignment]
    store: dict[tuple[str, str], str] = {}  # noqa: RUF012

    def get_password(self, service: str, username: str) -> str | None:
        return self.store.get((service, username))

    def set_password(self, service: str, username: str, password: str) -> None:
        self.store[(service, username)] = password

    def delete_password(self, service: str, username: str) -> None:
        if self.store.pop((service, username), None) is None:
            raise PasswordDeleteError(username)


class FileKeyring(KeyringBackend):
    """For subprocess tests: a JSON file at $TEST_KEYRING_FILE, outside MosAic's folders."""

    priority = 1  # type: ignore[assignment]

    def _path(self) -> Path:
        return Path(os.environ["TEST_KEYRING_FILE"])

    def _load(self) -> dict[str, str]:
        p = self._path()
        return json.loads(p.read_text()) if p.exists() else {}

    def get_password(self, service: str, username: str) -> str | None:
        return self._load().get(f"{service}/{username}")

    def set_password(self, service: str, username: str, password: str) -> None:
        data = self._load()
        data[f"{service}/{username}"] = password
        self._path().write_text(json.dumps(data))

    def delete_password(self, service: str, username: str) -> None:
        data = self._load()
        if data.pop(f"{service}/{username}", None) is None:
            raise PasswordDeleteError(username)
        self._path().write_text(json.dumps(data))
