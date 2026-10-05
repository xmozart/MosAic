"""``mosaic config``: settings, AI providers and keys (ADR 0003).

Keys are read from a hidden prompt or from stdin, never from the command line.
"""

from __future__ import annotations

import sys

import click

from mosaic.core.settings import SettingError
from mosaic.storage import secrets
from mosaic.storage.config import ConfigService
from mosaic.storage.control import ControlDB


def _service() -> tuple[ControlDB, ConfigService]:
    control = ControlDB()
    return control, ConfigService(control)


@click.group("config")
def config() -> None:
    """Show and change MosAic settings, AI providers and API keys."""


@config.command("show")
def show() -> None:
    """Providers per capability, key status (last 4 characters only) and settings."""
    control, svc = _service()
    me = control.local_principal
    try:
        click.echo("AI providers")
        providers = svc.providers(me)
        keys_needed: set[str] = set()
        for cap, st in providers.items():
            ch = st.choice
            click.echo(f"  {cap:12s} {ch.provider:15s} {ch.model:24s} {ch.mode:6s} ({st.source})")
            if st.needs_key:
                keys_needed.add(ch.provider)
        click.echo("API keys")
        for provider in sorted(keys_needed):
            ks = svc.key_status(me, provider)
            if ks.configured:
                click.echo(f"  {provider:15s} configured (…{ks.last4 or '????'})")
            else:
                hint = ks.error or f"run `mosaic config ai set-key --provider {provider}`"
                click.echo(f"  {provider:15s} missing — {hint}")
        click.echo("Settings")
        for key, sv in sorted(svc.settings(me).items()):
            shown = sv.value if sv.value not in ("", None) else "(not set)"
            click.echo(f"  {key:30s} {shown} ({sv.source})")
        corpus = svc.get(me, "eval.corpus_dir")
        if not corpus:
            click.echo(
                "Eval corpus: not configured — run `mosaic config set eval.corpus_dir <path>`"
            )
    finally:
        control.db.dispose()


@config.command("set")
@click.argument("key")
@click.argument("value")
def set_setting(key: str, value: str) -> None:
    """Set a setting, e.g. `mosaic config set eval.corpus_dir ~/MosAicCorpus`."""
    control, svc = _service()
    try:
        sv = svc.set(control.local_principal, key, value)
        click.echo(f"{key} = {sv.value}")
    except SettingError as exc:
        raise click.ClickException(str(exc)) from exc
    finally:
        control.db.dispose()


@config.command("reset")
@click.argument("key")
def reset_setting(key: str) -> None:
    """Return a setting to its default."""
    control, svc = _service()
    try:
        sv = svc.reset(control.local_principal, key)
        click.echo(f"{key} = {sv.value} (default)")
    except SettingError as exc:
        raise click.ClickException(str(exc)) from exc
    finally:
        control.db.dispose()


@config.group("ai")
def ai() -> None:
    """AI provider and key settings."""


@ai.command("set")
@click.option(
    "--capability",
    required=True,
    help="vision, planner, selector, critic, transcriber, embedder, or all",
)
@click.option("--provider", required=True)
@click.option("--model", required=True)
def ai_set(capability: str, provider: str, model: str) -> None:
    """Choose the provider and model for a capability."""
    control, svc = _service()
    try:
        for ch in svc.set_provider(control.local_principal, capability, provider, model):
            click.echo(f"{ch.capability}: {ch.provider} {ch.model}")
    except SettingError as exc:
        raise click.ClickException(str(exc)) from exc
    finally:
        control.db.dispose()


@ai.command("use")
@click.argument("provider")
def ai_use(provider: str) -> None:
    """Use PROVIDER for every AI capability with its preset models.

    anthropic needs an API key; claude-cli and codex-cli use the installed Claude Code or
    Codex app and your own sign-in, no key (ADR 0014)."""
    from mosaic.core.settings import preset

    control, svc = _service()
    try:
        models = preset(provider)
        svc.set_providers_many(
            control.local_principal, {cap: (provider, m) for cap, m in models.items()}
        )
        for cap, m in models.items():
            click.echo(f"{cap}: {provider} {m}")
        if (
            provider == "anthropic"
            and not svc.key_status(control.local_principal, provider).configured
        ):
            click.echo("next: mosaic config ai set-key --provider anthropic")
        else:
            click.echo(f"check it with: mosaic config ai test --provider {provider}")
    except SettingError as exc:
        raise click.ClickException(str(exc)) from exc
    finally:
        control.db.dispose()


@ai.command("test")
@click.option("--provider", default=None, help="Default: every provider the profile uses.")
def ai_test(provider: str | None) -> None:
    """Check each AI provider in use with one minimal call (key or app sign-in)."""
    from mosaic.ai.health import check_provider

    control, svc = _service()
    me = control.local_principal
    try:
        if provider:
            providers = [provider]
        else:
            providers = sorted(
                {
                    st.choice.provider
                    for st in svc.providers(me).values()
                    if st.choice.mode != "local" or st.choice.provider == "fake"
                }
            )
        failed = False
        for p in providers:
            r = check_provider(svc, me, p)
            if r.ok:
                click.echo(f"{p}: ok ({r.model}, {r.latency_ms} ms, ${r.cost_usd:.5f})")
            else:
                failed = True
                click.echo(f"{p}: FAILED — {r.message}")
        if failed:
            raise click.ClickException("provider check failed")
    finally:
        control.db.dispose()


@ai.command("reset-key")
@click.option("--provider", required=True)
def ai_reset_key(provider: str) -> None:
    """Remove a provider key from the OS keyring."""
    control, svc = _service()
    try:
        svc.reset_key(control.local_principal, provider)
        click.echo(f"{provider} key removed")
    except (SettingError, secrets.SecretError) as exc:
        raise click.ClickException(str(exc)) from exc
    finally:
        control.db.dispose()


@ai.command("set-key")
@click.option("--provider", required=True)
def ai_set_key(provider: str) -> None:
    """Store a provider API key in the OS keyring (hidden prompt, or piped on stdin)."""
    if sys.stdin.isatty():
        value = click.prompt(f"{provider} API key", hide_input=True, prompt_suffix=": ")
    else:
        value = sys.stdin.readline()
    value = value.strip()
    control, svc = _service()
    try:
        ks = svc.set_key(control.local_principal, provider, value)
        click.echo(f"{provider} key stored in the OS keyring (…{ks.last4 or '????'})")
    except (SettingError, secrets.SecretError) as exc:
        raise click.ClickException(secrets.redact(str(exc), value)) from None
    finally:
        control.db.dispose()
