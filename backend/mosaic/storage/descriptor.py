"""Project descriptor ``<root>/.mosaic-project.json`` (ARCHITECTURE.md §4)."""

from __future__ import annotations

import json
import os
from pathlib import Path

from pydantic import BaseModel, ConfigDict

from mosaic.core.paths import DESCRIPTOR_NAME, WORKSPACE_DIR
from mosaic.storage.placement import Placement

FORMAT_VERSION = 2


class ProjectDescriptor(BaseModel):
    model_config = ConfigDict(extra="allow")  # unknown fields are preserved

    format_version: int = FORMAT_VERSION
    project_id: str
    name: str
    workspace: str = WORKSPACE_DIR
    placement: Placement
    created_at: str


class UnsupportedDescriptorError(RuntimeError):
    pass


def descriptor_path(root: Path) -> Path:
    return root / DESCRIPTOR_NAME


def read_descriptor(root: Path) -> ProjectDescriptor | None:
    path = descriptor_path(root)
    if not path.is_file():
        return None
    descriptor = ProjectDescriptor.model_validate_json(path.read_text())
    if descriptor.format_version > FORMAT_VERSION:
        raise UnsupportedDescriptorError(
            f"{path} was written by a newer MosAic (format {descriptor.format_version}); "
            "update MosAic to open it"
        )
    return descriptor


def write_descriptor(root: Path, descriptor: ProjectDescriptor) -> None:
    path = descriptor_path(root)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(descriptor.model_dump(mode="json"), indent=2) + "\n")
    os.replace(tmp, path)
