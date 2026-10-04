from __future__ import annotations

import json
from pathlib import Path

import pytest
from click.testing import CliRunner

from mosaic.cli.main import cli
from mosaic.core.keys import artifact_key
from mosaic.storage import placement, provenance
from mosaic.storage.control import ControlDB
from mosaic.storage.descriptor import UnsupportedDescriptorError
from mosaic.storage.models_control import ProjectRegistry
from mosaic.storage.models_project import Provenance
from mosaic.storage.placement import FsClass, PlacementRefusedError, classify
from mosaic.storage.projects import (
    NotAProjectError,
    Project,
    init_project,
    open_project,
    preview,
)


def test_cloud_paths_are_classified(tmp_path: Path) -> None:
    home = tmp_path
    for rel in (
        "Library/CloudStorage/OneDrive-Personal/trip",
        "Library/Mobile Documents/x",
        "Dropbox/trip",
        "Google Drive/trip",
    ):
        d = home / rel
        d.mkdir(parents=True)
        assert classify(d, home=home).fs_class is FsClass.CLOUD_SYNCED, rel
    assert classify(tmp_path / "Dropbox", home=home / "other").fs_class is FsClass.LOCAL


def test_network_and_read_only(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(placement, "fs_type", lambda _p: "smbfs")
    assert classify(tmp_path).fs_class is FsClass.NETWORK
    monkeypatch.setattr(placement, "fs_type", lambda _p: "apfs")
    monkeypatch.setattr(placement, "is_writable", lambda _p: False)
    c = classify(tmp_path)
    assert c.fs_class is FsClass.READ_ONLY
    assert c.placement.value == "external"


@pytest.mark.parametrize("cls", [FsClass.NETWORK, FsClass.CLOUD_SYNCED, FsClass.READ_ONLY])
def test_m0_refuses_non_local(cls: FsClass) -> None:
    c = placement.Classification(cls, placement.PLACEMENT_FOR_CLASS[cls], "x", "r")
    with pytest.raises(PlacementRefusedError, match="later version"):
        placement.require_supported(c)


def test_live_db_refused_on_cloud(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(placement, "is_cloud_synced", lambda _p, _h=None: True)
    from mosaic.storage.db import Database

    with pytest.raises(PlacementRefusedError):
        Database(tmp_path / "x.db", "project")


def test_init_creates_descriptor_workspace_and_registry(tmp_path: Path) -> None:
    folder = tmp_path / "Trip"
    folder.mkdir()
    (folder / "clip.mp4").write_bytes(b"original")
    control = ControlDB()
    p = init_project(control, control.local_principal, folder)
    desc = json.loads((folder / ".mosaic-project.json").read_text())
    assert desc["format_version"] == 2
    assert desc["placement"] == "in_folder"
    assert desc["workspace"] == "MosAic"
    assert desc["name"] == "Trip"
    assert len(desc["project_id"]) == 26
    assert (folder / "MosAic" / "project.db").is_file()
    assert (folder / "clip.mp4").read_bytes() == b"original"
    with control.db.session() as s:
        row = s.get(ProjectRegistry, p.id)
        assert row is not None
        assert row.user_id == control.local_principal.user_id
    p.close()
    again = init_project(control, control.local_principal, folder)
    assert again.id == p.id
    again.close()
    opened = open_project(control, control.local_principal, folder)
    assert opened.id == p.id
    opened.close()


def test_open_non_project(tmp_path: Path) -> None:
    control = ControlDB()
    with pytest.raises(NotAProjectError):
        open_project(control, control.local_principal, tmp_path)


def test_cli_init_refuses_cloud(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    trip = tmp_path.resolve()
    monkeypatch.setattr(placement, "is_cloud_synced", lambda p, _h=None: p == trip)
    result = CliRunner().invoke(cli, ["init", str(tmp_path)])
    assert result.exit_code != 0
    assert "cloud-synced" in result.output
    assert not (tmp_path / ".mosaic-project.json").exists()


def test_cli_init_ok(tmp_path: Path) -> None:
    result = CliRunner().invoke(cli, ["init", str(tmp_path)])
    assert result.exit_code == 0, result.output
    assert "will not be modified" in result.output


def _prov(p: Project) -> int:
    with p.db.session() as s:
        return provenance.record(s, provenance.ProvenanceInfo(kind="test", algorithm_version="1"))


def test_artifact_store_roundtrip_and_atomicity(tmp_path: Path) -> None:
    control = ControlDB()
    p = init_project(control, control.local_principal, tmp_path)
    prov = _prov(p)
    key = artifact_key("probe", project_id=p.id, inputs={"f": "a.mp4"}, version="1")
    assert not p.artifacts.exists("probe", key)
    doc = {"streams": [], "lufs": -14.2, "nested": [[1.5, "é"]], "n": 3}
    p.artifacts.put_json("probe", key, doc, provenance_id=prov)
    assert p.artifacts.exists("probe", key)
    assert p.artifacts.get_json("probe", key) == doc
    assert p.artifacts.provenance_id("probe", key) == prov
    assert p.artifacts.path("probe", key).is_relative_to(tmp_path / "MosAic" / "cache")

    def crash_mid_write() -> None:
        with p.artifacts.writer("proxy", "proxy-x", ".mp4", provenance_id=prov) as tmp:
            tmp.write_bytes(b"partial")
            raise RuntimeError("crash mid-write")

    with pytest.raises(RuntimeError):
        crash_mid_write()
    assert not p.artifacts.exists("proxy", "proxy-x")
    assert not list((tmp_path / "MosAic" / "cache" / "proxy").rglob("*.tmp*"))
    p.close()


def test_artifact_keys_are_deterministic_and_project_scoped() -> None:
    a = artifact_key(
        "x", project_id="P1", inputs={"b": 1, "a": [1, 2]}, config={"t": 0.5}, version="v1"
    )
    b = artifact_key(
        "x", project_id="P1", inputs={"a": [1, 2], "b": 1}, config={"t": 0.5}, version="v1"
    )
    assert a == b
    assert a != artifact_key(
        "x", project_id="P2", inputs={"b": 1, "a": [1, 2]}, config={"t": 0.5}, version="v1"
    )
    assert a != artifact_key(
        "x", project_id="P1", inputs={"b": 1, "a": [1, 2]}, config={"t": 0.5}, version="v2"
    )


def test_artifact_bytes_files_keys_delete_and_unsafe_names(tmp_path: Path) -> None:
    control = ControlDB()
    p = init_project(control, control.local_principal, tmp_path)
    prov = _prov(p)
    p.artifacts.put_bytes("blob", "blob-1", b"abc", provenance_id=prov)
    src = tmp_path / "src.txt"
    src.write_text("hello")
    p.artifacts.put_file("blob", "blob-2", src, provenance_id=prov)
    assert p.artifacts.get_bytes("blob", "blob-1") == b"abc"
    assert p.artifacts.path("blob", "blob-2").read_text() == "hello"
    assert sorted(p.artifacts.keys("blob")) == ["blob-1", "blob-2"]
    p.artifacts.delete("blob", "blob-1")
    assert not p.artifacts.exists("blob", "blob-1")
    assert p.artifacts.keys("blob") == ["blob-2"]
    for kind, key in (("../x", "k"), ("ok", "../../etc"), ("ok", "Up")):
        with pytest.raises(ValueError, match="unsafe"):
            p.artifacts.put_bytes(kind, key, b"x", provenance_id=prov)
    p.close()


def test_provenance_record(tmp_path: Path) -> None:
    control = ControlDB()
    p = init_project(control, control.local_principal, tmp_path)
    with p.db.session() as s:
        pid = provenance.record(
            s,
            provenance.ProvenanceInfo(
                kind="vision",
                provider="fake",
                model="m",
                prompt_version="vision/v1",
                input_keys=["mosaic-1"],
                config_hash="abc",
                tokens_in=10,
                tokens_out=5,
                cost_usd=0.01,
            ),
        )
    with p.db.session() as s:
        row = s.get(Provenance, pid)
        assert row is not None
        assert row.input_keys == ["mosaic-1"]
        assert row.prompt_version == "vision/v1"
        assert row.cost_usd == pytest.approx(0.01)
    p.close()


def test_control_registry_and_edit_index(tmp_path: Path) -> None:
    control = ControlDB()
    me = control.local_principal
    p = init_project(control, me, tmp_path)
    assert control.project_root(p.id) == tmp_path.resolve()
    assert [r.project_id for r in control.projects(me)] == [p.id]
    control.index_edit(me, "01EDIT", p.id)
    control.index_edit(me, "01EDIT", p.id)  # idempotent
    assert control.project_for_edit("01EDIT") == p.id
    assert control.project_for_edit("nope") is None
    assert control.project_root("nope") is None
    p.close()


def test_preview_writes_nothing(tmp_path: Path) -> None:
    c = preview(tmp_path)
    assert c.fs_class is FsClass.LOCAL
    assert list(tmp_path.iterdir()) == []


def test_cloud_name_false_positives(tmp_path: Path) -> None:
    for name in ("Boxing", "OneDriveBackup", "Dropboxes"):
        (tmp_path / name).mkdir()
        assert classify(tmp_path / name, home=tmp_path).fs_class is FsClass.LOCAL, name
    for name in ("OneDrive - Contoso", "Dropbox (Personal)", "Box Sync"):
        (tmp_path / name).mkdir()
        assert classify(tmp_path / name, home=tmp_path).fs_class is FsClass.CLOUD_SYNCED, name


def test_newer_descriptor_is_refused(tmp_path: Path) -> None:
    (tmp_path / ".mosaic-project.json").write_text(
        json.dumps(
            {
                "format_version": 99,
                "project_id": "X",
                "name": "n",
                "placement": "in_folder",
                "created_at": "2026-01-01T00:00:00+00:00",
            }
        )
    )
    control = ControlDB()
    with pytest.raises(UnsupportedDescriptorError):
        open_project(control, control.local_principal, tmp_path)


def test_split_descriptor_refused_in_m0(tmp_path: Path) -> None:
    (tmp_path / ".mosaic-project.json").write_text(
        json.dumps(
            {
                "format_version": 2,
                "project_id": "X",
                "name": "n",
                "placement": "split",
                "created_at": "2026-01-01T00:00:00+00:00",
            }
        )
    )
    control = ControlDB()
    with pytest.raises(PlacementRefusedError, match="split"):
        open_project(control, control.local_principal, tmp_path)


def test_cli_analyze_rejects_other_modes(tmp_path: Path) -> None:
    runner = CliRunner()
    assert runner.invoke(cli, ["init", str(tmp_path)]).exit_code == 0
    result = runner.invoke(cli, ["analyze", str(tmp_path), "--mode", "thorough"])
    assert result.exit_code != 0
    assert "supports: balanced" in result.output
    missing = runner.invoke(cli, ["analyze", str(tmp_path / "nope")])
    assert missing.exit_code != 0
