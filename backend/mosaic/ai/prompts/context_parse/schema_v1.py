"""Output schema for context_parse v1: the TripContext structure (PRODUCT.md §3).

Bound to the stored model on purpose: the parsed proposal must be exactly what can be
saved. Any change to ``TripContext`` therefore requires context_parse v2 (and the AI cache
key, which hashes the schema, already changes with it)."""

from __future__ import annotations

from mosaic.library.context import TripContext as Output

__all__ = ["Output"]
