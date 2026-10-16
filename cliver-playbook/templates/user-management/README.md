# cliver-app (user-management)

The service scaffold plus the **identity domain**: full RBAC user management,
password + OIDC login, and an OAuth 2.1 provider for AI-agent/API clients —
one complete runnable app. See `INTEGRATION.md` for the exact delta against
`templates/service-scaffold`.

What you get beyond the scaffold:

- **RBAC**: users, roles, a code-defined permission catalog, role-permission
  binding. Admin = a seeded role holding every catalog permission (not a
  hard-coded superuser). Self-protections (no self-delete/deactivate/demote)
  and last-admin-removal guard are server-enforced.
- **Sessions**: opaque DB tokens (SHA-256 at rest, revocable per device),
  brute-force lockout, transparent PBKDF2 re-hash upgrades, and a
  server-enforced must-change-password gate (first login after seeding or an
  admin reset).
- **SSO**: a multi-provider OIDC client — each provider is a settings entry
  (`oidc.providers.<key>`, discovery-based `issuer` or explicit endpoint
  URLs), the login page grows one button per enabled provider, and identities
  attach to local accounts with optional auto-provisioning. Google and
  GitHub presets ship in `app.yaml`, disabled with empty credentials.
- **Linked accounts**: the profile page lists a user's external identities,
  links new ones through the same OIDC redirect chain, and unlinks them —
  with a server-enforced guard that a passwordless account keeps its last
  credential.
- **Layered configuration**: `app.yaml` (committed, secret-free) under
  `.env`/environment overrides under init kwargs — the scaffold mechanism
  with the identity block on top.
- **OAuth 2.1 provider**: DCR + PKCE for agent clients (MCP-style), refresh
  rotation with replay detection, a consent page in the SPA
  (`/oauth/authorize`) fed by a signed short-lived hand-off blob, and an
  admin `/oauth` page listing registered clients and live grants — with
  per-(user × client) revocation that kills access and refresh tokens alike.
- **Audit**: every login, admin mutation, and OAuth event lands in
  `audit_logs`, browsable at `/audit` (needs `audit:read`).

## Quickstart

```bash
make init                   # backend (uv) + frontend (pnpm) dependencies
make backend-start          # starts db container, migrates (seeds admin), serves :8000
make web-ui-start           # serves http://127.0.0.1:5173 (proxies /api to :8000)
# No .env needed: defaults match the bundled compose db. Copy .env.example
# to .env to override — e.g. set CLIVER_INITIAL_ADMIN_PASSWORD to skip the
# one-time random password print during the first migration. Non-secret
# structure lives in the committed app.yaml (env/.env beat it).
```

First login: `admin` / your `CLIVER_INITIAL_ADMIN_PASSWORD` (or the random
password the migration printed once) — the server forces a password change
before anything else.

Verify:

```bash
curl http://127.0.0.1:8000/api/v1/health             # {"status":"ok"}
make backend-test                                      # 87 tests: 78 identity + 9 scaffold
pnpm --dir frontend build                              # type-check + production build
curl -i http://127.0.0.1:8000/.well-known/oauth-authorization-server
```

## Layout

```
app.yaml                   # layered config base: presets + non-secret structure (no secrets)
backend/
  app/auth/              # the identity core
    passwords.py         #   PBKDF2 hash/verify (+ async wrappers)
    tokens.py            #   one table, three token kinds (web/static/oauth) — predicate discipline
    permissions.py       #   the code-defined permission catalog
    dependencies.py      #   get_current_user (gate) + require_perm
    audit.py             #   write_audit + secret sanitizing
    oidc.py              #   OIDC client (multi-provider registry, PKCE, state, userinfo)
    oauth21.py           #   OAuth 2.1 provider (DCR/PKCE/rotation/replay)
  app/core/              # config.py (nested oidc block) + config_yaml.py (scaffold mirror)
  app/services/          # users.py, roles.py (+ scaffold items.py)
  app/api/               # auth.py, admin.py (+ scaffold meta/items)
  app/schemas/auth.py    # request/response contracts (no hashes ever)
  alembic/versions/      # 0001_scaffold_base -> 0002_user_management (tables + seed)
  tests/                 # config, auth_password, rbac, oidc_config, oidc, oauth21, profile,
                         # identity_link (+ scaffold)
frontend/
  src/api/auth.ts        # typed wrappers for every identity endpoint
  src/components/auth/   # AuthContext, RequirePerm, AuthShell
  src/pages/             # Login, ChangePassword, OAuthCallback, OAuthAuthorize, Profile
  src/pages/admin/       # Users, Roles, OAuth, Audit
```

## Conventions (identity-specific)

- **Permissions live in code** (`app/auth/permissions.py`); roles are data.
  Extending the catalog = add to `PERMISSION_CATALOG`; the dump endpoint,
  role editor, and validation follow automatically.
- **New protected endpoints** declare `Depends(require_perm("<code>"))` —
  authorization is reviewable by reading the router top to bottom.
- **The token table is one table** — every query must carry its kind
  discriminators (`client_id IS NULL AND expires_at IS NULL` for static;
  `client_id = …` for OAuth). See the guard comment in `tokens.py`.
- **Audit rows commit with the mutation they describe** (one commit per
  request, at the end); failed logins commit their audit *before* raising.
- UI permission gating (`hasPerm`, `RequirePerm`) is cosmetic — the server
  rejects regardless.
- Sensitive values (passwords, tokens, client secrets) never appear in audit
  detail; `sanitize_detail` redacts and truncates as a backstop.

## Agent clients (OAuth 2.1 in one paragraph)

Register via RFC 7591 dynamic client registration (`POST /register`), send the
user to `/authorize` (they sign in on the SPA consent page), exchange the code
at `/token` with PKCE, and use the bearer against the API. Refresh tokens
rotate on every use; replays inside a short grace window are audited as
retries, replays beyond it revoke the whole token family. Metadata:
`/.well-known/oauth-authorization-server` and
`/.well-known/oauth-protected-resource` (RFC 9728) at the root.
