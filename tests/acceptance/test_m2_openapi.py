"""M2 acceptance 9: every endpoint `docs/ui/API_MAP.md` lists for an M2 screen exists in the
OpenAPI schema the frontend's client is generated from (docs/milestones/M2.md).

The client itself is typed from that schema (`openapi-fetch`), so `tsc` already fails on a
call to a path the schema lacks; this test closes the other direction: a documented M2
endpoint the server doesn't serve.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import pytest

pytestmark = [pytest.mark.acceptance]

ROOT = Path(__file__).resolve().parents[2]
M2_SCREENS = {f"S{n}" for n in (0, *range(2, 15), 17, 20, 21, 22, 23, 25)}
PARAM = re.compile(r"\{[^}]+\}")


def _segments(path: str) -> list[str]:
    return [("{}" if PARAM.fullmatch(s) else s) for s in path.strip("/").split("/")]


def _served(method: str, path: str, served: list[tuple[str, list[str]]]) -> bool:
    want = _segments(path)
    return any(
        m == method
        and len(have) == len(want)
        and all(h == w or h == "{}" for h, w in zip(have, want, strict=True))
        for m, have in served
    )


METHOD = re.compile(r"\b(GET|POST|PUT|PATCH|DELETE)\b")


def documented_m2_endpoints() -> list[tuple[str, str, str]]:
    """(method, path, row's screens) for each endpoint of an M2 screen's row. A token that
    doesn't start at a top-level API segment continues the previous one (`/foo/{id}/pause`
    · `/resume`). A method written after a `·` (`· POST /x`) applies from there on;
    else the row's Method column (`GET/POST` means both). Rows marked "not in M2" are left
    out."""
    spec = json.loads((ROOT / "frontend/src/api/openapi.json").read_text())
    tops = {p.split("/")[2] for p in spec["paths"]}
    out: list[tuple[str, str, str]] = []
    for line in (ROOT / "docs/ui/API_MAP.md").read_text().splitlines():
        if not line.startswith("| ") or line.startswith("| Method") or "not in M2" in line:
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        screens = set(re.findall(r"S\d+", cells[-1]))
        if not screens & M2_SCREENS:
            continue
        methods = METHOD.findall(cells[0])
        cell = "|".join(cells[1:-1])
        prev: str | None = None
        last = 0
        for m in re.finditer(r"`(/[^`]*)`", cell):
            # A method applies when it follows a `·` separator, outside any description.
            between = re.sub(r"`[^`]*`", "", cell[last : m.start()])
            if "·" in between:
                inline = METHOD.findall(between.rsplit("·", 1)[1])
                if inline:
                    methods = inline[-1:]
            last = m.end()
            path = re.split(r"[?\s]", m.group(1))[0].rstrip("/")
            if path in ("", "/api") or "…" in path:
                continue
            if prev and path.split("/")[1] not in tops:
                path = prev.rsplit("/", 1)[0] + path
            prev = path
            out.extend((meth, "/api" + path, cells[-1]) for meth in methods)
    return out


def test_every_m2_endpoint_in_the_api_map_is_in_the_openapi_schema() -> None:
    spec = json.loads((ROOT / "frontend/src/api/openapi.json").read_text())
    served = [
        (m.upper(), _segments(p))
        for p, ops in spec["paths"].items()
        for m in ops
        if m != "parameters"
    ]
    documented = documented_m2_endpoints()
    assert len(documented) > 60, "the API map parsed"
    missing = [(m, p, used) for m, p, used in documented if not _served(m, p, served)]
    assert not missing, f"documented for M2 screens but not served: {missing}"


def test_the_committed_schema_matches_the_server() -> None:
    from mosaic.app.main import create_app
    from mosaic.app.services import Services
    from mosaic.storage.control import ControlDB

    live = create_app(Services.create(ControlDB())).openapi()
    committed = json.loads((ROOT / "frontend/src/api/openapi.json").read_text())

    def ops(spec: dict[str, Any]) -> set[tuple[str, str]]:
        return {(m, p) for p, o in spec["paths"].items() for m in o if m != "parameters"}

    assert ops(live) == ops(committed), "run `npm run api` in frontend/"
