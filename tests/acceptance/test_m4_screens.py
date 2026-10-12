"""M4 acceptance 6: every M4 screen state is a story, rendered and compared in both
themes, and every endpoint `docs/ui/API_MAP.md` lists for an M4 screen is served.

The visual test (`npm run visual`, in `make ci`) compares each story's render with its
committed baselines in both themes; this test closes the other side: a state the screen
docs list with no story (so no baseline), or a documented M4 endpoint the server lacks.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tests.acceptance.test_m2_openapi import _segments, _served, documented_m2_endpoints

pytestmark = [pytest.mark.acceptance]

ROOT = Path(__file__).resolve().parents[2]
M4_SCREENS = {"S13", "S14", "S15", "S16", "S17", "S18", "S19", "S24"}

# Each state the screen docs list (its first words) → the stories that show it (Storybook
# ids: title-slug--story-slug), or the ADR saying why it has none.
STATES: dict[str, dict[str, list[str] | str]] = {
    "S13": {
        "Empty": ["screens-s13-s14-edits--edits-empty"],
        "Generating": ["screens-s13-s14-edits--edits-grid"],
        "Preliminary": ["screens-s13-s14-edits--edits-grid"],
        "Final rendered": ["screens-s13-s14-edits--edits-grid"],
    },
    "S14": {
        "Infeasible locks warning": "0093",
        "Preliminary analysis banner": ["screens-s13-s14-edits--wizard-preliminary"],
        "Start from a template or previous edit": [
            "screens-s13-s14-edits--wizard-story",
            "screens-s13-s14-edits--edits-grid",
        ],
        "Estimate loading": ["screens-s13-s14-edits--wizard-estimating"],
    },
    "S15": {
        "Running": ["screens-s15-creating-edit--running", "screens-s15-creating-edit--planning"],
        "Cancelled": ["screens-s15-creating-edit--cancelled"],
        "Failed": ["screens-s15-creating-edit--failed"],
    },
    "S16": {
        "Locked beat": ["screens-s16-storyboard--board"],
        "Regenerating beat": ["screens-s16-storyboard--board"],
        "Infeasible-locks inline warning": ["screens-s16-storyboard--infeasible"],
        "Draft has unsaved changes": ["screens-s16-storyboard--unsaved"],
    },
    "S17": {
        "Preview rendering": ["screens-s17-preview--preview-rendering"],
        "No findings": ["screens-s17-preview--no-findings"],
        # The "Applied in v3" card; the toast with Undo is a vitest (Preview.test.tsx,
        # "applies a finding as a new version, with Undo reverting to the one before").
        "Fix applied": ["screens-s17-preview--ready"],
    },
    "S18": {
        "Single version": ["screens-s18-versions--single"],
        "Comparing": ["screens-s18-versions--comparing"],
        "Reverting": ["screens-s18-versions--reverting"],
    },
    "S19": {
        "Encoder unavailable for a preset": ["screens-s17-preview--render-final-no-hevc"],
        "Destination not writable": ["screens-s17-preview--render-final-folder"],
    },
    "S24": {
        "Place question": ["screens-s10-library--help-label-place"],
        "Same-person question": ["screens-s10-library--help-label-same-person"],
        "Event question": ["screens-s10-library--help-label-event"],
        "Done summary": ["screens-s10-library--help-label-done"],
    },
}


def _states(screen: str) -> list[str]:
    doc = next((ROOT / "docs/ui/screens").glob(f"{screen}-*.md")).read_text()
    block = doc.split("## States", 1)[1].split("\n## ", 1)[0]
    return [line[2:].strip() for line in block.splitlines() if line.startswith("- ")]


@pytest.mark.parametrize("screen", sorted(M4_SCREENS))
def test_every_listed_state_has_a_story_in_both_themes(screen: str) -> None:
    known = STATES[screen]
    listed = _states(screen)
    assert listed, f"{screen} lists its states"
    for state in listed:
        key = next((k for k in known if state.startswith(k)), None)
        assert key is not None, f"{screen}: no story for the state {state!r}"
        stories = known[key]
        if isinstance(stories, str):  # not a story: an ADR says why
            assert list((ROOT / "docs/decisions").glob(f"{stories}-*.md")), stories
            continue
        for story in stories:
            for theme in ("dark", "light"):
                png = ROOT / "frontend/visual" / f"{story}.{theme}.png"
                assert png.is_file(), f"{screen} {state!r}: no {theme} baseline for {story}"


def test_every_m4_endpoint_in_the_api_map_is_served() -> None:
    spec = json.loads((ROOT / "frontend/src/api/openapi.json").read_text())
    served = [
        (m.upper(), _segments(p))
        for p, ops in spec["paths"].items()
        for m in ops
        if m != "parameters"
    ]
    documented = documented_m2_endpoints(M4_SCREENS, skip_note=None)
    assert len(documented) > 30, "the API map parsed"
    missing = [(m, p, used) for m, p, used in documented if not _served(m, p, served)]
    assert not missing, f"documented for M4 screens but not served: {missing}"
