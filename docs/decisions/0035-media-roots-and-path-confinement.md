# 0035 — Media roots and path confinement (server mode)

- Status: accepted (M2 step 3b)
- Deciders: agent (autonomous; no human gate)

## Context

On a server, the browser chooses folders through the server ("Server-side browser limited to configured media roots", ARCHITECTURE.md §3). §14 requires the following:
- every path is canonicalised;
- paths outside the media roots are rejected;
- symlinks that escape are rejected;
- browser clients see only relative paths.

M2 acceptance 2 asks for API tests showing that path traversal, symlink escapes and absolute-path requests are rejected.

## Decision

- **Roots** live in the control DB (`media_root`: canonical absolute path, label, source).
  - The admin manages them with `GET/POST/DELETE /api/admin/media-roots`. This is the only API that shows a server path, and only to the admin, who typed it.
  - At start-up, `MOSAIC_MEDIA_ROOTS` (separated by the OS path separator) adds roots with `source: env`. A missing mount is skipped.
- **`storage/media_roots.py`** is the single gate, with three entry points:
  - **`within(root, rel)`** takes a client path relative to a root:
    - it refuses NUL bytes, absolute paths (`/…`, `//…`, `C:…`) and backslash traversal;
    - it joins the path to the canonical root and resolves symlinks;
    - the result must still lie inside the root, so `..`, encoded `..` and symlinks to elsewhere are all refused.
  - **`confine(path)`** checks that an absolute path from a client lies inside some root. Today it serves relink's `choose_folder`; project creation and preview in step 5 will use it too.
  - **`relative(root, path)`** gives the path the client sees: relative, with POSIX separators.
- **`GET /api/fs/browse`**:
  - Without `root`, it lists the roots: id, label and source, with no paths.
  - With `root` and `path`, it lists the folders there, each with its direct video and photo counts (by extension, not recursive) and `has_project`.
  - It also returns breadcrumbs, the counts for the current folder (`here`), and a `next_cursor` after 500 entries.
  - Hidden entries are skipped, and so are symlinks that leave the root. A symlink inside the root is listed under its canonical path.
- **Errors:** an escaping path gets 403 (`PathOutsideRootError`); an unknown root, a missing folder or an unusable name gets 404. Messages never name a real server path.
- **Unreadable entries:** an unreadable child folder is left out of the listing; an unreadable folder itself gets 403. Neither ever produces a 500.
- **Other confined endpoints:**
  - **LUT paths** (`PUT /projects/{pid}/devices` `lut_path`, ADR 0028) go through `confine` in server mode, and the server reads only the canonical path it returns.
  - **Relink** uses the confined path, answers with `{root, path}` (relative), and its messages carry no paths.
- **Desktop mode:** both APIs answer 404, because the desktop app uses the native folder picker.

## Consequences

- **Relink contract.** Server clients never see absolute paths, so the step 5 screens send `{root, path}`, not an absolute `choose_folder`.
- **Environment roots return.** `MOSAIC_MEDIA_ROOTS` is applied at every start, so deleting an env root lasts only until the next restart. S22 marks those roots "from the server's configuration".
- **Symlink race, accepted.** Between the check and the listing, someone who can write inside a root could swap a folder for a symlink. Remote clients can't do that. A later hardening could walk with directory file descriptors and `O_NOFOLLOW`.

- Each new endpoint that takes a filesystem path must go through `media_roots.confine` or `within` in server mode. Today these are relink; project creation and preview arrive in step 5.
- The step 11 secret scan and the route-surface test (ADR 0034) still apply to these routes. All of them require a session.
