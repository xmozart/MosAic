"""The assembly key (ADR 0083): a render reuses an earlier file only when everything that
makes the file is the same."""

from __future__ import annotations

from typing import Any

from mosaic.render import plan
from mosaic.render.plan import Profile, assembly_key

FINAL = Profile("final", 1920, 1080, "h264_videotoolbox", "14M")


def _key(**over: Any) -> str:
    args: dict[str, Any] = {
        "project_id": "p",
        "chunks": ["c1", "c2", "c3"],
        "audio": ["a1", "a2", "a3"],
        "music": {"path": "/m.mp3", "size": 10, "mtime_ns": 5, "duck": [[0, 90]]},
        "prof": FINAL,
        "rate": "30000/1001",
        "frames": 900,
    } | over
    return assembly_key(**args)


def test_any_change_to_what_makes_the_file_changes_the_key(monkeypatch: Any) -> None:
    base = _key()
    assert _key() == base, "deterministic"
    music = {"path": "/m.mp3", "size": 10, "mtime_ns": 5, "duck": [[0, 90]]}
    changed = [
        _key(chunks=["c2", "c1", "c3"]),
        _key(audio=["a1", "a2", "a9"]),
        _key(audio=[]),
        _key(music=music | {"size": 11}),
        _key(music=music | {"mtime_ns": 6}),
        _key(music=music | {"duck": [[0, 120]]}),
        _key(music=None),
        _key(prof=Profile("preview", 1280, 720, "h264_videotoolbox", "5M")),
        _key(prof=Profile("final", 1920, 1080, "ffv1", "14M", lossless=True)),
        _key(rate="25/1"),
        _key(frames=901),
    ]
    assert len({base, *changed}) == len(changed) + 1
    monkeypatch.setattr(plan, "ASSEMBLY_VERSION", "assembly/2")
    assert _key() != base, "a new assembler never reuses an old file"


def test_a_changed_dialogue_intent_reaches_the_music_signature() -> None:
    """The duck follows the events' audio intents, which chunk keys don't carry."""
    from types import SimpleNamespace

    from mosaic.render.tasks import _music_signature

    def version(intent: str) -> Any:
        event = {
            "timeline_in": {"frames": 0, "rate": "30/1"},
            "timeline_out": {"frames": 90, "rate": "30/1"},
            "audio": {"intent": intent, "source_enabled": True},
        }
        return SimpleNamespace(
            rate="30/1",
            request={"music": {"path": "/nowhere/song.mp3", "level_db": -18}},
            timeline={"tracks": [{"events": [event]}]},
        )

    talk, ambient = (
        _music_signature(version("dialogue")),
        _music_signature(version("natural_sound")),
    )
    assert talk is not None
    assert ambient is not None
    assert talk["duck"] == [[0, 90]]
    assert ambient["duck"] == []
    assert _music_signature(SimpleNamespace(rate="30/1", request={}, timeline={})) is None
