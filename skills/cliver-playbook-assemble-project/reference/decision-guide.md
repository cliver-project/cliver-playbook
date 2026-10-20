# Decision guide: reuse, configure, create, vendor

Apply the tests in order. The first one that answers is the disposition.

1. **Does a playbook package already provide it?** → *Reuse.*
2. **Does an existing setting, registry, router seam, or extension point
   change it?** → *Configure.*
3. **Is it specific to this product's domain?** → *Create.*
4. **None of the above, and the change is genuinely required?** → *Vendor*,
   with a written reason and provenance.

Most new-project work stops at 1 and 3. Reaching 4 is a design smell until
proven otherwise.

## Backend capability matrix

| Capability | Disposition | What the project does |
|---|---|---|
| Layered configuration | Reuse | Subclass the most-derived package `Settings`; add project fields. |
| Process runtime, engine, session factory | Reuse | Call `runtime.configure()` once from `create_app`; use `get_db` / `open_session`. |
| Declarative base and migration machinery | Reuse | Use a project-owned `Base` and a project Alembic chain with its own version table. |
| Health, version, demo Items API | Reuse | Include `basic.ROUTERS`; ignore or keep the demo Items surface. |
| Accounts, sessions, password policy | Reuse | Include `user.ROUTERS`; configure policy fields. |
| RBAC | Reuse + configure | Register project permission codes; assign them to roles. |
| OIDC login | Configure | Add providers to `oidc.providers.<key>`; no code change. |
| OAuth 2.1 provider for agents | Reuse + configure | `oauth21_*` settings; routes are added by `mount_oauth_routes`. |
| Audit log | Reuse | Call `write_audit` from project services; never create another log table. |
| Runtime settings UI | Reuse + create | Register one project `SettingsSection`; the admin page renders it. |
| RAG pipeline (chunk, embed, retrieve, rerank, generate) | Reuse | Select stages in `rag.*`; bind cliver-core purposes. |
| Custom RAG stage | Create + register | Implement the package protocol, register in the registry, and route model access through cliver-core. |
| MCP protocol endpoint and gate | Reuse | Include `mcp.ROUTERS` and compose the MCP lifespan. |
| MCP tools | Create | Decorate project functions with `@mcp.tool()` plus `@public_tool()` or `@require_perm(...)`. |
| Test harness | Copy once | Adapt a package `tests/conftest.py`; the pattern is the asset. |
| Makefile, ruff/pytest/oxlint config | Copy once | Project-specific paths and targets; own it after copying. |

## Frontend capability matrix

| Capability | Disposition | What the project does |
|---|---|---|
| Providers, layout, route table | Reuse as pattern | Copy the matching `dev/` shell; keep provider order. |
| Theme and design tokens | Reuse + configure | Import the basic stylesheet; override CSS variables in the app stylesheet. |
| i18n | Reuse | `createI18n(...)` with every package bundle plus the project bundle. |
| HTTP client and auth interceptors | Reuse | `installAuthClient()` once, before the first request. |
| UI primitives, CRUD pattern | Reuse as pattern | Import from package roots or deep paths with the file extension. |
| Sign-in, profile, admin pages | Reuse | Route arrays from `cliver-playbook-app-user`. |
| RAG pages | Reuse | `ragRoutes`, `ragNavItems`, `ragStandaloneRoutes`. |
| MCP pages | Reuse | `mcpRoutes`, `mcpNavItems`. |
| Project pages, routes, navigation | Create | Add route objects and `extraNavItems`; add translation keys. |
| Demo Items page | Reuse as pattern | It rides with `basicRoutes`; removing it from a composed install is not supported. |
| Vite/tsconfig/oxlint tooling | Reuse | Extend `cliver-playbook-app-basic/tooling/*`; copy `.oxlintrc.json`. |

## The exact seams

### 1. Settings subclass

Subclass the most-derived package for the chosen profile, never a parallel
class:

```python
# app/settings.py
from cliver_playbook.app.mcp.settings import Settings as PlaybookSettings


class Settings(PlaybookSettings):
    """Project settings; every playbook block is inherited unchanged."""

    feature_orders_enabled: bool = True
```

- `minimal` → `cliver_playbook.app.basic.settings.Settings`
- `web` → `cliver_playbook.app.user.settings.Settings`
- `rag` → `cliver_playbook.app.rag.settings.Settings`
- `mcp` → `cliver_playbook.app.mcp.settings.Settings`

The subclass is what `runtime.configure()` binds, so every package's
`settings` proxy serves it. Fields can come from the environment
(`CLIVER_<FIELD>`), `.env`, runtime overrides, `app.yaml` (bare field names),
or defaults — in that precedence order.

### 2. Project permission codes

Register them at import time, before any route or tool guard uses them:

```python
# app/permissions.py
from cliver_playbook.app.user.auth.permissions import (
    Permission,
    register_permission_codes,
)

register_permission_codes(
    [
        Permission("orders:read", "View orders", "Orders"),
        Permission("orders:write", "Create and edit orders", "Orders"),
    ]
)
```

Import `app.permissions` from `app/__init__.py` or from `create_app` before
the app is built, and from `migrate.py` before the identity chain seeds roles.
The catalog is the single source of truth for the admin pick-list, role
binding validation, and the seed. A code registered twice with different
metadata raises at import.

Codes are `resource:action`. Reserve `settings:*`, `user:*`, `role:*`,
`audit:*`, `oauth:*`, `rag:*`, and `mcp:*` for the owning packages.

### 3. Project runtime settings section

Only for knobs an administrator should change without a restart. Bootstrap
values and credentials stay in the environment.

```python
# app/settings_section.py
from typing import Any

from cliver_playbook.app.basic.runtime_settings import (
    SettingsField,
    SettingsSection,
    register_settings_section,
)


def _fields() -> tuple[SettingsField, ...]:
    return (
        SettingsField(
            name="feature_orders_enabled",
            label="Enable orders",
            type="boolean",
            description="Turns the orders surface on for this deployment.",
            env_var="CLIVER_FEATURE_ORDERS_ENABLED",
        ),
    )


def _read(settings: Any) -> dict[str, Any]:
    return {"feature_orders_enabled": settings.feature_orders_enabled}


def _apply(settings: Any, values: dict[str, Any]) -> None:
    # Validate fully before mutating: compute the merged state first.
    merged = {**_read(settings), **values}
    settings.feature_orders_enabled = bool(merged["feature_orders_enabled"])


register_settings_section(
    SettingsSection(
        key="orders",
        title="Orders",
        description="Project-owned feature switches.",
        fields=_fields,
        read=_read,
        apply=_apply,
    )
)
```

The section key is process-wide and must be unique. Import the module at
startup, ideally from `app/__init__.py`. The admin settings page lists it
automatically; a missing frontend translation falls back to the English
strings the backend returns.

### 4. Project MCP tools

The tool decorators are the only place that enforce permissions, write the
audit row, apply the concurrency cap, and time the call:

```python
# app/tools/orders.py
from typing import Any

from cliver_playbook.app.mcp.server import mcp
from cliver_playbook.app.mcp.toolkit import require_perm

from app.services.orders import list_orders


@mcp.tool()
@require_perm("mcp:tools:invoke", "orders:read")
async def list_recent_orders(limit: int = 20) -> list[dict[str, Any]]:
    """Return the most recent orders visible to the caller."""
    return await list_orders(limit=limit)
```

Import every project tool module at process start, before
`create_app()` runs — for example from `app/tools/__init__.py`, imported at
the top of `app/app.py`. A tool module that is never imported is never
registered, and the endpoint will not list it. Use `@public_tool()` only for
diagnostics that carry no data; it is greppable on purpose.

### 5. Custom RAG stage

Prefer an existing stage plus cliver-core bindings. If the project truly needs
a new chunker, embedder, retriever, reranker, or generator, implement the
package protocol and register it at import time:

```python
from cliver_playbook.app.rag.chunking import registry

registry.register("orders-markdown", lambda: OrdersMarkdownChunker())
```

Import it before the app serves `GET /api/v1/rag/stages`. All model calls go
through cliver-core. If the stage is reusable beyond this product, contribute
it to the playbook instead of keeping it in the project.

### 6. Frontend composition

```tsx
const routes: RouteObject[] = [
  {
    element: <AuthAppLayout extraNavItems={[...ragNavItems, ...projectNavItems]} />,
    children: [...basicRoutes, ...userRoutes, ...ragRoutes, ...projectRoutes],
  },
  ...userStandaloneRoutes,
  ...ragStandaloneRoutes,
  { path: "*", element: <Navigate to="/" replace /> },
];
```

```tsx
installAuthClient();
createI18n(userTranslations, ragTranslations, projectTranslations);
```

```css
@import "cliver-playbook-app-basic/styles/index.css";
@source "../node_modules/cliver-playbook-app-user/src";
@source "../node_modules/cliver-playbook-app-rag/src";
@source "../src";
```

The project's own routes and nav entries are ordinary `RouteObject[]` and
`NavItem[]` values; no package file is edited to accept them.

### 7. Theme

The token variables live in the basic stylesheet. Override them after the
import in the app stylesheet; do not fork the package for branding:

```css
@import "cliver-playbook-app-basic/styles/index.css";

:root,
[data-theme="light"] {
  --color-primary: oklch(0.55 0.15 250);
}
```

## What the project must create

- Domain tables and models, plus the project-owned Alembic chain.
- Domain services, schemas, routers, and their tests.
- Domain permission codes and role assignments.
- Project pages, route objects, nav entries, and translation bundles.
- Project MCP tools, if the profile includes MCP.
- A project settings section, if the product has operator knobs.
- Deployment assets: Dockerfile or process definition, reverse proxy, backup
  and migration steps. The playbook has no deployment opinion.
- `project-manifest.yaml`, `README.md`, `Makefile`, `.gitignore`,
  `.env.example`, and the project brief or decisions.

## When vendoring is legitimate

Vendor only when a required change is impossible through a seam and cannot
reasonably be contributed upstream. Legitimate examples:

- The protocol path must not be `/mcp`, and the product cannot live with the
  fixed path or a reverse-proxy rewrite.
- A core table shape must change in a way no extension table can express.
- A stage implementation is product-specific, cannot use cliver-core, and
  cannot be written as a registered stage.

Not legitimate:

- App name, branding, theme colors, nav items, login copy.
- Adding a page, route, permission code, settings section, or MCP tool.
- Adding a domain table or column — that belongs in the project chain.
- Changing OIDC providers, RAG stage selection, or MCP auth policy — those
  are configuration.
- "I want to understand the code" or "copying feels simpler".

Vendoring costs upstream fixes, security patches, and every future release.
It is an explicit fork, not a faster compose.

Rules when vendoring:

- Copy with `var/playbook/scripts/vendor_package.py --package <name> --target
  . --apply`; repeat `--package` for several packages. Do not rename the
  `cliver_playbook` namespace by hand.
- Never mix compose and vendor for the same package: the installed
  distribution can shadow the vendored tree on `sys.path`.
- Verify the import resolves under `vendor/`:
  `python -c "import cliver_playbook.app.<name> as m; print(m.__file__)"`.
- Record provenance in `vendor/FORKED_FROM.md` and in the manifest's
  `vendored:` entries; the revision is a tag or commit, never a branch.
- Add a comment at each local change, and compare against every later
  playbook tag manually.

## Worked decisions

```yaml
decisions:
  - "Profile web: the first release has accounts and roles but no knowledge base or agent tools."
  - "Reused basic + user; configured Google OIDC through the provider registry (no code)."
  - "Created the orders domain in a project Alembic chain; no playbook table was altered."
  - "Registered orders:read/write; assigned them to the operator role; admin keeps the * wildcard."
  - "Left the demo Items surface in place; it is inert and removing it from a composed install is unsupported."
  - "Vendored nothing. No seam was insufficient."
```
