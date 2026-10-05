"""Adapter protocol. Only ``ai/adapters/<provider>/`` may import a provider SDK (ADR 0003)."""

from __future__ import annotations

from typing import Any, Protocol

from mosaic.ai.types import AdapterLimits, RawCompletion, StructuredRequest


class Adapter(Protocol):
    provider: str

    def limits(self, model: str) -> AdapterLimits: ...

    def cost_usd(self, model: str, tokens_in: int, tokens_out: int) -> float: ...

    def estimate_tokens(self, request: StructuredRequest) -> tuple[int, int]:
        """Upper-bound (input, output) tokens for the budget check before a call."""
        ...

    def complete(
        self,
        request: StructuredRequest,
        model: str,
        json_schema: dict[str, Any],
        feedback: str | None,
    ) -> RawCompletion:
        """Answer ``request`` as JSON matching ``json_schema``. ``feedback`` carries the
        previous attempt's validation errors on the single retry."""
        ...


_DROP = frozenset(
    {
        "minimum",
        "maximum",
        "exclusiveMinimum",
        "exclusiveMaximum",
        "multipleOf",
        "minLength",
        "maxLength",
        "pattern",
        "minItems",
        "maxItems",
        "title",
        "default",
    }
)
_NAME_MAPS = ("properties", "$defs", "definitions", "patternProperties")


def strict_schema(schema: dict[str, Any]) -> dict[str, Any]:
    """A JSON schema accepted by structured-output APIs: every object closed
    (``additionalProperties: false``), unsupported numeric/string bounds removed.
    Pydantic still validates the full constraints on our side (invariant 6).

    Keywords are removed only from schema nodes; the keys of ``properties`` and ``$defs``
    are field and definition *names* and are always kept (a field may be called ``title``).
    """

    def node(n: Any) -> Any:
        if isinstance(n, list):
            return [node(v) for v in n]
        if not isinstance(n, dict):
            return n
        out: dict[str, Any] = {}
        for k, v in n.items():
            if k in _NAME_MAPS and isinstance(v, dict):
                out[k] = {name: node(sub) for name, sub in v.items()}
            elif k in _DROP:
                continue
            else:
                out[k] = node(v)
        if out.get("type") == "object" or "properties" in out:
            out["additionalProperties"] = False
            out.setdefault("required", list(out.get("properties", {})))
        return out

    result: dict[str, Any] = node(schema)
    return result


def estimate_text_tokens(*texts: str) -> int:
    return sum(len(t) for t in texts) // 3 + 16
