"""AI provider layer (M0 step 9b): registry, adapters, AIClient, budgets."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import httpx2
import pytest
from click.testing import CliRunner
from sqlalchemy import select

from mosaic.ai.adapters.anthropic.adapter import AnthropicAdapter
from mosaic.ai.adapters.base import strict_schema
from mosaic.ai.adapters.fake import adapter as fake
from mosaic.ai.client import AIClient
from mosaic.ai.prompts.loader import load
from mosaic.ai.registry import LocalOnlyError, resolve
from mosaic.ai.types import AdapterError, ImageInput, StructuredRequest
from mosaic.cli.main import cli
from mosaic.core.settings import SettingError
from mosaic.jobs.context import TaskContext
from mosaic.jobs.executor import LocalExecutor
from mosaic.jobs.model import JobSpec, ResourceClass, TaskSpec
from mosaic.jobs.registry import DeferTask, PermanentError
from mosaic.jobs.store import JobStore
from mosaic.storage.config import ConfigService, NotConfiguredError
from mosaic.storage.control import ControlDB
from mosaic.storage.models_control import UsageRecord
from mosaic.storage.models_project import Provenance
from mosaic.storage.projects import init_project


def test_strict_schema_closes_objects_and_drops_bounds() -> None:
    schema = {
        "type": "object",
        "title": "X",
        "properties": {
            "n": {"type": "integer", "minimum": 1, "maximum": 5},
            "s": {"type": "string", "maxLength": 3},
            "o": {"type": "object", "properties": {"a": {"type": "string"}}},
        },
        "required": ["n"],
    }
    out = strict_schema(schema)
    assert out["additionalProperties"] is False
    assert out["properties"]["o"]["additionalProperties"] is False
    assert out["properties"]["o"]["required"] == ["a"]
    assert "minimum" not in out["properties"]["n"]
    assert "maxLength" not in out["properties"]["s"]
    assert "title" not in out


def test_prompt_loader() -> None:
    prompt = load("healthcheck", 1)
    system, user = prompt.render({})
    assert "configuration checks" in system
    assert "ok" in user
    assert prompt.schema.model_validate({"ok": True})


def test_registry_and_capability_rules() -> None:
    control = ControlDB()
    cfg = ConfigService(control)
    me = control.local_principal
    with pytest.raises(NotConfiguredError, match="set-key --provider anthropic"):
        resolve(cfg, me, "vision")
    cfg.set_key(me, "anthropic", "sk-ant-test-0000000000000000")
    assert resolve(cfg, me, "vision").adapter.provider == "anthropic"
    cfg.set(me, "ai.local_only", "true")
    with pytest.raises(LocalOnlyError):
        resolve(cfg, me, "vision")
    cfg.set_provider(me, "vision", "fake", "fake-1")
    assert resolve(cfg, me, "vision").adapter.provider == "fake"
    with pytest.raises(SettingError, match="cannot serve transcriber"):
        cfg.set_provider(me, "transcriber", "anthropic", "claude-haiku-4-5")


class _Messages:
    def __init__(self, behaviour: Any) -> None:
        self.behaviour = behaviour
        self.calls: list[dict[str, Any]] = []

    def create(self, **kwargs: Any) -> Any:
        self.calls.append(kwargs)
        return self.behaviour(kwargs)


class _Resp:
    def __init__(self, text: str, stop: str = "end_turn") -> None:
        self.stop_reason = stop
        self.stop_details = None
        self.model = "claude-haiku-4-5"
        self.content = [type("B", (), {"type": "text", "text": text})()]
        self.usage = type("U", (), {"input_tokens": 1000, "output_tokens": 200})()


def _request() -> StructuredRequest:
    prompt = load("healthcheck", 1)
    return StructuredRequest(
        "vision",
        "healthcheck",
        1,
        "sys",
        "user",
        prompt.schema,
        (ImageInput(b"\xff\xd8jpeg", "image/jpeg", 1568, 882),),
        512,
    )


def _adapter(behaviour: Any) -> tuple[AnthropicAdapter, _Messages]:
    a = AnthropicAdapter("sk-ant-test-0000000000000000")
    msgs = _Messages(behaviour)
    a._client = type("C", (), {"messages": msgs})()  # type: ignore[assignment]
    return a, msgs


def test_anthropic_request_shape_per_model_and_cost() -> None:
    a, msgs = _adapter(lambda _k: _Resp('{"ok": true}'))
    raw = a.complete(_request(), "claude-haiku-4-5", {"type": "object"}, None)
    sent = msgs.calls[0]
    assert sent["extra_body"] == {"temperature": 0.0}
    assert "effort" not in sent["output_config"]
    assert sent["output_config"]["format"]["type"] == "json_schema"
    assert sent["messages"][0]["content"][0]["type"] == "image"
    assert raw.text == '{"ok": true}'
    a.complete(_request(), "claude-sonnet-5-5", {"type": "object"}, "fix field x")
    sent = msgs.calls[1]
    assert "extra_body" not in sent
    assert sent["output_config"]["effort"] == "medium"
    assert "fix field x" in sent["messages"][0]["content"][-1]["text"]
    assert a.cost_usd("claude-haiku-4-5", 1_000_000, 100_000) == pytest.approx(1.5)
    assert a.cost_usd("claude-sonnet-5-5", 1_000_000, 100_000) == pytest.approx(3.0)
    est_in, est_out = a.estimate_tokens(_request())
    assert est_in > 1500
    assert est_out == 512


def test_anthropic_errors_are_classified() -> None:
    import anthropic

    req = httpx2.Request("POST", "https://api.anthropic.com/v1/messages")

    def rate(_k: Any) -> Any:
        raise anthropic.RateLimitError(
            "slow", response=httpx2.Response(429, request=req), body=None
        )

    def auth(_k: Any) -> Any:
        raise anthropic.AuthenticationError(
            "bad", response=httpx2.Response(401, request=req), body=None
        )

    for fn, retryable, text in ((rate, True, "temporarily"), (auth, False, "set-key")):
        a, _ = _adapter(fn)
        with pytest.raises(AdapterError, match=text) as info:
            a.complete(_request(), "claude-haiku-4-5", {}, None)
        assert info.value.retryable is retryable
    a, _ = _adapter(lambda _k: _Resp("", stop="refusal"))
    with pytest.raises(AdapterError, match="declined"):
        a.complete(_request(), "claude-haiku-4-5", {}, None)


def _task_ctx(tmp_path: Path, limit: float | None = None) -> TaskContext:
    control = ControlDB()
    me = control.local_principal
    ConfigService(control).set_provider(me, "vision", "fake", "fake-1")
    project = init_project(control, me, tmp_path)
    store = JobStore(control.db)
    store.create_job(
        me,
        JobSpec(
            project.id,
            "t",
            cost_limit_usd=limit,
            tasks=[TaskSpec("x", "s", resource_class=ResourceClass.AI_API)],
        ),
    )
    leased = store.lease("w", "ai_api")
    assert leased is not None
    return TaskContext(leased, "w", LocalExecutor(store), store, project, control=control)


def test_aiclient_caches_validates_and_records(tmp_path: Path) -> None:
    ctx = _task_ctx(tmp_path)
    client = AIClient(ctx)
    before = len(fake.CALLS)
    first = client.structured("vision", "healthcheck", 1, {})
    assert (first.cached, first.provider) == (False, "fake")
    assert len(fake.CALLS) == before + 1
    again = client.structured("vision", "healthcheck", 1, {})
    assert again.cached
    assert again.provenance_id == first.provenance_id
    assert len(fake.CALLS) == before + 1  # zero calls for an identical request
    client.structured("vision", "healthcheck", 1, {}, variant=1)
    assert len(fake.CALLS) == before + 2  # --variant forces a fresh take
    # Changing the model changes the adapter call and the cache key (acceptance 7).
    assert ctx.control is not None
    ConfigService(ctx.control).set_provider(ctx.control.local_principal, "vision", "fake", "fake-2")
    other = AIClient(ctx).structured("vision", "healthcheck", 1, {})
    assert not other.cached
    with ctx.project.db.session() as s:
        prov = s.get(Provenance, other.provenance_id)
        assert prov is not None
        assert (prov.provider, prov.model, prov.prompt_version) == (
            "fake",
            "fake-2",
            "healthcheck/v1",
        )
    with ctx.control.db.session() as s:
        usage = list(s.scalars(select(UsageRecord)))
    assert len(usage) == 3
    ctx.project.close()


def test_aiclient_retries_once_then_fails(tmp_path: Path) -> None:
    ctx = _task_ctx(tmp_path)
    client = AIClient(ctx)
    before = len(fake.CALLS)
    ok = client.structured("vision", "healthcheck", 1, {"_fake_invalid_first": True})
    assert ok.data.model_dump() == {"ok": True}
    assert len(fake.CALLS) == before + 2
    with pytest.raises(PermanentError, match="invalid output after retry"):
        # A distinct variant: the identical request above is (correctly) served from cache.
        client.structured("vision", "healthcheck", 1, {"_fake_always_invalid": True}, variant=7)
    ctx.project.close()


def test_cost_limit_pauses_job_and_defers(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(fake.FakeAdapter, "cost_usd", lambda self, model, i, o: 0.4)
    ctx = _task_ctx(tmp_path, limit=1.0)
    client = AIClient(ctx)
    client.structured("vision", "healthcheck", 1, {})
    client.structured("vision", "healthcheck", 1, {}, variant=1)
    with pytest.raises(DeferTask, match="cost limit"):
        client.structured("vision", "healthcheck", 1, {}, variant=2)
    job = ctx.store.job(ctx.task.job_id)
    assert job is not None
    assert job.status == "paused_cost_limit"
    assert job.cost_usd == pytest.approx(0.8)
    assert ctx.store.defer(ctx.task.id, "w", "cost limit")
    task = ctx.store.task(ctx.task.id)
    assert task is not None
    assert (task.status, task.attempts) == ("ready", 0)
    ctx.project.close()


def test_config_ai_test_cli() -> None:
    runner = CliRunner()
    missing = runner.invoke(cli, ["config", "ai", "test", "--provider", "anthropic"])
    assert missing.exit_code != 0
    assert "set-key" in missing.output
    runner.invoke(
        cli,
        ["config", "ai", "set", "--capability", "all", "--provider", "fake", "--model", "fake-1"],
    )
    ok = runner.invoke(cli, ["config", "ai", "test"])
    assert ok.exit_code == 0, ok.output
    assert "fake: ok" in ok.output
    runner.invoke(
        cli,
        ["config", "ai", "set-key", "--provider", "anthropic"],
        input="sk-ant-test-1111111111111111\n",
    )
    assert (
        runner.invoke(cli, ["config", "ai", "reset-key", "--provider", "anthropic"]).exit_code == 0
    )
    control = ControlDB()
    assert not ConfigService(control).key_status(control.local_principal, "anthropic").configured


def test_strict_schema_keeps_fields_named_like_keywords() -> None:
    from pydantic import BaseModel, Field

    class Out(BaseModel):
        title: str
        default: int = Field(ge=0)
        pattern: str = Field(max_length=10)
        note: str

    schema = strict_schema(Out.model_json_schema())
    assert set(schema["properties"]) == {"title", "default", "pattern", "note"}
    assert set(schema["required"]) <= set(schema["properties"])
    assert "minimum" not in schema["properties"]["default"]
    assert "maxLength" not in schema["properties"]["pattern"]


def test_cached_answers_need_no_key(tmp_path: Path) -> None:
    ctx = _task_ctx(tmp_path)
    assert ctx.control is not None
    first = AIClient(ctx).structured("vision", "healthcheck", 1, {})
    # Point the capability at a provider without a key: a cache hit must still work only if
    # the provider and model are unchanged, so turn on local_only instead.
    ConfigService(ctx.control).set(ctx.control.local_principal, "ai.local_only", "true")
    again = AIClient(ctx).structured("vision", "healthcheck", 1, {})
    assert again.cached
    assert again.provenance_id == first.provenance_id
    ctx.project.close()


def test_local_models_are_validated_and_resolved_from_the_profile(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from mosaic.ai import registry
    from mosaic.ai.adapters.faster_whisper.transcriber import MODEL_REVISIONS
    from mosaic.ai.adapters.siglip_onnx.embedder import VARIANTS
    from mosaic.core.settings import LOCAL_MODELS

    assert set(LOCAL_MODELS["faster-whisper"]) == set(MODEL_REVISIONS)
    assert set(LOCAL_MODELS["siglip-onnx"]) == set(VARIANTS)
    control = ControlDB()
    cfg = ConfigService(control)
    me = control.local_principal
    with pytest.raises(SettingError, match="supports models"):
        cfg.set_provider(me, "transcriber", "faster-whisper", "large-v9")
    monkeypatch.delenv("MOSAIC_STT_MODEL", raising=False)
    monkeypatch.delenv("MOSAIC_EMBED_VARIANT", raising=False)
    cfg.set_provider(me, "transcriber", "faster-whisper", "small")
    cfg.set_provider(me, "embedder", "siglip-onnx", "quantized")
    tr = registry.transcriber(cfg, me)
    em = registry.embedder(cfg, me)
    assert tr.model.startswith("faster-whisper/small@")
    assert em.model.startswith("siglip-base-patch16-224/quantized@")
    assert em.dim == 768
    monkeypatch.setenv("MOSAIC_STT_MODEL", "medium")  # CI override wins
    assert registry.transcriber(cfg, me).model.startswith("faster-whisper/medium@")


def test_api_validate_secret() -> None:
    from fastapi.testclient import TestClient

    from mosaic.app.main import create_app
    from mosaic.app.services import Services

    svc = Services.create()
    app = create_app(svc)
    app.state.allowed_hosts = {"testserver"}
    client = TestClient(app)
    assert client.post("/api/secrets/db/x/validate").status_code == 404
    missing = client.post("/api/secrets/ai/anthropic/validate").json()
    assert missing["ok"] is False
    assert "set-key" in missing["message"]
    key = "sk-ant-test-2222222222222222"
    put = client.put("/api/secrets/ai/anthropic", json={"value": key})
    assert key not in put.text
    ok = client.post("/api/secrets/ai/fake/validate").json()  # no network in unit tests
    assert ok["ok"] is True
    assert key not in str(ok)


def test_only_adapters_import_provider_sdks() -> None:
    import ast

    root = Path(__file__).resolve().parents[2] / "backend" / "mosaic"
    sdks = {"anthropic", "faster_whisper", "onnxruntime", "huggingface_hub", "ctranslate2"}
    offenders = []
    for path in root.rglob("*.py"):
        rel = path.relative_to(root).as_posix()
        if rel.startswith("ai/adapters/"):
            continue
        for node in ast.walk(ast.parse(path.read_text())):
            names = []
            if isinstance(node, ast.Import):
                names = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                names = [node.module]
            offenders += [f"{rel}: {n}" for n in names if n.split(".")[0] in sdks]
    assert not offenders, offenders
