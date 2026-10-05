"""Versioned prompt files: ``ai/prompts/<name>/v<N>.md`` beside their output schema
(``schema_v<N>.py``). Prompts are provider-neutral (ADR 0003).

A prompt file has ``## System`` and ``## User`` sections; ``{{name}}`` placeholders are
filled from the request context (no other templating, so JSON examples stay literal).
"""

from __future__ import annotations

import importlib
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pydantic import BaseModel

PROMPTS_DIR = Path(__file__).resolve().parent
_PLACEHOLDER = re.compile(r"\{\{\s*([a-z_][a-z0-9_]*)\s*\}\}")


@dataclass(frozen=True)
class Prompt:
    name: str
    version: int
    system: str
    user: str
    schema: type[BaseModel]

    def render(self, context: dict[str, Any]) -> tuple[str, str]:
        def fill(text: str) -> str:
            def sub(m: re.Match[str]) -> str:
                key = m.group(1)
                if key not in context:
                    raise KeyError(f"prompt {self.name}/v{self.version} needs {key!r}")
                return str(context[key])

            return _PLACEHOLDER.sub(sub, text)

        return fill(self.system), fill(self.user)


def load(name: str, version: int) -> Prompt:
    path = PROMPTS_DIR / name / f"v{version}.md"
    text = path.read_text()
    sections = re.split(r"^## (System|User)\s*$", text, flags=re.M)
    parts = {sections[i]: sections[i + 1].strip() for i in range(1, len(sections) - 1, 2)}
    if "System" not in parts or "User" not in parts:
        raise ValueError(f"{path} needs '## System' and '## User' sections")
    module = importlib.import_module(f"mosaic.ai.prompts.{name}.schema_v{version}")
    schema: type[BaseModel] = module.Output
    return Prompt(name, version, parts["System"], parts["User"], schema)
