"""Desktop API access (M3; ARCHITECTURE.md §14; ADR 0057).

The Tauri shell starts the backend with a fresh random token on the first line of stdin
(``serve --token-stdin``), or in ``MOSAIC_DESKTOP_TOKEN``; never in argv. ``serve`` reads
it before anything else starts (and takes it out of the environment), so workers, FFmpeg
and AI apps never inherit it. A token that is set but empty or short stops the start. The
UI and the API share one loopback origin (``http://127.0.0.1:<random port>``); the shell
injects the token into its own webview, and the page trades it once for an HttpOnly
session cookie, so media elements (``<video>``, ``<img>``) and the event stream are
covered too.

A request is let in when it carries the token as ``Authorization: Bearer``, or the session
cookie *and* ``Sec-Fetch-Site: same-origin`` (or ``none``, a navigation the user started).
Browsers set that header themselves and pages cannot change it, so another web page — even
one served from ``127.0.0.1`` on another port, which counts as the same *site* and would
get the cookie — is refused. No CORS headers are sent: no other origin may read anything.

Without a token (developers running ``mosaic serve``, and tests) desktop mode stays as in
M0: loopback and the Host check only.
"""

from __future__ import annotations

import hmac
import os
import secrets
import threading
from typing import TextIO

ENV_TOKEN = "MOSAIC_DESKTOP_TOKEN"
COOKIE = "mosaic_desktop"
SAME_ORIGIN = frozenset({"same-origin", "none"})


MIN_TOKEN = 32


class DesktopTokenError(ValueError):
    """A token was given but is unusable: refuse to start rather than run unprotected."""


def checked(token: str) -> str:
    token = token.strip()
    if len(token) < MIN_TOKEN or not token.isascii():
        raise DesktopTokenError(f"the desktop token must be at least {MIN_TOKEN} ASCII characters")
    return token


def take_token_from_env() -> str | None:
    """The shell's token, removed from this process's environment (invariant 11). Unset:
    None (developers, tests). Set but empty or short: an error, never "no protection"."""
    if ENV_TOKEN not in os.environ:
        return None
    return checked(os.environ.pop(ENV_TOKEN))


def read_token(stream: TextIO) -> str:
    """The shell's token from the first line of stdin (``serve --token-stdin``): not in
    the environment, where same-user tools such as ``ps eww`` could read it. The shell
    then keeps stdin open as a lifeline: when it closes, ``serve`` stops (ADR 0060)."""
    return checked(stream.readline())


class DesktopAccess:
    def __init__(self, token: str | None) -> None:
        self._token = token
        self._sessions: set[str] = set()
        self._lock = threading.Lock()

    @property
    def enforced(self) -> bool:
        return self._token is not None

    def bearer_ok(self, authorization: str | None) -> bool:
        if self._token is None or not authorization:
            return False
        scheme, _, value = authorization.partition(" ")
        return scheme.lower() == "bearer" and hmac.compare_digest(
            value.strip().encode(), self._token.encode()
        )

    def new_session(self) -> str:
        sid = secrets.token_urlsafe(32)
        with self._lock:
            self._sessions.add(sid)
        return sid

    def session_ok(self, cookie: str | None, fetch_site: str | None) -> bool:
        if not cookie or (fetch_site or "").lower() not in SAME_ORIGIN:
            return False
        with self._lock:
            return any(hmac.compare_digest(cookie.encode(), s.encode()) for s in self._sessions)

    def allows(self, authorization: str | None, cookie: str | None, fetch_site: str | None) -> bool:
        if not self.enforced:
            return True
        return self.bearer_ok(authorization) or self.session_ok(cookie, fetch_site)
