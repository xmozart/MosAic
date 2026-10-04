"""Shared quality helpers."""

from __future__ import annotations


def shake_metric_name(names: set[str]) -> str:
    """Gyro shake (``shake_gyro``) when the asset has telemetry, optical-flow ``shake``
    otherwise (ARCHITECTURE.md §8 stage 6)."""
    return "shake_gyro" if "shake_gyro" in names else "shake"
