"""Permissions registration test: importing the rag package registers
four rag:* codes into the identity package's permission catalog."""

from __future__ import annotations

from cliver_playbook.app.user.auth.permissions import permission_codes


def test_rag_permissions_registered() -> None:
    codes = set(permission_codes())
    for expected in (
        "rag:documents:read",
        "rag:documents:write",
        "rag:search:read",
        "rag:chat:read",
    ):
        assert expected in codes, f"missing permission code: {expected}"


def test_rag_permissions_have_group_rag() -> None:
    from cliver_playbook.app.user.auth.permissions import permission_catalog

    rag_codes = [p for p in permission_catalog() if p.group == "rag"]
    # Four codes is the ADR-0018 contract: there is no separate admin
    # read because v1 has no per-user document ownership to gate.
    assert len(rag_codes) == 4
    assert {p.code for p in rag_codes} == {
        "rag:documents:read",
        "rag:documents:write",
        "rag:search:read",
        "rag:chat:read",
    }
