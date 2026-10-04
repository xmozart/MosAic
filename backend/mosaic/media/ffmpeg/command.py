"""Typed FFmpeg command model.

This package is the only place where FFmpeg/ffprobe argv lists are assembled
(CLAUDE.md code conventions). Other modules call the builder functions in
``mosaic.media.ffmpeg.builders`` and receive an ``FFmpegCommand``.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from fractions import Fraction
from pathlib import Path

OptionValue = str | int | Fraction | None


def _fmt(value: OptionValue) -> str | None:
    if value is None:
        return None
    if isinstance(value, Fraction):
        return f"{value.numerator}/{value.denominator}"
    return str(value)


def _option_args(options: Sequence[tuple[str, OptionValue]]) -> list[str]:
    args: list[str] = []
    for flag, value in options:
        args.append(flag)
        formatted = _fmt(value)
        if formatted is not None:
            args.append(formatted)
    return args


def media_path(path: Path) -> str:
    """An unambiguous FFmpeg URL for a local file.

    Absolute path with the ``file:`` protocol, so names starting with ``-`` or containing
    ``name:`` are never parsed as options or protocols.
    """
    return "file:" + str(path.resolve())


def _local(target: str) -> str | None:
    if target.startswith("file:"):
        return str(Path(target[5:]).resolve())
    if target.startswith("pipe:") or target == "-" or ":" in target.split("/")[0]:
        return None
    return str(Path(target).resolve())


class UnsafeCommandError(ValueError):
    """An output would overwrite one of the command's inputs (protects originals)."""


def escape_filter_value(value: str) -> str:
    """Escape a value for use inside a filtergraph option (``key=value``)."""
    out = value.replace("\\", "\\\\").replace("'", "\\'").replace(":", "\\:")
    return out.replace(",", "\\,").replace("[", "\\[").replace("]", "\\]").replace(";", "\\;")


@dataclass(frozen=True)
class Filter:
    """One filter, e.g. ``Filter("scale", w=1280, h=-2)`` → ``scale=w=1280:h=-2``."""

    name: str
    args: tuple[tuple[str, OptionValue], ...] = ()
    positional: tuple[str, ...] = ()

    @classmethod
    def of(cls, name: str, *positional: str, **kwargs: OptionValue) -> Filter:
        return cls(name=name, args=tuple(kwargs.items()), positional=positional)

    def render(self) -> str:
        parts = list(self.positional)
        for key, value in self.args:
            formatted = _fmt(value)
            if formatted is None:
                continue
            parts.append(f"{key}={formatted}")
        return self.name if not parts else f"{self.name}={':'.join(parts)}"


@dataclass(frozen=True)
class Chain:
    """A linear filter chain with optional input and output pad labels."""

    filters: tuple[Filter, ...]
    inputs: tuple[str, ...] = ()
    outputs: tuple[str, ...] = ()

    def render(self) -> str:
        ins = "".join(f"[{p}]" for p in self.inputs)
        outs = "".join(f"[{p}]" for p in self.outputs)
        body = ",".join(f.render() for f in self.filters) or "null"
        return f"{ins}{body}{outs}"


def chain(*filters: Filter) -> str:
    return ",".join(f.render() for f in filters)


def graph(chains: Iterable[Chain]) -> str:
    return ";".join(c.render() for c in chains)


@dataclass
class InputSpec:
    path: str
    options: list[tuple[str, OptionValue]] = field(default_factory=list)


@dataclass
class OutputSpec:
    path: str
    options: list[tuple[str, OptionValue]] = field(default_factory=list)


@dataclass
class FFmpegCommand:
    """A complete ffmpeg invocation; ``argv`` renders it for a given binary."""

    inputs: list[InputSpec]
    outputs: list[OutputSpec]
    global_options: list[tuple[str, OptionValue]] = field(default_factory=list)
    filter_complex: str | None = None
    tool: str = "ffmpeg"
    stdin_data: bytes | None = None
    description: str = ""

    def check_safe(self) -> None:
        ins = {p for p in (_local(i.path) for i in self.inputs) if p}
        for out in self.outputs:
            target = _local(out.path)
            if target and target in ins:
                raise UnsafeCommandError(f"output {target} is also an input")

    def argv(self, binary: Path) -> list[str]:
        self.check_safe()
        args: list[str] = [str(binary), "-hide_banner", "-nostdin"]
        if self.tool == "ffmpeg":
            args += ["-y", "-loglevel", "error"]
        args += _option_args(self.global_options)
        for inp in self.inputs:
            args += _option_args(inp.options)
            args += ["-i", inp.path]
        if self.filter_complex is not None:
            args += ["-filter_complex", self.filter_complex]
        for out in self.outputs:
            args += _option_args(out.options)
            args.append(out.path)
        return args

    def uses_stdin(self) -> bool:
        return any(i.path in ("pipe:0", "-") for i in self.inputs)


@dataclass
class ProbeCommand:
    """An ffprobe invocation."""

    args: list[str]
    tool: str = "ffprobe"
    description: str = ""

    def argv(self, binary: Path) -> list[str]:
        return [str(binary), "-hide_banner", "-loglevel", "error", *self.args]
