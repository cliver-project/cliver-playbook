# ADR-0003: RBAC tables and the code-defined permission catalog

**Status:** Accepted (2026-10-15; write-up 2026-10-17 — the decision shipped with the
user package, whose modules cite it). Amended 2026-10-16 (package-extensible catalog).
**Context:** Authorization for every surface (REST, MCP, admin UI) is role-based: roles
are bundles of permission codes, users hold roles. The open question was where the
*set of permissions that may exist* is defined — in the database, where admins can
edit it, or in code.

## Decision

1. **Four RBAC tables, no `permissions` table.** `users`, `roles`, `user_roles`
   (M2M + `granted_by`) and `role_permissions` (role → permission *code*, a string).
   Permission codes are not a foreign key because they are not rows.

2. **The catalog is code.** `auth/permissions.py` holds the curated list — `code`,
   human `name`, and a `group` for UI presentation. `GET /api/v1/admin/permissions`
   dumps it for the admin UI's pick-list, and `PUT /roles/{id}/permissions` rejects
   any code outside it (400). Adding a capability is one commit that adds a catalog
   entry *and* a `require_perm("<code>")` call site: a permission with no enforcement
   point does not exist.

3. **The enforcement chain is one dependency, in order.**
   `get_current_user` resolves the bearer token to a user with roles and permissions
   loaded fresh, applies the `must_change_password` gate, then `require_perm("…")`
   checks the code and the route body runs. Deny by default: a route without
   `require_perm` is authenticated but ungated, which is a deliberate, reviewable
   choice at each call site.

4. **`admin` is a seeded role holding every catalog code — not a hardcoded
   superuser.** No code path branches on "is this user an admin"; branches read
   permissions. Seed roles carry `is_system`, which protects them from deletion and
   rename. This is what a fix looks like: the predecessor's `ROLE_PERMISSIONS`
   dictionary in code had drifted from the codes that actually existed, so "admin"
   silently lacked capabilities the UI offered.

5. **Self-protection rules are enforced server-side**: a user cannot delete,
   deactivate or downgrade themselves, and the last holder of the admin role cannot
   lose it. Removing the final admin locks everyone out permanently, and no UI state
   can be trusted to prevent that.

6. **The catalog is package-extensible** (amendment, 2026-10-16 — the package split).
   A package that composes on top registers its own codes with
   `register_permission_codes()` at import time; readers go through
   `permission_catalog()` / `permission_codes()` **at the point of use**, never a
   module-level snapshot. A pure identity deployment therefore carries only the base
   codes, a composed one carries base + registered, and the admin pick-list,
   role-binding validation and the migration seed all read the same merged view.
   The seed is the load-bearing case: it runs inside a process that may or may not
   have imported the MCP package, and the admin role must end up with exactly the
   codes that process knows about.

## Consequences

- Permissions apply to the **next request**: no caching layer between RBAC changes
  and enforcement. One indexed join per request is the price, and it buys instant
  revocation.
- Codes are wire-stable identifiers: renaming one is a breaking change for stored
  `role_permissions` rows and for external clients, so codes are added, not renamed.
- Audit rows record the acting user; combining them with `role_permissions` history
  is what reconstructs "who could do this at the time".

## Alternatives considered

- **A `permissions` table** (the textbook RBAC schema): rejected — admins could bind
  codes with no enforcement point, the table needs seeding and migrating on every
  code change, and the catalog would exist in two places (table + `require_perm`
  call sites) with nothing keeping them aligned.
- **Roles and permissions as code** (a literal dict of role → codes): rejected — it
  makes the split between seeded roles and admin-created roles imaginary, and it is
  exactly the construct that drifted in the predecessor.
- **Route-level permission lists in one table** (a central mapping file): rejected —
  a permission check belongs next to the handler that needs it, where a reader sees
  it; a central file is a second place to forget.
