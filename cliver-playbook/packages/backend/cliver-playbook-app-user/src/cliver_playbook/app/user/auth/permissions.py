"""The permission catalog — a code-defined, package-extensible list (ADR-0003).

There is deliberately NO `permissions` table. Permissions are compile-time
facts of the application: every code that exists has a `require_perm()` call
site somewhere in the routers. A database table would allow admins to bind
nonexistent codes (drift) and would need seeding/migration on every code change.
The catalog here is the single source of truth; roles bind codes from it, and
`PUT /roles/{id}/permissions` rejects anything outside it.

Adding a permission owned by THIS package = add a row to `_BASE_CATALOG` plus a
`require_perm("...")` call site in one commit.

A package that composes on top of this one (the `mcp` package, ADR-0017) adds
its own codes with `register_permission_codes()` — called at that package's
import time, in-memory, before it defines any `require_perm()` call site of its
own (its package `__init__` imports its permissions module first). A pure
`user` deployment therefore carries only the base codes; a composed one carries
base + registered, and the admin UI pick-list, the role-binding validation and
the migration seed all read the same merged view.

Read the catalog through `permission_catalog()` / `permission_codes()` at the
point of use — never by importing a snapshot at module import, or a later
registration would be invisible to that reader (the seed in migration 0001 is
the load-bearing example: applying the chain in a process that imported the
`mcp` package must grant the admin role the `mcp:*` codes too).
"""

from collections.abc import Iterable
from dataclasses import dataclass


@dataclass(frozen=True)
class Permission:
    """One grantable capability. `code` is the stable wire/API identifier."""

    code: str
    name: str
    group: str


# Codes owned by this package. Order is presentation order in the admin UI
# pick-list (grouped by the `group` field).
_BASE_CATALOG: tuple[Permission, ...] = (
    # User administration
    Permission("user:read", "View users", "Users"),
    Permission("user:create", "Create users", "Users"),
    Permission("user:update", "Edit users and assign roles", "Users"),
    Permission("user:delete", "Delete users", "Users"),
    Permission("user:reset_password", "Reset another user's password", "Users"),
    Permission("user:force_logout", "Revoke another user's sessions", "Users"),
    # Role administration
    Permission("role:read", "View roles and permission bindings", "Roles"),
    Permission("role:manage", "Create/edit roles and bind permissions", "Roles"),
    # Compliance
    Permission("audit:read", "Read the audit log", "Audit"),
    # OAuth 2.1 provider administration (ADR-0005)
    Permission("oauth:read", "View registered clients and active grants", "OAuth"),
    Permission("oauth:revoke", "Revoke OAuth grants (user × client)", "OAuth"),
)

if len({p.code for p in _BASE_CATALOG}) != len(_BASE_CATALOG):  # pragma: no cover
    # A duplicated code in the literal above is an authoring mistake: fail at
    # import, where the traceback names this module, instead of at a random
    # role-binding request later.
    raise RuntimeError("duplicate permission code in _BASE_CATALOG")


# Entries contributed by composing packages (code -> Permission). Kept apart
# from the base tuple so the base stays a reviewable literal and a re-import of
# a composing package is naturally idempotent.
_registered: dict[str, Permission] = {}


def register_permission_codes(entries: Iterable[Permission]) -> None:
    """Add catalog entries owned by a composing package.

    Idempotent for identical entries — importing the owning package twice (or
    two modules of it) must not be an error. A code that already exists with
    *different* metadata (base entry or another package's registration) is a
    programming error and raises: two sources of truth for one code would make
    the admin UI and the route guards disagree.

    Rules for the registering package: call it at import time, before defining
    any `require_perm()` call site for these codes (validation is import-time),
    and keep the registration side-effect free otherwise.
    """
    known = {p.code: p for p in _BASE_CATALOG}
    known.update(_registered)
    for entry in entries:
        existing = known.get(entry.code)
        if existing is not None and existing != entry:
            raise ValueError(
                f"permission code {entry.code!r} is already registered as "
                f"{existing!r} — refusing to redefine it as {entry!r}"
            )
        _registered[entry.code] = entry
        known[entry.code] = entry


def permission_catalog() -> tuple[Permission, ...]:
    """The live catalog: base entries in literal order, then registered ones."""
    merged = {p.code: p for p in _BASE_CATALOG}
    merged.update(_registered)
    return (*_BASE_CATALOG, *(merged[code] for code in sorted(_registered)))


def permission_codes() -> frozenset[str]:
    """Every code that currently exists, base + registered."""
    return frozenset({*(p.code for p in _BASE_CATALOG), *_registered})


def catalog_as_dicts() -> list[dict]:
    """Serializable dump for `GET /api/v1/admin/permissions` (admin UI pickers)."""
    return [{"code": p.code, "name": p.name, "group": p.group} for p in permission_catalog()]
