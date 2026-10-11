# 0064 — Opening a project at the newest schema skips the migration

- Status: accepted (M3 step 6, after the M3.6b push)
- Deciders: agent (autonomous; no human gate)

## Context

M3.6b's GitHub run (38108958737) fixed the memory measurement (ADR 0063) and then failed two timing budgets on the slower runner:
- the 40-hour library list page took 330 ms against 300 ms;
- one of the 5,000-clip filter changes took 318 ms against 300 ms.

Every API request on a project opens it. On the 40-hour project, the open took 44 of the page's 90 ms here, and 37 ms of those were spent in `migrate()`: Alembic, then `PRAGMA foreign_key_check` over every table, inside the migration transaction. It ran on every open, even with nothing to migrate.

## Decision

- `storage.db.migrate` first reads the database's `alembic_version`. When that is the tree's head, which is read once per process from the scripts, it returns without opening a migration. A database behind head, or a new one, migrates exactly as before (ADR 0022's single transaction and foreign-key check).
- The budgets are unchanged.

## Consequences

- A project opens in about 3 ms here (it was 44 ms), and the 40-hour list page takes about 45 ms (it was 90 ms).
- The foreign-key check now runs only when a migration does. That is the only time the schema changes, so the check still guards every migration.
- A database whose version row says head but whose tables differ, which only manual tampering could produce, is no longer re-checked on open. The migration tests cover every real upgrade path.
