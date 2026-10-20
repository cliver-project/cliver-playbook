"""The permission registry: base catalog + package registration (ADR-0017).

The mechanism under test is the seam a composing package uses to contribute
its own codes: `register_permission_codes()` called at import time must be
visible to every *later* reader of the catalog (role-binding validation, the
admin dump, the migration seed). The composed, end-to-end use — the `mcp`
package's four codes, seeded into a fresh database — is asserted in that
package's suite, where the registration actually happens on import.

Registration has no unregister counterpart on purpose (codes are compile-time
facts), so these tests add entries that stay in the process-wide registry for
the rest of the session. They use a `test:` namespace that cannot collide with
a real package's codes, and every assertion is written relative to the live
catalog rather than to a fixed length.
"""

from __future__ import annotations

import pytest

from cliver_playbook.app.user.auth.permissions import (
    Permission,
    catalog_as_dicts,
    permission_catalog,
    permission_codes,
    register_permission_codes,
)

TEST_ENTRY = Permission("test:registry", "Registry probe", "Test")


def test_registered_codes_join_catalog_and_codes():
    before = len(permission_catalog())
    register_permission_codes([TEST_ENTRY])

    assert TEST_ENTRY in permission_catalog()
    assert len(permission_catalog()) == before + 1
    assert "test:registry" in permission_codes()

    # The admin UI dump is derived from the same merged view: a registered
    # code must be bindable through the pick-list, not just importable.
    assert {"code": "test:registry", "name": "Registry probe", "group": "Test"} in (
        catalog_as_dicts()
    )


def test_registration_is_idempotent_for_identical_entries():
    register_permission_codes([TEST_ENTRY])
    register_permission_codes([TEST_ENTRY])
    codes = [p.code for p in permission_catalog()]
    assert codes.count("test:registry") == 1


def test_conflicting_redefinition_raises():
    # Same code, different metadata: two sources of truth would make the
    # route guard and the admin pick-list disagree — refuse loudly.
    with pytest.raises(ValueError, match="already registered"):
        register_permission_codes([Permission("test:registry", "Other name", "Test")])

    # A base code is equally protected: a package may not silently re-describe
    # (or "re-group") a code this package owns.
    with pytest.raises(ValueError, match="already registered"):
        register_permission_codes([Permission("user:read", "Mine now", "MCP")])


def test_base_catalog_is_intact_after_registration():
    codes = permission_codes()
    for expected in ("user:read", "role:manage", "audit:read", "oauth:revoke"):
        assert expected in codes
    # Registration appends; it never rewrites a base entry's metadata.
    base = {p.code: p for p in permission_catalog() if p.code == "user:read"}
    assert base["user:read"].group == "Users"
