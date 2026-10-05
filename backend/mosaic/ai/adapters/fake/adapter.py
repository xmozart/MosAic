"""Fake/replay adapter (ADR 0002 H): deterministic, offline, free. Used by all tests and CI.

Answers come from, in order: a recording in ``$MOSAIC_AI_REPLAY_DIR`` keyed by the request
hash (so real responses can be replayed in regression tests), or the responder registered
for the prompt, which builds a valid answer from the request's structured ``context``.
"""

from __future__ import annotations

import json
import os
import threading
from collections.abc import Callable
from pathlib import Path
from typing import Any

from mosaic.ai.adapters.base import estimate_text_tokens
from mosaic.ai.types import AdapterError, AdapterLimits, RawCompletion, StructuredRequest
from mosaic.core.keys import digest

PROVIDER = "fake"
ENV_REPLAY = "MOSAIC_AI_REPLAY_DIR"
ENV_COST = "MOSAIC_FAKE_COST_USD"  # tests only

Responder = Callable[[StructuredRequest], dict[str, Any]]
RESPONDERS: dict[str, Responder] = {}
CALLS: list[str] = []  # prompt names of every completed call, for tests
_lock = threading.Lock()


def responder(prompt_name: str) -> Callable[[Responder], Responder]:
    def register(fn: Responder) -> Responder:
        RESPONDERS[prompt_name] = fn
        return fn

    return register


def request_hash(request: StructuredRequest, model: str) -> str:
    return digest(
        {
            "model": model,
            "prompt": [request.prompt_name, request.prompt_version],
            "system": request.system,
            "user": request.user_text,
            "images": [digest(img.data.hex()) for img in request.images],
        }
    )


def limits(model: str) -> AdapterLimits:
    return AdapterLimits(
        max_image_px=1568,
        max_images=20,
        supports_video=False,
        structured_output=True,
        context_window=200_000,
        local=True,
    )


class FakeAdapter:
    provider = PROVIDER

    def limits(self, model: str) -> AdapterLimits:
        return limits(model)

    def cost_usd(self, model: str, tokens_in: int, tokens_out: int) -> float:
        # Free, unless a test sets a per-call price to exercise budgets (worker
        # subprocesses inherit the environment, not monkeypatches).
        try:
            return float(os.environ.get(ENV_COST, "0") or 0)
        except ValueError:
            return 0.0

    def estimate_tokens(self, request: StructuredRequest) -> tuple[int, int]:
        return estimate_text_tokens(request.system, request.user_text), request.max_tokens

    def complete(
        self,
        request: StructuredRequest,
        model: str,
        json_schema: dict[str, Any],
        feedback: str | None,
    ) -> RawCompletion:
        replay = os.environ.get(ENV_REPLAY)
        if replay:
            path = Path(replay) / f"{request_hash(request, model)}.json"
            if path.is_file():
                text = path.read_text()
                return self._done(request, text, model)
        fn = RESPONDERS.get(request.prompt_name)
        if fn is None:
            raise AdapterError(
                f"fake adapter has no responder for {request.prompt_name!r}", retryable=False
            )
        answer = fn(request)
        if request.context.get("_fake_invalid_first") and feedback is None:
            answer = {"invalid": True}  # exercise the validate-and-retry path
        if request.context.get("_fake_always_invalid"):
            answer = {"invalid": True}
        return self._done(request, json.dumps(answer), model)

    def _done(self, request: StructuredRequest, text: str, model: str) -> RawCompletion:
        with _lock:
            CALLS.append(request.prompt_name)
        tokens_in, _ = self.estimate_tokens(request)
        return RawCompletion(
            text=text,
            tokens_in=tokens_in,
            tokens_out=len(text) // 3,
            model=model,
            latency_ms=0,
            stop_reason="end_turn",
        )


@responder("healthcheck")
def _healthcheck(_request: StructuredRequest) -> dict[str, Any]:
    return {"ok": True}


@responder("vision")
def _vision(request: StructuredRequest) -> dict[str, Any]:
    """One neutral observation per listed segment; tests override for specific answers."""
    return {
        "segments": [
            {
                "segment": seg["ref"],
                "description": f"Footage from {request.context['asset']}, segment {seg['ref']}.",
                "subjects": ["scene"],
                "shot_type": "wide",
                "camera_motion": "static",
                "people": "none",
                "interest": "medium",
                "composition": "good",
                "issues": [],
                "usable": True,
                "best_tile": seg["tiles"][len(seg["tiles"]) // 2],
            }
            for seg in request.context["segments"]
        ]
    }


@responder("planner")
def _planner(request: StructuredRequest) -> dict[str, Any]:
    """Chronological beats over consecutive slices of the candidates, equal shares."""
    refs: list[str] = list(request.context["candidate_refs"])
    k = max(1, min(2 if request.context["duration_s"] <= 60 else 3, len(refs)))
    size = -(-len(refs) // k)
    shares = [100 // k] * k
    shares[-1] += 100 - sum(shares)
    beats = [
        {
            "beat_id": f"b{i + 1}",
            "title": f"Part {i + 1}",
            "intent": f"Part {i + 1} of the trip, in order.",
            "share_percent": shares[i],
            "candidates": refs[i * size : (i + 1) * size] or refs[-1:],
        }
        for i in range(k)
    ]
    return {"title": "Trip film", "beats": beats}


def _round_robin(pool: list[str], assets: dict[str, int]) -> list[str]:
    """One clip per recording first, then the next of each: variety, as a selector would."""
    by_asset: dict[int, list[str]] = {}
    for ref in pool:
        by_asset.setdefault(assets.get(ref, 0), []).append(ref)
    out: list[str] = []
    while any(by_asset.values()):
        for queue in by_asset.values():
            if queue:
                out.append(queue.pop(0))
    return out


@responder("selector")
def _selector(request: StructuredRequest) -> dict[str, Any]:
    """Round-robin over recordings: the first clip of each recording is essential (priority
    5), extra clips are optional; a few more than suggested; no clip used twice."""
    speech = set(request.context.get("speech_refs", []))
    assets: dict[str, int] = request.context.get("candidate_assets", {})
    used: set[str] = set()
    beats = []
    for pool in request.context["beat_pools"]:
        free = _round_robin([r for r in pool["pool"] if r not in used], assets)
        distinct = len({assets.get(r, 0) for r in free})
        picked = free[: max(pool["shots"] + 2, distinct)] or free[:1]
        used.update(picked)
        spare = [r for r in free if r not in picked]
        seen_assets: set[int] = set()
        selections = []
        for n, r in enumerate(picked):
            first = assets.get(r, 0) not in seen_assets
            seen_assets.add(assets.get(r, 0))
            selections.append(
                {
                    "segment_id": r,
                    "role": "establishing" if n == 0 else "b_roll",
                    "priority": 5 if first else max(1, 4 - n // 4),
                    "length": "medium",
                    "audio_intent": "dialogue" if r in speech else "natural_sound",
                    "reason": f"Shot {n + 1} of {pool['beat_id']}.",
                    "alternatives": [
                        {"segment_id": a, "why_not": "Kept as a spare."} for a in spare[:1]
                    ],
                }
            )
        beats.append({"beat_id": pool["beat_id"], "selections": selections})
    return {"beats": beats}


@responder("review")
def _review(request: StructuredRequest) -> dict[str, Any]:
    """A neutral full-resolution observation that keeps the quick description."""
    return {
        "description": f"Reviewed at full resolution: {request.context.get('l2_description', '')}"[
            :290
        ],
        "subjects": ["scene"],
        "shot_type": "wide",
        "camera_motion": "static",
        "people": "none",
        "interest": "medium",
        "composition": "good",
        "issues": [],
        "usable": True,
        "best_frame": "F2",
        "main_subject_visible": False,
    }


@responder("context_parse")
def _context_parse(request: StructuredRequest) -> dict[str, Any]:
    """Keeps the notes as free notes; never invents names, dates or places."""
    return {
        "trip_name": "",
        "home_timezone": None,
        "days": [],
        "people": [],
        "must_include": [],
        "avoid": [],
        "free_notes": str(request.context.get("text", ""))[:300],
    }
