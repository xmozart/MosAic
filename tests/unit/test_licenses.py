"""Acceptance 6: LICENSES.md lists every dependency, and none is GPL/AGPL."""

from __future__ import annotations

import re
import tomllib
from importlib import metadata
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
FORBIDDEN = re.compile(r"\b(A?GPL|GNU General Public|Affero|SSPL|Non-?Commercial)", re.I)
LESSER = re.compile(r"LGPL|Lesser", re.I)


def _locked_packages() -> set[str]:
    lock = tomllib.loads((ROOT / "uv.lock").read_text())
    return {p["name"] for p in lock["package"] if p["name"] != "mosaic"}


def _listed() -> str:
    return (ROOT / "LICENSES.md").read_text().lower()


def test_every_locked_package_is_listed() -> None:
    listed = _listed()
    missing = sorted(n for n in _locked_packages() if f"| {n.lower()} |" not in listed)
    assert not missing, f"add to LICENSES.md: {missing}"


def test_installed_packages_are_not_gpl() -> None:
    offenders: list[str] = []
    for name in _locked_packages():
        try:
            meta = metadata.metadata(name)
        except metadata.PackageNotFoundError:
            continue  # platform-specific package not installed here
        texts = [meta.get("License-Expression") or "", meta.get("License") or ""]
        texts += [c for c in meta.get_all("Classifier") or [] if c.startswith("License")]
        joined = " ".join(t[:200] for t in texts)
        if FORBIDDEN.search(joined) and not LESSER.search(joined):
            offenders.append(f"{name}: {joined[:120]}")
    assert not offenders, offenders


GPL_NATIVE = re.compile(
    r"(^|/)lib(x264|x265|postproc|xvidcore|vidstab|rubberband|fdk-aac)[.-]", re.I
)


def test_no_bundled_gpl_media_libraries() -> None:
    """Package metadata can say Apache/BSD while a wheel bundles a GPL FFmpeg (as the macOS
    opencv-python wheels do, ADR 0008). Scan installed native libraries directly."""
    import sysconfig

    paths = sysconfig.get_paths()
    sites = {Path(paths["purelib"]), Path(paths["platlib"])}
    offenders: list[str] = []
    for site in sites:
        for p in site.rglob("*"):
            native = p.suffix in (".dylib", ".so", ".dll") or ".so." in p.name
            if not native:
                continue
            if GPL_NATIVE.search(p.as_posix()):
                offenders.append(str(p.relative_to(site)))
            # Our only FFmpeg is the external LGPL build: a bundled copy (which could have
            # GPL encoders linked statically) is not allowed either.
            if re.search(r"(^|/)libav(codec|format)[.-]", p.as_posix()):
                offenders.append(str(p.relative_to(site)))
    assert not offenders, offenders
