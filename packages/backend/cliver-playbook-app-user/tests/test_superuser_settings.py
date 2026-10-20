"""Superuser wildcard and module-owned runtime settings (ADR-0021).

Two behaviors are pinned here:

- The seeded admin role holds exactly ``*`` and passes every permission
  check; only another ``*`` holder may grant, narrow, or delete a wildcard
  role. The invariant is cheap because a set containing ``*`` normalizes to
  ``["*"]``.
- The admin settings API delegates to the section registered by this
  package. Updates apply to the live Settings instance immediately, persist
  in ``app_settings``, reject secrets and environment-managed fields, and a
  reset restores the startup baseline.
"""

from __future__ import annotations

from cliver_playbook.app.basic import runtime
from cliver_playbook.app.basic.models.entities import AppSetting
from cliver_playbook.app.user.auth.dependencies import Viewer
from cliver_playbook.app.user.auth.permissions import ALL_PERMISSIONS

from .helpers import login

ADMIN_PASSWORD = "admin-test-passw0rd"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _roles(client, headers) -> list[dict]:
    resp = await client.get("/api/v1/admin/roles", headers=headers)
    assert resp.status_code == 200, resp.text
    return resp.json()


async def _role_id(client, headers, code: str) -> int:
    return next(role["id"] for role in await _roles(client, headers) if role["code"] == code)


async def _create_role(client, headers, code: str, permission_codes: list[str]) -> dict:
    resp = await client.post(
        "/api/v1/admin/roles",
        headers=headers,
        json={"code": code, "name": code.title(), "permission_codes": permission_codes},
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


async def _create_user(client, headers, username: str, role_codes: list[str]) -> dict:
    roles = await _roles(client, headers)
    role_ids = [role["id"] for role in roles if role["code"] in role_codes]
    resp = await client.post(
        "/api/v1/admin/users",
        headers=headers,
        json={
            "username": username,
            "password": "some-pass-123",
            "role_ids": role_ids,
            "must_change_password": False,
        },
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


async def _headers_for(client, username: str) -> dict[str, str]:
    token = await login(client, username, "some-pass-123")
    return {"Authorization": f"Bearer {token}"}


# ---------------------------------------------------------------------------
# The wildcard
# ---------------------------------------------------------------------------


def test_viewer_has_honours_the_wildcard():
    viewer = Viewer(
        user_id=1,
        username="root",
        display_name="Root",
        must_change_password=False,
        permissions=frozenset({ALL_PERMISSIONS}),
    )
    assert viewer.has("anything:at:all")
    assert viewer.has("settings:manage")

    narrow = Viewer(
        user_id=2,
        username="limited",
        display_name="Limited",
        must_change_password=False,
        permissions=frozenset({"user:read"}),
    )
    assert narrow.has("user:read")
    assert not narrow.has("user:create")


async def test_seeded_admin_role_holds_only_the_wildcard(client, admin_headers):
    roles = await _roles(client, admin_headers)
    admin = next(role for role in roles if role["code"] == "admin")
    assert admin["permission_codes"] == [ALL_PERMISSIONS]


async def test_wildcard_grants_every_route(client, admin_headers):
    await _create_role(client, admin_headers, "root", [ALL_PERMISSIONS])
    await _create_user(client, admin_headers, "rooter", ["root"])
    headers = await _headers_for(client, "rooter")

    for path in (
        "/api/v1/admin/users",
        "/api/v1/admin/roles",
        "/api/v1/admin/settings",
        "/api/v1/admin/audit",
        "/api/v1/admin/permissions",
    ):
        resp = await client.get(path, headers=headers)
        assert resp.status_code == 200, (path, resp.status_code, resp.text)


async def test_wildcard_normalizes_the_role_set(client, admin_headers):
    role = await _create_role(client, admin_headers, "everything", [ALL_PERMISSIONS, "user:read"])
    assert role["permission_codes"] == [ALL_PERMISSIONS]
    assert next(r for r in await _roles(client, admin_headers) if r["code"] == "everything")[
        "permission_codes"
    ] == [ALL_PERMISSIONS]


async def test_admin_role_cannot_be_narrowed(client, admin_headers):
    admin_role_id = await _role_id(client, admin_headers, "admin")
    resp = await client.patch(
        f"/api/v1/admin/roles/{admin_role_id}",
        headers=admin_headers,
        json={"permission_codes": ["user:read"]},
    )
    assert resp.status_code == 400
    assert "all permissions" in resp.json()["detail"].lower()

    # Re-submitting the invariant is fine.
    assert (
        await client.patch(
            f"/api/v1/admin/roles/{admin_role_id}",
            headers=admin_headers,
            json={"permission_codes": [ALL_PERMISSIONS]},
        )
    ).status_code == 200


async def test_non_superuser_cannot_grant_or_touch_the_wildcard(client, admin_headers):
    await _create_role(client, admin_headers, "role-manager", ["role:manage", "role:read"])
    await _create_user(client, admin_headers, "manager", ["role-manager"])
    headers = await _headers_for(client, "manager")

    # Granting * is reserved for a * holder.
    create = await client.post(
        "/api/v1/admin/roles",
        headers=headers,
        json={"code": "sneaky", "name": "Sneaky", "permission_codes": [ALL_PERMISSIONS]},
    )
    assert create.status_code == 403

    # Nor may they add * to a role they can otherwise edit.
    own_role_id = await _role_id(client, admin_headers, "role-manager")
    bind = await client.patch(
        f"/api/v1/admin/roles/{own_role_id}",
        headers=headers,
        json={"permission_codes": ["role:manage", ALL_PERMISSIONS]},
    )
    assert bind.status_code == 403

    # A wildcard role — including the admin role — is off limits.
    await _create_role(client, admin_headers, "shadow-root", [ALL_PERMISSIONS])
    shadow_id = await _role_id(client, admin_headers, "shadow-root")
    assert (
        await client.patch(
            f"/api/v1/admin/roles/{shadow_id}",
            headers=headers,
            json={"name": "Renamed"},
        )
    ).status_code == 403
    assert (
        await client.delete(f"/api/v1/admin/roles/{shadow_id}", headers=headers)
    ).status_code == 403
    admin_role_id = await _role_id(client, admin_headers, "admin")
    assert (
        await client.patch(
            f"/api/v1/admin/roles/{admin_role_id}",
            headers=headers,
            json={"name": "Owned"},
        )
    ).status_code == 403


# ---------------------------------------------------------------------------
# Runtime settings: identity section
# ---------------------------------------------------------------------------


def _field(section: dict, name: str) -> dict:
    return next(field for field in section["fields"] if field["name"] == name)


async def test_list_and_read_settings(client, admin_headers):
    resp = await client.get("/api/v1/admin/settings", headers=admin_headers)
    assert resp.status_code == 200, resp.text
    sections = {section["key"]: section for section in resp.json()}
    assert "user" in sections
    field = _field(sections["user"], "login_lockout_threshold")
    assert field["value"] == 5
    assert field["source"] == "config"
    assert field["read_only"] is False

    single = await client.get("/api/v1/admin/settings/user", headers=admin_headers)
    assert single.status_code == 200
    assert single.json()["key"] == "user"


async def test_update_applies_live_and_persists(client, db, admin_headers):
    resp = await client.put(
        "/api/v1/admin/settings/user",
        headers=admin_headers,
        json={"values": {"login_lockout_threshold": 7}},
    )
    assert resp.status_code == 200, resp.text
    field = _field(resp.json(), "login_lockout_threshold")
    assert field["value"] == 7
    assert field["source"] == "runtime"

    # Live: the bound Settings instance is the one every request reads.
    assert runtime.configured_settings().login_lockout_threshold == 7

    row = await db.get(AppSetting, "user")
    await db.refresh(row)
    assert row is not None
    assert row.values == {"login_lockout_threshold": 7}

    # A second partial update merges rather than replacing the stored row.
    second = await client.put(
        "/api/v1/admin/settings/user",
        headers=admin_headers,
        json={"values": {"token_ttl_days": 14}},
    )
    assert second.status_code == 200
    assert _field(second.json(), "login_lockout_threshold")["value"] == 7
    assert _field(second.json(), "token_ttl_days")["value"] == 14
    await db.refresh(row)
    assert row.values == {"login_lockout_threshold": 7, "token_ttl_days": 14}


async def test_reset_restores_the_startup_baseline(client, db, admin_headers):
    await client.put(
        "/api/v1/admin/settings/user",
        headers=admin_headers,
        json={"values": {"login_lockout_threshold": 9}},
    )
    assert runtime.configured_settings().login_lockout_threshold == 9

    resp = await client.delete("/api/v1/admin/settings/user", headers=admin_headers)
    assert resp.status_code == 200, resp.text
    field = _field(resp.json(), "login_lockout_threshold")
    assert field["value"] == 5
    assert field["source"] == "config"
    assert runtime.configured_settings().login_lockout_threshold == 5
    assert await db.get(AppSetting, "user") is None


async def test_invalid_and_unknown_settings_are_rejected(client, admin_headers):
    invalid = await client.put(
        "/api/v1/admin/settings/user",
        headers=admin_headers,
        json={"values": {"login_lockout_threshold": 0}},
    )
    assert invalid.status_code == 400
    assert runtime.configured_settings().login_lockout_threshold == 5

    unknown_field = await client.put(
        "/api/v1/admin/settings/user",
        headers=admin_headers,
        json={"values": {"not_a_field": 1}},
    )
    assert unknown_field.status_code == 400

    assert (
        await client.get("/api/v1/admin/settings/nope", headers=admin_headers)
    ).status_code == 404
    assert (
        await client.put(
            "/api/v1/admin/settings/nope",
            headers=admin_headers,
            json={"values": {}},
        )
    ).status_code == 404


async def test_environment_managed_field_is_read_only(client, admin_headers, monkeypatch):
    monkeypatch.setenv("CLIVER_TOKEN_TTL_DAYS", "12")
    section = (await client.get("/api/v1/admin/settings/user", headers=admin_headers)).json()
    field = _field(section, "token_ttl_days")
    assert field["read_only"] is True
    assert field["source"] == "environment"

    resp = await client.put(
        "/api/v1/admin/settings/user",
        headers=admin_headers,
        json={"values": {"token_ttl_days": 99}},
    )
    assert resp.status_code == 400
    assert "CLIVER_TOKEN_TTL_DAYS" in resp.json()["detail"]
    assert runtime.configured_settings().token_ttl_days == 30


async def test_settings_rbac(client, admin_headers):
    await _create_role(client, admin_headers, "settings-reader", ["settings:read"])
    await _create_user(client, admin_headers, "auditor", ["settings-reader"])
    headers = await _headers_for(client, "auditor")

    assert (await client.get("/api/v1/admin/settings", headers=headers)).status_code == 200
    assert (
        await client.put(
            "/api/v1/admin/settings/user",
            headers=headers,
            json={"values": {"login_lockout_threshold": 7}},
        )
    ).status_code == 403
    assert (await client.delete("/api/v1/admin/settings/user", headers=headers)).status_code == 403


async def test_settings_changes_are_audited(client, admin_headers):
    await client.put(
        "/api/v1/admin/settings/user",
        headers=admin_headers,
        json={"values": {"login_lockout_threshold": 7}},
    )
    await client.delete("/api/v1/admin/settings/user", headers=admin_headers)

    updates = await client.get(
        "/api/v1/admin/audit",
        headers=admin_headers,
        params={"event": "admin.settings.update"},
    )
    assert updates.status_code == 200
    assert updates.json()["total"] == 1
    assert updates.json()["items"][0]["target"] == "settings:user"

    resets = await client.get(
        "/api/v1/admin/audit",
        headers=admin_headers,
        params={"event": "admin.settings.reset"},
    )
    assert resets.json()["total"] == 1
