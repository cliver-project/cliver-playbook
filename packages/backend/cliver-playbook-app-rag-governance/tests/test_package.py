"""Package-level assertions for the governance package.

The package's import has two side effects that must happen before any
router module is imported: the permission codes are registered in the
identity catalog, and the ``rag_governance`` settings section is
registered with the runtime settings registry. Both are exercised here
because a regression in import order would otherwise surface as a
cryptic ``require_perm`` failure in an unrelated API test.
"""

from __future__ import annotations


def test_permissions_are_registered_in_the_shared_catalog() -> None:
    from cliver_playbook.app.rag_governance import ROUTERS  # noqa: F401
    from cliver_playbook.app.user.auth.permissions import permission_codes

    assert "rag_governance:project:write" in permission_codes()
    assert "rag_governance:approve" in permission_codes()
    assert "rag_governance:staged:read" in permission_codes()


def test_settings_extend_rag_settings() -> None:
    from cliver_playbook.app.rag.settings import Settings as RagSettings
    from cliver_playbook.app.rag_governance.settings import Settings

    assert issubclass(Settings, RagSettings)
    assert Settings(_env_file=None).rag_governance.default_approval_mode == "manual"


def test_settings_section_is_registered() -> None:
    from cliver_playbook.app.basic.runtime_settings import settings_sections
    from cliver_playbook.app.rag_governance import settings_section  # noqa: F401

    keys = {section.key for section in settings_sections()}
    assert "rag_governance" in keys
