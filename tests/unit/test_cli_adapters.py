"""Claude Code and Codex CLI providers (ADR 0014), driven against stand-in executables."""

from __future__ import annotations

import json
import os
import stat
import sys
from pathlib import Path

import pytest
from click.testing import CliRunner

from mosaic.ai.adapters.claude_cli.adapter import ClaudeCliAdapter
from mosaic.ai.adapters.codex_cli.adapter import CodexCliAdapter
from mosaic.ai.client import AIClient
from mosaic.ai.prompts.healthcheck.schema_v1 import Output as Health
from mosaic.ai.registry import LocalOnlyError, adapter_for, task_check_ready
from mosaic.ai.types import AdapterError, ImageInput, StructuredRequest
from mosaic.cli.main import cli
from mosaic.jobs.context import TaskContext
from mosaic.jobs.executor import LocalExecutor
from mosaic.jobs.model import JobSpec, ResourceClass, TaskSpec
from mosaic.jobs.store import JobStore
from mosaic.storage.config import ConfigService, NotConfiguredError
from mosaic.storage.control import ControlDB
from mosaic.storage.projects import init_project

SECRET_TEXT = "trip-to-the-secret-waterfall"

FAKE_CLAUDE = r"""
import json, os, sys
log = os.environ["FAKE_CLI_LOG"]
stdin = sys.stdin.read()
json.dump({"argv": sys.argv, "stdin": stdin, "cwd": os.getcwd(), "cwd_files": os.listdir("."),
           "env_key": os.environ.get("ANTHROPIC_API_KEY")}, open(log, "w"))
mode = os.environ.get("FAKE_CLI_MODE", "ok")
print(json.dumps({"type": "system", "subtype": "init"}))
if mode == "login":
    print(json.dumps({"type": "result", "subtype": "success", "is_error": True,
                      "result": "Invalid API key · Please run /login"}))
    sys.exit(1)
if mode == "crash":
    sys.stderr.write("segfault\n"); sys.exit(3)
answer = {"ok": True} if mode == "ok" else {"ok": "not-a-bool"}
print(json.dumps({"type": "result", "subtype": "success", "is_error": False,
                  "structured_output": answer, "result": json.dumps(answer),
                  "usage": {"input_tokens": 100, "cache_read_input_tokens": 20,
                            "cache_creation_input_tokens": 0, "output_tokens": 7},
                  "modelUsage": {"claude-haiku-4-5": {"canonicalModel": "claude-haiku-4-5"}}}))
"""

FAKE_CODEX = r"""
import json, os, sys
argv = sys.argv
stdin = sys.stdin.read()
out = argv[argv.index("-o") + 1]
schema = json.load(open(argv[argv.index("--output-schema") + 1]))
images = [open(argv[i + 1], "rb").read()[:4].hex() for i, a in enumerate(argv) if a == "-i"]
json.dump({"argv": argv, "stdin": stdin, "schema": schema, "images": images,
           "env_key": os.environ.get("OPENAI_API_KEY")}, open(os.environ["FAKE_CLI_LOG"], "w"))
mode = os.environ.get("FAKE_CLI_MODE", "ok")
print(json.dumps({"type": "thread.started"}))
if mode == "login":
    print(json.dumps({"type": "turn.failed", "error": {"message": "401 Unauthorized: login"}}))
    sys.exit(1)
if mode == "ratelimit":
    print(json.dumps({"type": "turn.failed", "error": {"message": "429 rate limit reached"}}))
    sys.exit(1)
open(out, "w").write(json.dumps({"ok": True}))
print(json.dumps({"type": "turn.completed", "usage": {"input_tokens": 300, "output_tokens": 9}}))
"""


def _exe(tmp: Path, name: str, body: str) -> Path:
    path = tmp / name
    path.write_text(f"#!{sys.executable}\n{body}")
    path.chmod(path.stat().st_mode | stat.S_IXUSR)
    return path


def _request(images: bool = True) -> StructuredRequest:
    imgs = (ImageInput(b"\xff\xd8\xff\xe0fakejpeg", "image/jpeg", 64, 64),) if images else ()
    return StructuredRequest(
        "vision", "healthcheck", 1, "You check things.", f"Describe {SECRET_TEXT}.", Health, imgs
    )


@pytest.fixture
def log(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    path = tmp_path / "cli-log.json"
    monkeypatch.setenv("FAKE_CLI_LOG", str(path))
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-should-not-leak")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-should-not-leak")
    return path


def test_claude_cli_request_and_answer(tmp_path: Path, log: Path) -> None:
    exe = _exe(tmp_path, "claude", FAKE_CLAUDE)
    raw = ClaudeCliAdapter(str(exe)).complete(
        _request(), "claude-haiku-4-5", {"type": "object"}, None
    )
    assert json.loads(raw.text) == {"ok": True}
    assert (raw.tokens_in, raw.tokens_out, raw.model) == (120, 7, "claude-haiku-4-5")
    seen = json.loads(log.read_text())
    argv = seen["argv"]
    assert SECRET_TEXT not in " ".join(argv), "user content goes through stdin, not argv"
    for flag in ("--safe-mode", "--no-session-persistence", "--json-schema", "--system-prompt"):
        assert flag in argv
    assert argv[argv.index("--tools") + 1] == ""
    assert argv[argv.index("--model") + 1] == "claude-haiku-4-5"
    message = json.loads(seen["stdin"])
    blocks = message["message"]["content"]
    assert blocks[0]["type"] == "image"
    assert blocks[-1]["text"].endswith(f"{SECRET_TEXT}.")
    assert seen["env_key"] is None, "the app must use the user's sign-in, not an API key"
    assert seen["cwd_files"] == []
    assert Path(seen["cwd"]) != Path.cwd()


def test_claude_cli_errors(tmp_path: Path, log: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    adapter = ClaudeCliAdapter(str(_exe(tmp_path, "claude", FAKE_CLAUDE)))
    monkeypatch.setenv("FAKE_CLI_MODE", "login")
    with pytest.raises(AdapterError, match="not signed in") as info:
        adapter.complete(_request(), "m", {}, None)
    assert info.value.retryable is False
    monkeypatch.setenv("FAKE_CLI_MODE", "crash")
    with pytest.raises(AdapterError, match="segfault"):
        adapter.complete(_request(), "m", {}, None)
    with pytest.raises(AdapterError, match="not found at"):
        ClaudeCliAdapter(str(tmp_path / "missing")).complete(_request(), "m", {}, None)


def test_claude_cli_timeout(tmp_path: Path, log: Path) -> None:
    exe = _exe(tmp_path, "claude", "import time; time.sleep(5)")
    with pytest.raises(AdapterError, match="timed out") as info:
        ClaudeCliAdapter(str(exe), timeout_s=0.5).complete(_request(), "m", {}, None)
    assert info.value.retryable is True


def test_codex_cli_request_and_answer(
    tmp_path: Path, log: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    exe = _exe(tmp_path, "codex", FAKE_CODEX)
    schema = {"type": "object", "properties": {"ok": {"type": "boolean"}}}
    raw = CodexCliAdapter(str(exe)).complete(_request(), "gpt-5.5", schema, "S1 is missing")
    assert json.loads(raw.text) == {"ok": True}
    assert (raw.tokens_in, raw.tokens_out, raw.model) == (300, 9, "gpt-5.5")
    seen = json.loads(log.read_text())
    argv = seen["argv"]
    assert SECRET_TEXT not in " ".join(argv)
    for flag in ("--ephemeral", "--ignore-user-config", "--skip-git-repo-check"):
        assert flag in argv
    assert argv[argv.index("--sandbox") + 1] == "read-only"
    assert argv[argv.index("-m") + 1] == "gpt-5.5"
    assert argv[-1] == "-"
    assert seen["schema"] == schema
    assert seen["images"] == ["ffd8ffe0"]
    assert "You check things." in seen["stdin"]
    assert SECRET_TEXT in seen["stdin"]
    assert "S1 is missing" in seen["stdin"]  # validation feedback on the retry
    assert seen["env_key"] is None
    monkeypatch.setenv("FAKE_CLI_MODE", "login")
    with pytest.raises(AdapterError, match="codex login") as info:
        CodexCliAdapter(str(exe)).complete(_request(), "gpt-5.5", schema, None)
    assert info.value.retryable is False
    monkeypatch.setenv("FAKE_CLI_MODE", "ratelimit")
    with pytest.raises(AdapterError) as info:
        CodexCliAdapter(str(exe)).complete(_request(), "gpt-5.5", schema, None)
    assert info.value.retryable is True


def _ctx(tmp_path: Path) -> TaskContext:
    control = ControlDB()
    project = init_project(control, control.local_principal, tmp_path / "proj")
    store = JobStore(control.db)
    store.create_job(
        control.local_principal,
        JobSpec(project.id, "t", tasks=[TaskSpec("x", "s", resource_class=ResourceClass.AI_API)]),
    )
    leased = store.lease("w", "ai_api")
    assert leased is not None
    return TaskContext(leased, "w", LocalExecutor(store), store, project, control=control)


def test_aiclient_through_claude_cli_needs_no_key(tmp_path: Path, log: Path) -> None:
    (tmp_path / "proj").mkdir()
    ctx = _ctx(tmp_path)
    assert ctx.control is not None
    svc = ConfigService(ctx.control)
    me = ctx.control.local_principal
    svc.set(me, "ai.cli.timeout_s", "30")
    svc.set(me, "ai.cli.claude_path", str(_exe(tmp_path, "claude", FAKE_CLAUDE)))
    svc.set_provider(me, "vision", "claude-cli", "claude-haiku-4-5")
    task_check_ready(ctx, "vision")
    result = AIClient(ctx).structured("vision", "healthcheck", 1, {})
    assert result.data.model_dump() == {"ok": True}
    assert (result.provider, result.cost_usd) == ("claude-cli", 0.0)
    assert AIClient(ctx).structured("vision", "healthcheck", 1, {}).cached
    # ai.local_only blocks providers that send data off the machine, CLI apps included.
    svc.set(me, "ai.local_only", True)
    with pytest.raises(LocalOnlyError):
        adapter_for(svc, me, "claude-cli")
    ctx.project.close()


def test_missing_app_is_not_configured(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    (tmp_path / "proj").mkdir()
    (tmp_path / "empty").mkdir()
    monkeypatch.setenv("PATH", str(tmp_path / "empty"))
    ctx = _ctx(tmp_path)
    assert ctx.control is not None
    ConfigService(ctx.control).set_provider(
        ctx.control.local_principal, "vision", "codex-cli", "gpt-5.5"
    )
    with pytest.raises(NotConfiguredError, match="codex app is not installed"):
        task_check_ready(ctx, "vision")
    ctx.project.close()


def test_ai_use_presets() -> None:
    runner = CliRunner()
    out = runner.invoke(cli, ["config", "ai", "use", "claude-cli"])
    assert out.exit_code == 0, out.output
    assert "vision: claude-cli claude-haiku-4-5" in out.output
    assert "planner: claude-cli claude-sonnet-5-5" in out.output
    shown = runner.invoke(cli, ["config", "show"]).output
    assert "claude-cli" in shown
    assert "set-key" not in shown, "CLI providers need no key"
    out = runner.invoke(cli, ["config", "ai", "use", "codex-cli"])
    assert "critic: codex-cli gpt-5.5" in out.output
    bad = runner.invoke(cli, ["config", "ai", "use", "nope"])
    assert bad.exit_code != 0
    assert "no preset" in bad.output
    assert os.environ.get("MOSAIC_HOME")  # isolated app data (conftest)


def test_claude_rate_limit_is_retryable(
    tmp_path: Path, log: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    body = FAKE_CLAUDE.replace(
        'if mode == "login":',
        'if mode == "ratelimit":\n'
        '    print(json.dumps({"type": "result", "subtype": "error_during_execution",'
        ' "is_error": True, "result": "API Error: 429 rate limit"}))\n'
        "    sys.exit(1)\n"
        'if mode == "login":',
    )
    monkeypatch.setenv("FAKE_CLI_MODE", "ratelimit")
    with pytest.raises(AdapterError) as info:
        ClaudeCliAdapter(str(_exe(tmp_path, "claude", body))).complete(_request(), "m", {}, None)
    assert info.value.retryable is True


def test_codex_tools_are_switched_off(tmp_path: Path, log: Path) -> None:
    exe = _exe(tmp_path, "codex", FAKE_CODEX)
    CodexCliAdapter(str(exe)).complete(_request(False), "gpt-5.5", {"type": "object"}, None)
    argv = json.loads(log.read_text())["argv"]
    disabled = {argv[i + 1] for i, a in enumerate(argv) if a == "--disable"}
    assert {"shell_tool", "unified_exec", "browser_use", "computer_use"} <= disabled


def test_system_prompts_are_fixed_text(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Some adapters pass the system text in argv: it may never carry request data."""
    from mosaic.ai.prompts import loader

    for folder in loader.PROMPTS_DIR.iterdir():
        for version in folder.glob("v*.md"):
            loader.load(folder.name, int(version.stem[1:]))  # every shipped prompt loads
    bad = tmp_path / "bad"
    bad.mkdir()
    (bad / "v1.md").write_text("## System\nTrip: {{trip}}\n\n## User\nHi\n")
    monkeypatch.setattr(loader, "PROMPTS_DIR", tmp_path)
    with pytest.raises(ValueError, match="not allowed in the System section"):
        loader.load("bad", 1)


def test_cli_settings_are_host_only_and_validated(tmp_path: Path) -> None:
    from fastapi.testclient import TestClient

    from mosaic.ai.health import model_for
    from mosaic.app.main import create_app
    from mosaic.app.services import Services
    from mosaic.core.settings import SettingError, coerce

    svc = Services.create()
    app = create_app(svc)
    app.state.allowed_hosts = {"testserver"}
    client = TestClient(app)
    for key in ("ai.cli.claude_path", "ai.cli.codex_path"):
        r = client.patch("/api/settings", json={key: "/bin/sh"})
        assert r.status_code == 403, "an API caller must not choose a program to run"
    assert client.post("/api/secrets/ai/claude-cli/validate").status_code == 404
    with pytest.raises(SettingError, match="file not found"):
        coerce("ai.cli.claude_path", str(tmp_path / "nope"))
    control = ControlDB()
    config = ConfigService(control)
    assert model_for(config, control.local_principal, "codex-cli") == "gpt-5.5"
    assert model_for(config, control.local_principal, "unknown") == "fake-1"


def test_ai_test_includes_cli_providers(tmp_path: Path, log: Path) -> None:
    runner = CliRunner()
    exe = _exe(tmp_path, "claude", FAKE_CLAUDE)
    assert runner.invoke(cli, ["config", "set", "ai.cli.claude_path", str(exe)]).exit_code == 0
    assert runner.invoke(cli, ["config", "ai", "use", "claude-cli"]).exit_code == 0
    out = runner.invoke(cli, ["config", "ai", "test"])
    assert "claude-cli: ok" in out.output, out.output
