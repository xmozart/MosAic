"""App configuration (ADR 0003, M0 acceptance 7 parts)."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest
from click.testing import CliRunner
from fastapi.testclient import TestClient
from sqlalchemy import text

from mosaic.app.main import create_app
from mosaic.app.services import Services
from mosaic.cli.main import cli
from mosaic.core.paths import app_data_dir
from mosaic.core.settings import SettingError
from mosaic.storage.config import ConfigService, NotConfiguredError
from mosaic.storage.control import ControlDB

ROOT = Path(__file__).resolve().parents[2]
KEY = "sk-ant-test-0123456789abcdefWXYZ"


def test_show_with_nothing_configured_is_clear_not_a_crash() -> None:
    result = CliRunner().invoke(cli, ["config", "show"])
    assert result.exit_code == 0, result.output
    assert (
        "anthropic       missing — run `mosaic config ai set-key --provider anthropic`"
        in result.output
    )
    assert (
        "Eval corpus: not configured — run `mosaic config set eval.corpus_dir <path>`"
        in result.output
    )
    control = ControlDB()
    with pytest.raises(NotConfiguredError, match="mosaic config ai set-key"):
        ConfigService(control).key_for(control.local_principal, "anthropic")


def test_set_settings_and_validation(tmp_path: Path) -> None:
    runner = CliRunner()
    ok = runner.invoke(cli, ["config", "set", "eval.corpus_dir", str(tmp_path)])
    assert ok.exit_code == 0, ok.output
    assert runner.invoke(cli, ["config", "set", "eval.corpus_dir", "/nope/x"]).exit_code != 0
    assert runner.invoke(cli, ["config", "set", "no.such.key", "1"]).exit_code != 0
    assert runner.invoke(cli, ["config", "set", "ai.budget.per_job_usd", "-1"]).exit_code != 0
    control = ControlDB()
    svc = ConfigService(control)
    me = control.local_principal
    assert svc.get(me, "eval.corpus_dir") == str(tmp_path.resolve())
    assert svc.settings(me)["eval.corpus_dir"].source == "user"
    svc.set(me, "ai.local_only", "true")
    assert svc.get(me, "ai.local_only") is True
    assert runner.invoke(cli, ["config", "reset", "ai.local_only"]).exit_code == 0
    assert svc.get(me, "ai.local_only") is False


def test_provider_profiles() -> None:
    runner = CliRunner()
    r = runner.invoke(
        cli,
        ["config", "ai", "set", "--capability", "all", "--provider", "fake", "--model", "fake-1"],
    )
    assert r.exit_code == 0, r.output
    control = ControlDB()
    svc = ConfigService(control)
    me = control.local_principal
    provs = svc.providers(me)
    assert {c for c, st in provs.items() if st.choice.provider == "fake"} == {
        "vision",
        "planner",
        "selector",
        "critic",
        "reviewer",  # M1: L3 review is a cloud capability too
        "summarizer",  # M1: day and trip summaries
    }
    assert provs["transcriber"].choice.provider == "faster-whisper"
    assert (
        runner.invoke(
            cli,
            [
                "config",
                "ai",
                "set",
                "--capability",
                "vision",
                "--provider",
                "nonexistent",
                "--model",
                "x",
            ],
        ).exit_code
        != 0
    )
    with pytest.raises(SettingError, match="unknown capability"):
        svc.set_provider(me, "dancing", "fake", "x")


def _everything_in(home: Path, control: ControlDB) -> str:
    blobs = [p.read_bytes().decode("latin-1") for p in home.rglob("*") if p.is_file()]
    with control.db.engine.connect() as conn:
        for (name,) in conn.execute(text("SELECT name FROM sqlite_master WHERE type='table'")):
            for row in conn.execute(text(f'SELECT * FROM "{name}"')):
                blobs.append(repr(tuple(row)))
    return "\n".join(blobs)


def test_set_key_from_stdin_lands_only_in_the_keyring() -> None:
    result = CliRunner().invoke(
        cli, ["config", "ai", "set-key", "--provider", "anthropic"], input=KEY + "\n"
    )
    assert result.exit_code == 0, result.output
    assert KEY not in result.output
    assert "WXYZ" in result.output  # last four only
    control = ControlDB()
    svc = ConfigService(control)
    me = control.local_principal
    status = svc.key_status(me, "anthropic")
    assert (status.configured, status.last4, status.ref) == (
        True,
        "WXYZ",
        "keyring:mosaic/ai/anthropic",
    )
    assert svc.key_for(me, "anthropic") == KEY
    assert KEY not in _everything_in(app_data_dir(), control)
    show = CliRunner().invoke(cli, ["config", "show"])
    assert "configured (…WXYZ)" in show.output
    assert KEY not in show.output


def test_set_key_subprocess_never_puts_the_key_in_argv(tmp_path: Path) -> None:
    keyfile = tmp_path / "keyring.json"
    env = {
        **os.environ,
        "PYTHON_KEYRING_BACKEND": "tests.support.testkeyring.FileKeyring",
        "TEST_KEYRING_FILE": str(keyfile),
        "PYTHONPATH": str(ROOT),
    }
    argv = [
        sys.executable,
        "-c",
        "from mosaic.cli.main import cli; cli()",
        "config",
        "ai",
        "set-key",
        "--provider",
        "anthropic",
    ]
    proc = subprocess.run(
        argv,
        input=KEY + "\n",
        capture_output=True,
        text=True,
        env=env,
        cwd=ROOT,
        check=False,
        timeout=60,
    )
    assert proc.returncode == 0, proc.stderr
    assert KEY not in " ".join(argv)
    assert KEY not in proc.stdout + proc.stderr
    assert KEY in keyfile.read_text()  # it went to the keyring backend
    assert KEY not in _everything_in(app_data_dir(), ControlDB())


def test_api_settings_providers_and_write_only_secrets(tmp_path: Path) -> None:
    svc = Services.create()
    app = create_app(svc)
    app.state.allowed_hosts = {"testserver"}
    client = TestClient(app)
    s = client.get("/api/settings").json()
    assert s["eval.corpus_dir"] == {"value": "", "source": "default"}
    s = client.patch("/api/settings", json={"eval.corpus_dir": str(tmp_path)}).json()
    assert s["eval.corpus_dir"]["source"] == "user"
    assert client.patch("/api/settings", json={"bogus": 1}).status_code == 422
    p = client.get("/api/providers").json()
    assert p["vision"]["key"] == {"configured": False, "last4": None}
    p = client.patch(
        "/api/providers", json={"planner": {"provider": "fake", "model": "fake-1"}}
    ).json()
    assert p["planner"]["provider"] == "fake"
    put = client.put("/api/secrets/ai/anthropic", json={"value": KEY})
    assert put.json() == {"configured": True, "last4": "WXYZ"}
    assert KEY not in client.get("/api/providers").text
    assert client.put("/api/secrets/db/password", json={"value": "x"}).status_code == 404


def test_allow_gpl_ffmpeg_setting_and_env_override(monkeypatch: pytest.MonkeyPatch) -> None:
    from mosaic.media import tools
    from mosaic.media.ffmpeg.capabilities import (
        Capabilities,
        FFmpegBinaries,
        FFmpegLicense,
        FFmpegLicenseError,
    )

    gpl = Capabilities(version="x", license=FFmpegLicense.GPL, configuration=("--enable-gpl",))
    monkeypatch.setattr(tools, "locate", lambda: FFmpegBinaries(Path("ff"), Path("fp")))
    monkeypatch.setattr(tools, "probe_capabilities", lambda _p: gpl)
    monkeypatch.delenv(tools.ENV_ALLOW_GPL, raising=False)
    tools.media_tools.cache_clear()
    try:
        with pytest.raises(FFmpegLicenseError):
            tools.media_tools()
        control = ControlDB()
        ConfigService(control).set(control.local_principal, "allow_gpl_ffmpeg", "true")
        tools.media_tools.cache_clear()
        assert tools.media_tools()[1] is gpl
        ConfigService(control).reset(control.local_principal, "allow_gpl_ffmpeg")
        monkeypatch.setenv(tools.ENV_ALLOW_GPL, "1")
        tools.media_tools.cache_clear()
        assert tools.media_tools()[1] is gpl
    finally:
        tools.media_tools.cache_clear()


def test_keyring_failures_are_reported_not_crashes() -> None:
    import keyring
    from keyring.backend import KeyringBackend
    from keyring.errors import KeyringLocked

    class Locked(KeyringBackend):
        priority = 1  # type: ignore[assignment]

        def get_password(self, service: str, username: str) -> str | None:
            raise KeyringLocked("locked " + KEY)

        def set_password(self, service: str, username: str, password: str) -> None:
            raise KeyringLocked("locked " + password)

        def delete_password(self, service: str, username: str) -> None:
            raise KeyringLocked("locked")

    control = ControlDB()
    svc = ConfigService(control)
    from mosaic.storage.models_control import SecretRef

    with control.db.session() as s:
        s.add(
            SecretRef(
                user_id=control.local_principal.user_id,
                name="ai/anthropic",
                ref="keyring:mosaic/ai/anthropic",
                updated_at="x",
            )
        )
    keyring.set_keyring(Locked())
    show = CliRunner().invoke(cli, ["config", "show"])
    assert show.exit_code == 0, show.output
    assert "OS keyring error (KeyringLocked)" in show.output
    setkey = CliRunner().invoke(
        cli, ["config", "ai", "set-key", "--provider", "anthropic"], input=KEY + "\n"
    )
    assert setkey.exit_code != 0
    assert "KeyringLocked" in setkey.output
    assert KEY not in setkey.output
    assert svc.key_status(control.local_principal, "anthropic").configured is False


def test_api_patches_are_atomic_and_never_echo_input(tmp_path: Path) -> None:
    svc = Services.create()
    app = create_app(svc)
    app.state.allowed_hosts = {"testserver"}
    client = TestClient(app)
    r = client.patch("/api/settings", json={"eval.corpus_dir": str(tmp_path), "bogus": 1})
    assert r.status_code == 422
    assert client.get("/api/settings").json()["eval.corpus_dir"]["source"] == "default"
    r = client.patch("/api/settings", json={"allow_gpl_ffmpeg": True})
    assert r.status_code == 403
    r = client.patch(
        "/api/providers",
        json={
            "planner": {"provider": "fake", "model": "m"},
            "vision": {"provider": "nonexistent", "model": "m"},
        },
    )
    assert r.status_code == 422
    assert client.get("/api/providers").json()["planner"]["source"] == "default"
    bad = client.put("/api/secrets/ai/anthropic", json={"valu": KEY})
    assert bad.status_code == 422
    assert KEY not in bad.text


def test_new_capability_inherits_the_single_chosen_provider() -> None:
    """`ai use claude-cli` before `reviewer` existed: reviewer follows claude-cli (ADR 0019)."""
    control = ControlDB()
    svc = ConfigService(control)
    me = control.local_principal
    for cap in ("vision", "planner", "selector", "critic"):
        svc.set_provider(me, cap, "claude-cli", "claude-sonnet-5-5")
    provs = svc.providers(me)
    assert provs["reviewer"].choice.provider == "claude-cli"
    assert provs["reviewer"].choice.model == "claude-sonnet-5-5"
    assert provs["reviewer"].source == "inherited"
    assert not provs["reviewer"].needs_key
    assert provs["transcriber"].source == "default"  # local capabilities are never inherited
    svc.set_provider(me, "critic", "anthropic", "claude-sonnet-5-5")  # mixed: no inheritance
    assert svc.providers(me)["reviewer"].source == "default"


def test_one_explicit_capability_never_moves_the_others() -> None:
    control = ControlDB()
    svc = ConfigService(control)
    me = control.local_principal
    svc.set_provider(me, "vision", "codex-cli", "gpt-5.5")
    provs = svc.providers(me)
    for cap in ("planner", "selector", "critic", "reviewer"):
        assert provs[cap].source == "default", cap
        assert provs[cap].choice.provider == "anthropic"


def test_eval_checks_the_reviewer_and_refuses_skipped_reviews(tmp_path: Path) -> None:
    import pytest

    from mosaic.evaluation import run as ev
    from mosaic.jobs.model import JobSpec, ResourceClass, TaskSpec
    from mosaic.jobs.store import JobStore

    control = ControlDB()
    svc = ConfigService(control)
    me = control.local_principal
    svc.set(me, "eval.corpus_dir", str(Path(__file__).parent))
    for cap in ("vision", "planner", "selector"):
        svc.set_provider(me, cap, "claude-cli", "claude-sonnet-5-5")
    stub = tmp_path / "claude"  # tests never depend on an installed app
    stub.write_text("#!/bin/sh\nexit 0\n")
    stub.chmod(0o755)
    svc.set(me, "ai.cli.claude_path", str(stub))
    with pytest.raises(ev.GateStop) as stop:
        ev.check_configuration(svc, me, deepen=True)
    msg = str(stop.value)
    assert "reviewer (anthropic)" in msg  # the only problem: the keyless default reviewer
    for cap in ("vision", "planner", "selector"):
        assert f"{cap} (" not in msg
    # Without --deepen the reviewer is not needed: the same setup passes the check.
    assert ev.check_configuration(svc, me, deepen=False).is_dir()

    store = JobStore(control.db)
    job = store.create_job(
        me,
        JobSpec(
            "p",
            "deepen",
            tasks=[TaskSpec("library.review", "s", resource_class=ResourceClass.AI_API)],
        ),
    )
    task = store.lease("w", "ai_api")
    assert task is not None
    store.skip(task.id, "w", "deep review skipped: not configured")
    with pytest.raises(ev.GateStop) as stop:
        ev.check_deep_review(control, job, "Trip")
    assert stop.value.gate == "G1"
    assert "1 tasks" in str(stop.value)
