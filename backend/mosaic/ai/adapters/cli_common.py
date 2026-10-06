"""Shared plumbing for adapters that drive an installed AI command-line app (ADR 0014).

The app runs as a subprocess in a fresh empty folder, with no tools, using the user's own
login (no API key): prompts and images go through stdin or temporary files, never argv
(argv is visible to other processes). API-key variables are removed from the child's
environment so the app always uses the signed-in subscription the user chose.
"""

from __future__ import annotations

import contextlib
import os
import shutil
import signal
import subprocess
import tempfile
import time
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

from mosaic.ai.types import AdapterError

DEFAULT_TIMEOUT_S = 300.0
RATE_LIMIT_HINTS = ("rate limit", "rate_limit", "429", "overloaded", "usage limit", "try again")


@dataclass(frozen=True)
class CliRun:
    stdout: str
    stderr: str
    returncode: int
    latency_ms: int


def find_binary(name: str, configured: str) -> str:
    """The configured path, or ``name`` on PATH; ``AdapterError`` naming the fix."""
    if configured:
        path = Path(configured).expanduser()
        if path.is_file() and os.access(path, os.X_OK):
            return str(path)
        raise AdapterError(
            f"{name} not found at {path}; fix `mosaic config set ai.cli.{name}_path <path>`",
            retryable=False,
        )
    found = shutil.which(name)
    if found is None:
        raise AdapterError(
            f"the {name} app is not installed or not on PATH; install it, sign in, or set "
            f"`mosaic config set ai.cli.{name}_path <path>`",
            retryable=False,
        )
    return found


@contextmanager
def workdir() -> Iterator[Path]:
    """An empty, private folder: the app sees no project files or instruction files."""
    with tempfile.TemporaryDirectory(prefix="mosaic-ai-") as tmp:
        yield Path(tmp)


def run(
    argv: Sequence[str],
    stdin: str,
    cwd: Path,
    timeout_s: float,
    drop_env: Sequence[str],
) -> CliRun:
    from mosaic.core.runtime import scrubbed_env

    # The app gets neither its own API-key variables (drop_env) nor any MosAic secret.
    env = {k: v for k, v in scrubbed_env().items() if k not in drop_env}
    # Own process group, so a timeout also stops the app's helper processes.
    group: dict[str, object] = (
        {"creationflags": getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)}
        if os.name == "nt"
        else {"start_new_session": True}
    )
    started = time.monotonic()
    try:
        proc = subprocess.Popen(  # fixed argv built by the adapter, no shell
            list(argv),
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            cwd=cwd,
            env=env,
            **group,  # type: ignore[call-overload]
        )
    except OSError as exc:
        raise AdapterError(f"could not start {argv[0]}: {exc.strerror}", retryable=False) from None
    try:
        stdout, stderr = proc.communicate(stdin, timeout=timeout_s)
    except subprocess.TimeoutExpired:
        _kill_tree(proc)
        name = Path(argv[0]).name
        raise AdapterError(f"{name} timed out after {timeout_s:.0f} s", retryable=True) from None
    latency = int((time.monotonic() - started) * 1000)
    return CliRun(stdout, stderr, proc.returncode, latency)


def _kill_tree(proc: subprocess.Popen[str]) -> None:
    if os.name == "nt":
        proc.kill()
    else:
        with contextlib.suppress(ProcessLookupError):
            os.killpg(proc.pid, signal.SIGKILL)
    # A helper that left the group could still hold the pipes: never wait for long.
    with contextlib.suppress(subprocess.TimeoutExpired):
        proc.communicate(timeout=5)


def classify(app: str, message: str, login_hint: str) -> AdapterError:
    low = message.lower()
    if any(
        w in low for w in ("log in", "login", "not logged", "authenticat", "unauthorized", "/login")
    ):
        return AdapterError(f"{app} is not signed in: {login_hint}", retryable=False)
    retryable = any(h in low for h in RATE_LIMIT_HINTS)
    return AdapterError(f"{app} failed: {message[:400]}", retryable=retryable)
