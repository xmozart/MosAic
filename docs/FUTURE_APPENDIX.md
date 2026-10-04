# Future Appendix — Do Not Build, Do Not Preclude

These capabilities are planned for a commercial stage. **Do not implement them.** Before any schema or service design is finalized, check that it does not block them.

## 1. Multi-user server
- Accounts, sessions, revocation.
- Project memberships with Owner / Editor / Viewer roles.
- Per-user preferences.
- Audit history.
- PostgreSQL control plane.

**Guard now:**
- Every control-plane row carries `user_id` (and later `tenant_id`), and every service method takes a `Principal`.
- Authorization is checked through a single `authz.check(principal, action, resource)` even while it always allows.
- The control DB goes through SQLAlchemy repositories with no SQLite-only SQL outside `storage/sqlite_*`.

## 2. Multi-tenant
- Tenants, tenant admins, tenant-scoped media roots, provider profiles, secrets, quotas and budgets, and strict isolation for jobs, caches and search.

**Guard now:**
- Cache and artifact keys include `project_id`.
- Search APIs require a project scope.
- Usage records carry project and user IDs.

## 3. Scale-out
- Distributed workers with capability registration, routing by codec and hardware, shared or object storage, and centralized observability.

**Guard now:**
- Tasks reference artifacts by key, never by absolute path.
- The `Executor` interface is the only way work is dispatched.
- Workers are stateless between tasks.

## 4. Collaboration
- Concurrent viewers, optimistic concurrency, branches, comments, approvals.

**Guard now:**
- The edit version graph (parent links), immutable versions, and draft op logs.

## 5. Commercial hardening
- Licensing and codec patent review: HEVC and AAC encoding in distributed builds, and libopenh264 (Cisco's patent coverage applies only to Cisco-distributed binaries).
- Vendor SDK agreements (Insta360 stitching), telemetry and crash reporting with opt-in, licensed music catalog, and enterprise SSO (OIDC/SAML).
- Cloud secret managers (AWS, Azure, GCP, Vault).
