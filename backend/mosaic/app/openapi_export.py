"""Write the API's OpenAPI document for the frontend's generated client (M2 acceptance 9).

``python -m mosaic.app.openapi_export PATH`` builds the app without services (the schema
needs no database) and writes the document as stable, sorted JSON.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast


def schema() -> dict[str, Any]:
    from mosaic.app.main import create_app
    from mosaic.app.services import Services

    app = create_app(cast(Services, SimpleNamespace()))
    return app.openapi()


def render() -> str:
    return json.dumps(schema(), indent=2, sort_keys=True) + "\n"


def main(argv: list[str] | None = None) -> None:
    out = Path((argv or sys.argv[1:])[0])
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(render())


if __name__ == "__main__":
    main()
