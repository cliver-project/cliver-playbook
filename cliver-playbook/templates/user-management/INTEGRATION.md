# user-management — integration manifest

How this template relates to `templates/service-scaffold`: it IS the scaffold
plus the identity-domain delta below, as one complete runnable app. The
`add-user-management` skill applies this manifest to a scaffold-derived
project — copying every ADD, applying every REPLACE, and checking each EDIT
trigger. Relative paths are template-root-relative (`backend/…`,
`frontend/…`).

Rule of thumb for REPLACE files: they are strict supersets of the scaffold
version — everything the scaffold had is still there, identity concerns are
added around it. When the target project has already diverged from the
scaffold, the skill must three-way compare (scaffold ↔ template ↔ target) and
replay the identity additions onto the target's version instead of
overwriting it.

## Backend — ADD

| File | Contents |
|---|---|
| `backend/app/auth/__init__.py` | Empty package marker. |
| `backend/app/auth/passwords.py` | PBKDF2-SHA256 hash/verify (200k iters), `needs_rehash`, async wrappers via `asyncio.to_thread`. |
| `backend/app/auth/tokens.py` | The single `auth_tokens` table's three token kinds (web / static / OAuth access), issue/verify/revoke with the ADR-0004 predicate discipline. `revoke_all_for_user` is the choke point that also revokes the OAuth refresh-token store. |
| `backend/app/auth/permissions.py` | The code-defined permission catalog (the authority — no permissions table); 11 codes incl. `oauth:read`/`oauth:revoke` for provider administration. |
| `backend/app/auth/dependencies.py` | `Viewer`, `get_current_user` (bearer → viewer, must-change-password 403 gate + allow-list), `require_perm()` with import-time code validation. |
| `backend/app/auth/audit.py` | `write_audit()` + secret sanitizing (redact, truncate, depth-limit). |
| `backend/app/auth/oidc.py` | OIDC client: provider registry, discovery cache, PKCE, HMAC state cookie, userinfo identification, `_open_client()` test seam. |
| `backend/app/auth/oauth21.py` | OAuth 2.1 provider: DCR, PKCE, HMAC login-blob hand-off to the SPA authorize page, atomic code claim, refresh rotation + replay detection, family revocation, AS/PRM metadata, `mount_oauth_routes()`. Exposes `revoke_grant()` (caller-session, no commit) — the per-(user × client) revocation the admin endpoint uses. |
| `backend/app/core/timeutil.py` | `utcnow()` tz-aware helper (scaffold uses inline `func.now()` defaults; identity code needs Python-side timestamps). |
| `backend/app/services/users.py` | User CRUD + role assignment, self-protections, last-admin guard, `authenticate()` with lockout. |
| `backend/app/services/roles.py` | Role CRUD, catalog-validated permission binding, system-role protection. |
| `backend/app/schemas/auth.py` | All identity request/response models (never exposes hashes). |
| `backend/app/api/auth.py` | `/api/v1/auth/*`: login/logout/me/change-password/profile (self-service contact edit), OIDC login+callback, OAuth authorize info+submit. One commit per request at the end; failed login commits audit before raising. |
| `backend/app/api/admin.py` | `/api/v1/admin/*`: permissions catalog, users CRUD + reset-password + force-logout, roles CRUD, OAuth provider administration (client listing, live grants, per-grant revoke — DCR is open, so the listing is the operator's only visibility), audit listing. Every endpoint declares `require_perm`. |
| `backend/alembic/versions/0002_user_management.py` | 10 identity tables + seed (admin role = all catalog permissions, user role, admin user with forced first-login change). Chains onto `0001_scaffold_base`. |
| `backend/tests/helpers.py` | `seed_admin()`, `login()` shared by the identity suites. |
| `backend/tests/test_auth_password.py` | 9 tests: login, 401 audit, lockout, gate, change-password semantics, revocation, expiry. |
| `backend/tests/test_rbac.py` | 9 tests: catalog, role CRUD, permission effectiveness, 403 matrix, self/last-admin protections, token-kind isolation, audit listing. |
| `backend/tests/test_oidc.py` | 7 tests via `httpx.MockTransport` (zero network): redirect shape, callback provision/linking (incl. `phone_number` claim), state tamper. |
| `backend/tests/test_oauth21.py` | 14 tests: metadata shape (byte-exact iss), DCR, full code+PKCE flow, single-use codes, refresh rotation/replay, revocation — incl. the regressions that password change / force logout / admin reset also kill OAuth refresh tokens (no grant revival after re-password), and the admin surface: client/grant listings, per-grant revoke (kills access + refresh, idempotent, audited), permission 403 matrix. |
| `backend/tests/test_profile.py` | 6 tests: admin phone roundtrip (set/absent-unchanged/""-clears), duplicate-email 409 (admin + self paths), self profile update + field-list audit, unset-vs-clear semantics, must-change-gate whitelist. |

## Backend — REPLACE (scaffold-owned files, strict supersets)

| File | What changed vs scaffold |
|---|---|
| `backend/app/models/entities.py` | Same demo `Item`; adds the 10 identity tables (users, roles, user_roles, role_permissions, oauth_identities, oauth_clients, oauth_codes, oauth_refresh_tokens, auth_tokens, audit_logs) with named constraints/indexes. `Item` timestamps gained explicit `DateTime(timezone=True)` — mirror that onto a diverged target (keeps `alembic autogenerate` quiet). |
| `backend/app/core/config.py` | Adds the identity settings block: `secret_key`/`hmac_secret`, `initial_admin_password`, token TTL, lockout, `oidc_*`, `web_base_url`, `oauth21_*`. Scaffold settings untouched. |
| `backend/app/main.py` | Adds `RequestMetaMiddleware` (ip/user-agent capture for audit), includes the auth + admin routers, and mounts the OAuth 2.1 routes at the root when enabled. The mcp-server template later moves that mount into its sub-app. |
| `backend/pyproject.toml` | Adds `email-validator` (EmailStr) and `mcp>=2.2.0,<3` (OAuth 2.1 routes use the SDK's request/response models). |
| `backend/tests/conftest.py` | Same DB lifecycle; adds the `admin_headers` fixture (seed + login). |
| `backend/tests/__init__.py` | Adds the package docstring (pytest 9 resolves helpers as `tests.<module>`). |

## Frontend — ADD

| File | Contents |
|---|---|
| `frontend/src/api/auth.ts` | Typed wrappers for every identity endpoint (session incl. `updateProfile`, SSO, authorize, admin users/roles/permissions/OAuth clients+grants+revoke/audit). |
| `frontend/src/components/auth/AuthContext.tsx` | Session state (`loading`/`authenticated`/`anonymous`), token storage, login/logout/adoptToken/refresh, `hasPerm` for display gating. |
| `frontend/src/components/auth/RequirePerm.tsx` | Route-level permission gate rendering an explicit no-access panel. |
| `frontend/src/components/auth/AuthShell.tsx` | Centered card chrome for the standalone auth pages. |
| `frontend/src/pages/LoginPage.tsx` | Password form + SSO buttons (rendered only when `/auth/oauth/providers` lists any). |
| `frontend/src/pages/ChangePasswordPage.tsx` | Self-service change; lands here for must-change accounts (also reachable directly). |
| `frontend/src/pages/OAuthCallbackPage.tsx` | OIDC landing: parses `#token=…`/`#error=…`, scrubs the fragment, adopts the session. |
| `frontend/src/pages/OAuthAuthorizePage.tsx` | OAuth 2.1 agent consent: shows client + scopes from the signed blob, submits credentials once, navigates the returned redirect URL. |
| `frontend/src/pages/ProfilePage.tsx` | Self-service profile (`/profile`, every authenticated user): display-name/email/phone form + inline password change that adopts the re-issued token. |
| `frontend/src/pages/admin/UsersPage.tsx` | Users table + create/edit dialogs, reset password, force logout, delete — every action permission-gated in the UI. |
| `frontend/src/pages/admin/RolesPage.tsx` | Roles table + editor with the permission catalog grouped by `group`; system roles protected. |
| `frontend/src/pages/admin/OAuthPage.tsx` | OAuth provider view (`/oauth`, gated by `oauth:read`): active grants (user × client × scopes × expiry) with per-grant revoke behind `oauth:revoke`, plus the registered-client listing. |
| `frontend/src/pages/admin/AuditPage.tsx` | Read-only audit trail with event/username filters and offset pagination. |

## Frontend — REPLACE (scaffold-owned files, strict supersets)

| File | What changed vs scaffold |
|---|---|
| `frontend/src/api/client.ts` | Adds token storage helpers (`cliver-token` localStorage key), default bearer source, and the response interceptors: 401 → clear + hard redirect `/login`; 403 `must_change_password` → `/change-password` (both loop-suppressed on auth pages). |
| `frontend/src/App.tsx` | Wraps routes in `AuthProvider`; adds the standalone auth routes (`/login`, `/change-password`, `/auth/callback`, `/oauth/authorize`), the ungated `/profile` route, and the permission-guarded admin routes (`/users`, `/roles`, `/oauth`, `/audit`) around the scaffold's `/` and `/items`. The admin `/oauth` page coexists with the standalone `/oauth/authorize` flow page (react-router ranks the exact match higher). |
| `frontend/src/layouts/AppLayout.tsx` | Adds the auth guard (loading placeholder, anonymous → `/login` with return path, must-change → gate), permission-gated admin nav items, and the user menu with Profile + logout (the scaffold's Home/Items entries stay ungated). |
| `frontend/src/locales/en.json` | Adds `nav.*`, `auth.*`, `admin.*`, `profile.*` keys (scaffold keys untouched). |
| `frontend/src/locales/zh.json` | Same keys, Chinese. |

## Root — REPLACE

| File | What changed vs scaffold |
|---|---|
| `.env.example` | Documents the identity settings block (all commented; defaults shown). |

## EDIT

None — every change folds into the REPLACE supersets. The Alembic chain needs
no edits either: `0002_user_management` hangs off `0001_scaffold_base`
(down_revision fixed). In a project whose chain has diverged, adjust
`down_revision` to the current head (or `alembic merge`) instead.

## Post-copy checklist

1. `cd backend && uv sync` — installs `email-validator` + `mcp`.
2. `uv run alembic upgrade head` — creates the identity tables and prints the
   generated admin password if `CLIVER_INITIAL_ADMIN_PASSWORD` was unset.
   A database already migrated from an OLDER copy of this template (before
   the OAuth catalog codes existed) needs the admin role granted
   `oauth:read`/`oauth:revoke` manually — fresh installs seed them from the
   catalog automatically.
3. `uv run pytest` — 54 tests (45 identity + 9 scaffold), all offline-capable
   except the DB (needs the compose PostgreSQL).
4. `cd frontend && pnpm install && pnpm build` — no new frontend dependencies.
5. Manual: log in as admin → forced password change → Users/Roles/OAuth/Audit
   pages; create a role without permissions → that account sees no admin nav
   and gets 403s server-side; open the user menu → Profile → edit contact
   details and change the password (other sessions drop); connect an agent via
   OAuth once → the grant appears on the OAuth page → revoke it → the agent's
   token dies.

## Not included (deliberate)

- Email verification / password reset by email — needs an SMTP story; add per
  project when real. (Self-service profile editing of display name/email/phone
  IS included; what is missing is *verifying* the email address.)
- User avatar upload — needs a file-storage story per project.
- TOTP/WebAuthn second factor — the token/audit plumbing is ready for it.
