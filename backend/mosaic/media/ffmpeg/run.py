"""Execute FFmpeg commands built by this package, logging command, stderr and duration."""

from __future__ import annotations

import logging
import subprocess
import threading
import time
from collections.abc import Callable, Iterable, Iterator
from dataclasses import dataclass
from pathlib import Path

from mosaic.core.runtime import scrubbed_env
from mosaic.media.ffmpeg.capabilities import FFmpegBinaries
from mosaic.media.ffmpeg.command import FFmpegCommand, ProbeCommand

log = logging.getLogger("mosaic.ffmpeg")

STDERR_TAIL = 4000


class FFmpegError(RuntimeError):
    def __init__(self, message: str, argv: list[str], returncode: int, stderr: str) -> None:
        super().__init__(f"{message} (exit {returncode}): {stderr[-600:].strip()}")
        self.argv = argv
        self.returncode = returncode
        self.stderr = stderr


@dataclass(frozen=True)
class RunResult:
    argv: list[str]
    returncode: int
    stdout: bytes
    stderr: str
    duration_ms: int


DiagnosticsSink = Callable[[RunResult], None]
_sinks: list[DiagnosticsSink] = []


def add_diagnostics_sink(sink: DiagnosticsSink) -> None:
    _sinks.append(sink)


def remove_diagnostics_sink(sink: DiagnosticsSink) -> None:
    if sink in _sinks:
        _sinks.remove(sink)


def _binary(binaries: FFmpegBinaries, tool: str) -> Path:
    return binaries.ffprobe if tool == "ffprobe" else binaries.ffmpeg


def run(
    binaries: FFmpegBinaries,
    command: FFmpegCommand | ProbeCommand,
    *,
    check: bool = True,
    timeout: float | None = None,
    stdin: bytes | None = None,
) -> RunResult:
    argv = command.argv(_binary(binaries, command.tool))
    data = stdin if stdin is not None else getattr(command, "stdin_data", None)
    started = time.monotonic()
    proc = subprocess.run(
        argv,
        env=scrubbed_env(),
        input=data,
        capture_output=True,
        check=False,
        timeout=timeout,
        stdin=None if data is not None else subprocess.DEVNULL,
    )
    duration_ms = int((time.monotonic() - started) * 1000)
    stderr = proc.stderr.decode("utf-8", "replace")
    result = RunResult(argv, proc.returncode, proc.stdout, stderr[-STDERR_TAIL:], duration_ms)
    log.info(
        "ffmpeg",
        extra={"argv": argv, "returncode": proc.returncode, "duration_ms": duration_ms},
    )
    for sink in list(_sinks):
        sink(result)
    if check and proc.returncode != 0:
        desc = getattr(command, "description", "") or command.tool
        raise FFmpegError(desc, argv, proc.returncode, stderr)
    return result


def run_streaming_stdin(
    binaries: FFmpegBinaries, command: FFmpegCommand, chunks: Iterable[bytes]
) -> RunResult:
    """Run ffmpeg feeding ``chunks`` to stdin (raw frames).

    stderr is drained on a thread so a chatty process cannot deadlock the pipe.
    """
    argv = command.argv(_binary(binaries, command.tool))
    started = time.monotonic()
    proc = subprocess.Popen(argv, stdin=subprocess.PIPE, stderr=subprocess.PIPE, env=scrubbed_env())
    stdin, stderr_pipe = proc.stdin, proc.stderr
    assert stdin is not None
    assert stderr_pipe is not None
    err_chunks: list[bytes] = []
    reader = threading.Thread(target=lambda: err_chunks.append(stderr_pipe.read()))
    reader.start()
    try:
        for chunk in chunks:
            stdin.write(chunk)
        stdin.close()
    except BrokenPipeError:
        pass  # ffmpeg exited early; stderr explains why
    returncode = proc.wait()
    reader.join()
    stderr = b"".join(err_chunks).decode("utf-8", "replace")
    duration_ms = int((time.monotonic() - started) * 1000)
    result = RunResult(argv, returncode, b"", stderr[-STDERR_TAIL:], duration_ms)
    log.info("ffmpeg", extra={"argv": argv, "returncode": returncode, "duration_ms": duration_ms})
    for sink in list(_sinks):
        sink(result)
    if returncode != 0:
        raise FFmpegError(command.description or "ffmpeg", argv, returncode, stderr)
    return result


def stream_stdout(
    binaries: FFmpegBinaries,
    command: FFmpegCommand,
    chunk_size: int,
    *,
    partial_tail: bool = False,
) -> Iterator[bytes]:
    """Yield stdout in fixed-size chunks (e.g. one raw frame each) without buffering the
    whole output (invariant 13). A short final read is dropped (half a video frame), unless
    ``partial_tail`` (audio samples: the last part of a second still counts). Raises
    ``FFmpegError`` if the process fails."""
    argv = command.argv(_binary(binaries, command.tool))
    started = time.monotonic()
    proc = subprocess.Popen(
        argv,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        stdin=subprocess.DEVNULL,
        env=scrubbed_env(),
    )
    out, err_pipe = proc.stdout, proc.stderr
    assert out is not None
    assert err_pipe is not None
    err_chunks: list[bytes] = []
    reader = threading.Thread(target=lambda: err_chunks.append(err_pipe.read()))
    reader.start()
    try:
        while True:
            buf = out.read(chunk_size)
            if not buf:
                break
            if len(buf) < chunk_size:  # short read at EOF only
                rest = out.read(chunk_size - len(buf))
                buf += rest
                if len(buf) < chunk_size:
                    if partial_tail and buf:
                        yield buf
                    break
            yield buf
    finally:
        if proc.poll() is None:
            out.close()
        returncode = proc.wait()
        reader.join()
        stderr = b"".join(err_chunks).decode("utf-8", "replace")
        result = RunResult(
            argv, returncode, b"", stderr[-STDERR_TAIL:], int((time.monotonic() - started) * 1000)
        )
        for sink in list(_sinks):
            sink(result)
    if returncode != 0:
        raise FFmpegError(command.description or "ffmpeg", argv, returncode, stderr)
