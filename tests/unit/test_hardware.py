"""Hardware probe and worker slots (M1 step 12, ADR 0030)."""

from __future__ import annotations

from dataclasses import replace

from mosaic.jobs.worker import GB, default_slots
from mosaic.media.hardware import Hardware, probe

MAC = Hardware(
    os="darwin",
    arch="arm64",
    cpu_model="Apple M4",
    cpu_logical=10,
    cpu_physical=10,
    cpu_performance=4,
    memory_bytes=32 * GB,
    hw_encoders=("h264_videotoolbox",),
)


def test_probe_describes_this_computer() -> None:
    hw = probe()
    assert hw.cpu_logical >= 1
    assert hw.memory_bytes is None or hw.memory_bytes > GB
    assert len(hw.fingerprint) == 16
    assert hw.as_json()["fingerprint"] == hw.fingerprint
    assert all(any(m in e for m in ("videotoolbox", "nvenc", "qsv", "amf")) for e in hw.hw_encoders)


def test_fingerprint_changes_with_the_machine() -> None:
    assert MAC.fingerprint == replace(MAC).fingerprint
    assert MAC.fingerprint != replace(MAC, memory_bytes=16 * GB).fingerprint


def test_slots_follow_cores_memory_and_encoders() -> None:
    assert default_slots(MAC) == {"cpu": 5, "gpu_encode": 2, "ai_api": 4, "io": 2}
    small = replace(MAC, cpu_logical=16, memory_bytes=6 * GB, hw_encoders=())
    slots = default_slots(small)
    assert slots["cpu"] == 3, "memory caps CPU slots at one per 2 GB"
    assert slots["gpu_encode"] == 1, "software encoding"
    assert default_slots(replace(MAC, cpu_logical=2))["cpu"] == 2
    assert default_slots(MAC, {"cpu": 9, "io": 0})["cpu"] == 9
    assert default_slots(MAC, {"cpu": 9, "io": 0})["io"] == 2, "0 keeps the default"
