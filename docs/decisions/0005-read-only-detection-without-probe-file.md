# ADR 0005 — Read-only folder detection without a probe file

- **Status:** accepted (agent decision, M0 step 2)
- **Date:** 2026-10-04

## Context

`ARCHITECTURE.md §4` detects the `read_only` class with a "write probe". `POST
/projects/preview` must not write anything, and invariant 1 makes the footage folder
precious: a stray probe file left by a crash is a modification the owner did not ask for.

## Options

1. Create and delete a probe file in the folder root.
2. Ask the OS: `os.access(path, W_OK | X_OK)`.
3. Option 2 at preview time, then let the first real write (`MosAic/` and the descriptor)
   surface any remaining failure.

## Decision

Option 3. Classification uses `os.access`; `mosaic init` then creates `MosAic/` and writes
the descriptor atomically, and any failure there is reported as an error.

## Consequences

- Some filesystems report `W_OK` but refuse writes (for example ACL-restricted network
  shares). Those fail at `init` with a clear error instead of being classified up front.
- `ARCHITECTURE.md §4` is updated to say "write-permission check".
