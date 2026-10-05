# ADR 0019 — A new AI capability inherits the owner's single provider choice

- **Status:** accepted (agent decision, M1)
- **Date:** 2026-10-05

## Context

The owner chose Claude Code for everything (`mosaic config ai use claude-cli`) before the
`reviewer` capability existed (ADR 0018). The new capability then fell back to the
shipped default (Anthropic API, which needs a key), so the first L3 Airshow eval skipped
every review. A provider choice is the owner's (ADR 0003): the agent must not rewrite it.

## Decision

- Only capabilities added after M0 (`LATER_CAPABILITIES`, currently `reviewer`) can
  inherit. They inherit only when the owner set **every** original cloud capability
  (vision, planner, selector, critic) to **one** provider, which is what
  `mosaic config ai use <provider>` does. A capability the owner never set then follows
  that provider, with the provider's **preset** model, not necessarily the model the owner
  picked elsewhere. A partial or mixed choice keeps the shipped default.
- It is shown as `inherited` in `mosaic config show` and the API. Nothing is written to
  the owner's profile.
- Local capabilities (transcriber, embedder) never inherit.
- `make eval --deepen` checks the reviewer's configuration as well. A deep review whose
  tasks were skipped stops the eval at G1 instead of producing results without L3.

## Consequences

Capabilities added in later milestones (for example a summary model) follow the owner's
choice automatically. The owner can still set any capability explicitly.
