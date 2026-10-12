"""Output schema for reselect v2: the same as v1 (the prompt gained a directive and the
owner's preferences; ADR 0074)."""

from __future__ import annotations

from mosaic.ai.prompts.reselect.schema_v1 import Output

__all__ = ["Output"]
