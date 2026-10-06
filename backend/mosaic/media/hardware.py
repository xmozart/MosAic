"""Hardware capability probe (M1 step 12, ADR 0030).

What this computer has: CPU cores, memory, and which hardware video encoders the FFmpeg
build can use. It sizes the worker pool (ARCHITECTURE.md §3) and identifies the machine
a benchmark was measured on. Probing never fails: a value it cannot read is ``None``.
"""

from __future__ import annotations

import hashlib
import json
import os
import platform
import subprocess
from dataclasses import asdict, dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

HW_ENCODER_MARKERS = ("videotoolbox", "nvenc", "qsv", "amf")
"""Encoder name parts that mean a platform hardware encoder (CLAUDE.md: licensing)."""


@dataclass(frozen=True)
class Hardware:
    os: str
    arch: str
    cpu_model: str | None
    cpu_logical: int
    cpu_physical: int | None
    cpu_performance: int | None  # Apple silicon performance cores
    memory_bytes: int | None
    hw_encoders: tuple[str, ...]  # hardware H.264/HEVC encoders that run here

    @property
    def fingerprint(self) -> str:
        """Identifies the machine for a stored benchmark (not for security)."""
        keys = (self.os, self.arch, self.cpu_model, self.cpu_logical, self.memory_bytes)
        return hashlib.sha256(json.dumps(keys).encode()).hexdigest()[:16]

    def as_json(self) -> dict[str, Any]:
        out = asdict(self)
        out["hw_encoders"] = list(self.hw_encoders)
        out["fingerprint"] = self.fingerprint
        return out


def _sysctl(name: str) -> str | None:
    from mosaic.storage.secrets import scrubbed_env

    try:
        out = subprocess.run(
            ["/usr/sbin/sysctl", "-n", name],
            capture_output=True,
            text=True,
            timeout=5,
            env=scrubbed_env(),
        )
    except (OSError, subprocess.SubprocessError):
        return None
    value = out.stdout.strip()
    return value if out.returncode == 0 and value else None


def _int(value: str | None) -> int | None:
    try:
        return int(value) if value is not None else None
    except ValueError:
        return None


def _linux_cpu() -> tuple[str | None, int | None]:
    try:
        text = Path("/proc/cpuinfo").read_text()
    except OSError:
        return None, None
    model = None
    cores: set[tuple[str, str]] = set()
    phys = core = ""
    for line in text.splitlines():
        key, _, value = line.partition(":")
        key, value = key.strip(), value.strip()
        if key == "model name" and model is None:
            model = value
        elif key == "physical id":
            phys = value
        elif key == "core id":
            core = value
            cores.add((phys, core))
    return model, (len(cores) or None)


def _linux_memory() -> int | None:
    try:
        for line in Path("/proc/meminfo").read_text().splitlines():
            if line.startswith("MemTotal:"):
                return int(line.split()[1]) * 1024
    except (OSError, ValueError, IndexError):
        pass
    return None


def _memory() -> int | None:
    try:
        return os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES")
    except (AttributeError, ValueError, OSError):
        return None


def _hw_encoders() -> tuple[str, ...]:
    try:
        from mosaic.media.tools import working_h264_encoders

        working = working_h264_encoders()
    except Exception:  # no FFmpeg yet: the probe still describes the CPU
        return ()
    return tuple(e for e in working if any(m in e for m in HW_ENCODER_MARKERS))


@lru_cache(maxsize=1)
def probe() -> Hardware:
    system = platform.system().lower()
    logical = os.cpu_count() or 1
    model: str | None = None
    physical = performance = memory = None
    if system == "darwin":
        model = _sysctl("machdep.cpu.brand_string")
        physical = _int(_sysctl("hw.physicalcpu"))
        performance = _int(_sysctl("hw.perflevel0.physicalcpu"))
        memory = _int(_sysctl("hw.memsize"))
    elif system == "linux":
        model, physical = _linux_cpu()
        memory = _linux_memory()
    if memory is None:
        memory = _memory()
    return Hardware(
        os=system,
        arch=platform.machine().lower(),
        cpu_model=model or platform.processor() or None,
        cpu_logical=logical,
        cpu_physical=physical,
        cpu_performance=performance,
        memory_bytes=memory,
        hw_encoders=_hw_encoders(),
    )
