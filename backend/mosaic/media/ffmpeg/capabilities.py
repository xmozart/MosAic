"""FFmpeg binary location plus capability and license probe (ADR 0002 item B)."""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from dataclasses import dataclass, field
from enum import StrEnum
from functools import lru_cache
from pathlib import Path

REPO_TOOLS_DIR = Path(__file__).resolve().parents[4] / ".tools" / "ffmpeg" / "bin"
ENV_DIR = "MOSAIC_FFMPEG_DIR"

ENCODER_PREFERENCE: tuple[str, ...] = ("h264_videotoolbox", "h264_nvenc", "libopenh264")
"""H.264 encoder order: VideoToolbox → NVENC → openh264 (ADR 0002 B)."""


class FFmpegLicense(StrEnum):
    LGPL = "lgpl"
    GPL = "gpl"
    NONFREE = "nonfree"


class FFmpegNotFoundError(RuntimeError):
    pass


class FFmpegLicenseError(RuntimeError):
    pass


@dataclass(frozen=True)
class FFmpegBinaries:
    ffmpeg: Path
    ffprobe: Path


@dataclass(frozen=True)
class Capabilities:
    version: str
    license: FFmpegLicense
    configuration: tuple[str, ...]
    encoders: frozenset[str] = field(default_factory=frozenset)
    decoders: frozenset[str] = field(default_factory=frozenset)
    filters: frozenset[str] = field(default_factory=frozenset)

    def has_encoder(self, name: str) -> bool:
        return name in self.encoders

    def has_filter(self, name: str) -> bool:
        return name in self.filters

    def h264_encoders(self) -> list[str]:
        return [e for e in ENCODER_PREFERENCE if e in self.encoders]

    @property
    def can_tonemap(self) -> bool:
        return self.has_filter("zscale") and self.has_filter("tonemap")


def locate(ffmpeg_dir: str | Path | None = None) -> FFmpegBinaries:
    """Find ffmpeg/ffprobe: explicit dir → $MOSAIC_FFMPEG_DIR → repo ``.tools`` → PATH."""
    candidates: list[Path] = []
    if ffmpeg_dir:
        candidates.append(Path(ffmpeg_dir).expanduser())
    env_dir = os.environ.get(ENV_DIR)
    if env_dir:
        candidates.append(Path(env_dir).expanduser())
    candidates.append(REPO_TOOLS_DIR)
    for directory in candidates:
        ff, fp = directory / "ffmpeg", directory / "ffprobe"
        if os.name == "nt":
            ff, fp = ff.with_suffix(".exe"), fp.with_suffix(".exe")
        if ff.is_file() and fp.is_file():
            return FFmpegBinaries(ffmpeg=ff, ffprobe=fp)
    on_path_ff, on_path_fp = shutil.which("ffmpeg"), shutil.which("ffprobe")
    if on_path_ff and on_path_fp:
        return FFmpegBinaries(ffmpeg=Path(on_path_ff), ffprobe=Path(on_path_fp))
    raise FFmpegNotFoundError(
        f"FFmpeg not found. Build the LGPL dev build with scripts/build-ffmpeg.sh or set {ENV_DIR}."
    )


def _run_text(argv: list[str]) -> str:
    from mosaic.storage.secrets import scrubbed_env

    proc = subprocess.run(
        argv, capture_output=True, text=True, check=False, timeout=60, env=scrubbed_env()
    )
    return proc.stdout + proc.stderr


def parse_license(configuration: tuple[str, ...]) -> FFmpegLicense:
    if "--enable-nonfree" in configuration:
        return FFmpegLicense.NONFREE
    if "--enable-gpl" in configuration:
        return FFmpegLicense.GPL
    return FFmpegLicense.LGPL


def _parse_listing(text: str) -> frozenset[str]:
    """Names from ``-encoders``/``-decoders``/``-filters``: second token after ``------``."""
    names: set[str] = set()
    started = False
    for line in text.splitlines():
        if line.strip().startswith("------"):
            started = True
            continue
        if not started:
            continue
        parts = line.split()
        if len(parts) >= 2:
            names.add(parts[1])
    return frozenset(names)


@lru_cache(maxsize=8)
def probe_capabilities(ffmpeg: Path) -> Capabilities:
    base = [str(ffmpeg), "-hide_banner"]
    buildconf = _run_text([*base, "-buildconf"])
    configuration = tuple(tok.strip() for tok in buildconf.split() if tok.strip().startswith("--"))
    version_text = _run_text([str(ffmpeg), "-version"])
    m = re.search(r"ffmpeg version (\S+)", version_text)
    return Capabilities(
        version=m.group(1) if m else "unknown",
        license=parse_license(configuration),
        configuration=configuration,
        encoders=_parse_listing(_run_text([*base, "-encoders"])),
        decoders=_parse_listing(_run_text([*base, "-decoders"])),
        filters=_parse_listing(_run_text([*base, "-filters"])),
    )


def ensure_license_allowed(caps: Capabilities, *, allow_gpl_ffmpeg: bool = False) -> None:
    """Refuse GPL/nonfree builds unless the dev-only ``allow_gpl_ffmpeg`` setting is true."""
    if caps.license is FFmpegLicense.LGPL:
        return
    if caps.license is FFmpegLicense.GPL and allow_gpl_ffmpeg:
        return
    raise FFmpegLicenseError(
        f"FFmpeg {caps.version} is a {caps.license.value.upper()} build. MosAic requires an "
        "LGPL build (scripts/build-ffmpeg.sh). Set allow_gpl_ffmpeg=true only for local "
        "development."
    )
