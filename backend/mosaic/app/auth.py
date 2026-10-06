"""Server-mode sign-in (ARCHITECTURE.md §3, §14; S2; ADR 0034).

One admin account (v1): an Argon2 password hash in the control DB. A session is a random
token in an HttpOnly, SameSite=Strict cookie; the DB keeps only its SHA-256. Every
mutating request must echo the session's CSRF token in ``X-CSRF-Token`` (double submit:
the token is also readable from the non-HttpOnly ``mosaic_csrf`` cookie). Five failed
sign-ins from one address lock it out for a while, doubling up to 15 minutes.

Desktop mode does not use any of this (its per-launch token comes with Tauri in M3).
"""

from __future__ import annotations

import hashlib
import hmac
import os
import secrets as pysecrets
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError
from sqlalchemy import delete
from sqlalchemy.exc import IntegrityError

from mosaic.core.clock import now_iso
from mosaic.storage.control import ControlDB
from mosaic.storage.models_control import AdminAccount, AuthSession

SESSION_COOKIE = "mosaic_session"
CSRF_COOKIE = "mosaic_csrf"
CSRF_HEADER = "x-csrf-token"
IDLE_S = 12 * 3600
ABSOLUTE_S = 7 * 24 * 3600
IDLE_MS = IDLE_S * 1000
ABSOLUTE_MS = ABSOLUTE_S * 1000
MIN_PASSWORD = 12
FAILURES_BEFORE_LOCK = 5
LOCK_S = 30
LOCK_MAX_S = 15 * 60

_hasher = PasswordHasher()


def server_mode() -> bool:
    return os.environ.get("MOSAIC_MODE", "desktop").strip().lower() == "server"


def cookie_secure() -> bool:
    """Secure cookies unless explicitly turned off for plain-http testing (browsers treat
    http://localhost as secure, so the default works for a local compose)."""
    return os.environ.get("MOSAIC_COOKIE_SECURE", "1").strip() not in ("0", "false", "no")


def _now_ms() -> int:
    return time.time_ns() // 1_000_000


def _digest(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


class AuthError(Exception):
    def __init__(self, status: int, message: str, retry_after: int | None = None) -> None:
        super().__init__(message)
        self.status = status
        self.retry_after = retry_after


@dataclass(frozen=True)
class Session:
    token: str  # the cookie value; never stored
    csrf: str


class Throttle:
    """Sign-in attempts per client address, in memory (one server process). An attempt is
    counted before the password is checked, so parallel guesses cannot slip past the lock."""

    def __init__(self, clock: Callable[[], float] = time.monotonic) -> None:
        self._clock = clock
        self._lock = threading.Lock()
        self._attempts: dict[str, int] = {}
        self._until: dict[str, float] = {}
        self._strikes: dict[str, int] = {}
        self._last: dict[str, float] = {}

    def _prune(self, now: float) -> None:
        """Forget a client that has been quiet for a full maximum lock: no attempt and no
        lock in that time (memory stays bounded, and old failures do not add up with new
        ones months later; within that window locks keep doubling)."""
        quiet = [
            c
            for c, last in self._last.items()
            if now - max(last, self._until.get(c, 0.0)) > LOCK_MAX_S
        ]
        for client in quiet:
            for d in (self._attempts, self._until, self._strikes, self._last):
                d.pop(client, None)

    def attempt(self, client: str) -> int:
        """0 when this attempt may proceed (it is counted), else seconds to wait."""
        with self._lock:
            now = self._clock()
            self._prune(now)
            until = self._until.get(client, 0.0)
            if until > now:
                return max(1, int(until - now + 0.999))
            self._last[client] = now
            n = self._attempts.get(client, 0) + 1
            self._attempts[client] = n
            if n >= FAILURES_BEFORE_LOCK:
                strikes = self._strikes.get(client, 0)
                self._until[client] = now + min(LOCK_MAX_S, LOCK_S * 2**strikes)
                self._strikes[client] = strikes + 1
                self._attempts[client] = 0
            return 0

    def wait_s(self, client: str) -> int:
        with self._lock:
            left = self._until.get(client, 0.0) - self._clock()
            return max(0, int(left + 0.999))

    def succeeded(self, client: str) -> None:
        with self._lock:
            for d in (self._attempts, self._until, self._strikes, self._last):
                d.pop(client, None)


class Auth:
    def __init__(self, control: ControlDB) -> None:
        self.control = control
        self.throttle = Throttle()

    # ------------------------------------------------------------------ account

    def has_admin(self) -> bool:
        with self.control.db.session() as s:
            return s.get(AdminAccount, 1) is not None

    def setup(self, password: str) -> Session:
        """Create the admin account once (S2 first-time variant)."""
        if len(password) < MIN_PASSWORD:
            raise AuthError(422, f"Use at least {MIN_PASSWORD} characters.")
        password_hash = _hasher.hash(password)
        try:
            with self.control.db.session() as s:
                if s.get(AdminAccount, 1) is not None:
                    raise AuthError(409, "An account already exists. Sign in instead.")
                s.add(AdminAccount(id=1, password_hash=password_hash, created_at=now_iso()))
        except IntegrityError:  # two first-time setups at once: one wins
            raise AuthError(409, "An account already exists. Sign in instead.") from None
        return self._new_session()

    def login(self, password: str, client: str) -> Session:
        wait = self.throttle.attempt(client)
        if wait:
            raise AuthError(429, "Too many attempts. Try again shortly.", retry_after=wait)
        with self.control.db.session() as s:
            row = s.get(AdminAccount, 1)
            stored = row.password_hash if row else None
        ok = False
        if stored is not None:
            try:
                ok = _hasher.verify(stored, password)
            except (VerificationError, InvalidHashError):
                ok = False
        else:
            _hasher.hash(password)  # same cost either way: no timing hint
        if not ok:
            wait = self.throttle.wait_s(client)  # this attempt may have been the fifth
            if wait:
                raise AuthError(429, "Too many attempts. Try again shortly.", retry_after=wait)
            raise AuthError(401, "That password didn't match. Try again.")
        self.throttle.succeeded(client)
        if stored is not None and _hasher.check_needs_rehash(stored):
            with self.control.db.session() as s:
                acc = s.get(AdminAccount, 1)
                if acc is not None:
                    acc.password_hash = _hasher.hash(password)
        return self._new_session()

    # ---------------------------------------------------------------- sessions

    def _new_session(self) -> Session:
        token = pysecrets.token_urlsafe(32)
        csrf = pysecrets.token_urlsafe(32)
        now = _now_ms()
        with self.control.db.session() as s:
            s.execute(delete(AuthSession).where(AuthSession.expires_ms < now))
            s.add(
                AuthSession(
                    token_hash=_digest(token),
                    csrf_hash=_digest(csrf),
                    created_ms=now,
                    last_seen_ms=now,
                    expires_ms=now + ABSOLUTE_MS,
                )
            )
        return Session(token, csrf)

    def check(self, token: str | None, csrf: str | None, mutating: bool) -> bool:
        """The session is valid (and, for a mutating request, the CSRF token matches)."""
        if not token:
            return False
        now = _now_ms()
        with self.control.db.session() as s:
            row = s.get(AuthSession, _digest(token))
            if row is None or row.expires_ms < now or now - row.last_seen_ms > IDLE_MS:
                if row is not None:
                    s.delete(row)
                return False
            if mutating and not (csrf and hmac.compare_digest(row.csrf_hash, _digest(csrf))):
                return False
            if now - row.last_seen_ms > 60_000:
                row.last_seen_ms = now
        return True

    def logout(self, token: str | None) -> None:
        if token:
            with self.control.db.session() as s:
                s.execute(delete(AuthSession).where(AuthSession.token_hash == _digest(token)))
