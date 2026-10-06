# 0036 — Server secret backends

- Status: accepted (M2 step 3c)
- Deciders: agent (autonomous; no human gate)

## Context

ARCHITECTURE.md §3 lists the server's secret sources: environment variables, Docker secrets, or an encrypted file keyed by an install master key. The desktop app keeps the OS keyring (ADR 0003). Two requirements apply everywhere:
- Invariant 11: secrets never touch project files, the DB, browser storage, logs, argv or exports, and the config stores only a `secret_ref`.
- M2: key entry is write-only, the UI shows the last 4 characters, and there is a Validate action.

## Decision

- **References** stay `scheme:name` in the control DB's `secret_ref` table. Four schemes:
  - `keyring:` is the OS keyring, used on desktop.
  - `file:<name>` is the server's encrypted file, `app_data/secrets.enc.json`:
    - mode 0600, written atomically;
    - each value is a Fernet token (`cryptography`: AES-128-CBC with HMAC-SHA256);
    - the key is derived with scrypt (n=2¹⁵, r=8, p=1) from the install master key and a random per-file salt.
  - `env:<VAR>` and `docker:<name>` are keys the deployment provides. They are read-only.
- **Master key.** It comes from `MOSAIC_MASTER_KEY`, or from `MOSAIC_MASTER_KEY_FILE` (for example a Docker secret), and needs at least 32 characters.
  - Without it, saving a key on a server answers 422, naming the setting, or the alternative of a deployment key.
  - If the master key changes, a saved key can't be decrypted. The key status reports "the master key changed. Enter the key again.", and nothing crashes.
- **Deployment keys** need no step in the app:
  - `MOSAIC_SECRET_<NAME>`, for example `MOSAIC_SECRET_AI_ANTHROPIC`;
  - or a Docker secret file `mosaic_<name>`, for example `/run/secrets/mosaic_ai_anthropic`. The directory can be overridden with `MOSAIC_DOCKER_SECRETS_DIR`.
  - When both exist, the Docker secret is used, because it never appears in `docker inspect`.
- **Precedence.** A key the user enters (the stored `secret_ref`) wins over a deployment key, since the user's decision overrides. `DELETE /api/secrets/{ref}` removes the user's key, and the deployment key is used again.
- **Writing.** `set_key` writes to `keyring:` on desktop and to `file:` on a server.
- **Key status responses** carry `configured`, `last4`, `store` (`keychain`, `encrypted_file`, `environment` or `docker`) and `from_deployment`. They never carry the reference, a path or the value.
- **One writer at a time.** Each save or delete in the file store is one read-change-write under a thread lock and a file lock, so other MosAic processes are covered too.
  - The temp file is created fresh with `mkstemp` (0600), fsynced, then renamed into place.
  - A damaged file is reported as "the encrypted key file is damaged; enter the key again", never as a 500, and its content is never echoed.
  - Entering a key again then works: the damaged file is kept aside as `secrets.enc.json.damaged-<ns>` (never deleted) and a fresh store starts.
  - The derived Fernet key is cached per master key and salt, because scrypt is slow on purpose.
- **Child processes never see MosAic secrets.** Installed AI apps (`cli_common.run`), FFmpeg and the probes (`secrets.scrubbed_env`) never receive `MOSAIC_MASTER_KEY`, `MOSAIC_MASTER_KEY_FILE` or any `MOSAIC_SECRET_*` variable; the list is `secrets.SECRET_ENV`. Only the worker process inherits them, because it needs the master key.
- **Layering.** `server_mode()` moves to `core/runtime.py`, so storage code can check the mode without importing the app layer.

## Consequences

- The Docker image (step 10) documents `MOSAIC_MASTER_KEY_FILE` and the `mosaic_*` Docker secrets. The compose example uses Docker secrets, not plain environment values.
- The secret-leak scan (acceptance 3, step 11) also checks `secrets.enc.json` for plain-text keys.
