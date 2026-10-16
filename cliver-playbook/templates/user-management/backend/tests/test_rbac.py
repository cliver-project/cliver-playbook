"""RBAC: permission catalog, role CRUD, permission-binding validation,
permission effectiveness on the next request, self-protections, last-admin
guard, and token-kind isolation (the ADR-0004 predicate discipline).
"""

from app.auth.tokens import rotate_static_token, verify_bearer
from tests.helpers import login

ADMIN_PASSWORD = "admin-test-passw0rd"


# ---------------------------------------------------------------------------
# Catalog + role CRUD
# ---------------------------------------------------------------------------


async def test_permission_catalog_dump(client, admin_headers):
    resp = await client.get("/api/v1/admin/permissions", headers=admin_headers)
    assert resp.status_code == 200
    codes = {item["code"] for item in resp.json()}
    assert "user:read" in codes and "role:manage" in codes and "audit:read" in codes
    assert all(item["name"] and item["group"] for item in resp.json())


async def test_role_crud_and_unknown_permission_rejected(client, admin_headers):
    create = await client.post(
        "/api/v1/admin/roles",
        headers=admin_headers,
        json={
            "code": "viewer",
            "name": "Viewer",
            "description": "Read-only users",
            "permission_codes": ["user:read", "role:read"],
        },
    )
    assert create.status_code == 201, create.text
    role_id = create.json()["id"]
    assert create.json()["permission_codes"] == ["role:read", "user:read"]

    # Codes outside the catalog are rejected with a helpful message.
    bad = await client.post(
        "/api/v1/admin/roles",
        headers=admin_headers,
        json={"code": "broken", "name": "Broken", "permission_codes": ["user:reed"]},
    )
    assert bad.status_code == 400
    assert "user:reed" in bad.json()["detail"]

    # Full-state PUT on permissions replaces the set.
    patch = await client.patch(
        f"/api/v1/admin/roles/{role_id}",
        headers=admin_headers,
        json={"permission_codes": ["audit:read"]},
    )
    assert patch.status_code == 200
    assert patch.json()["permission_codes"] == ["audit:read"]

    # System roles cannot be deleted; custom ones can.
    admin_role_id = next(
        r["id"]
        for r in (await client.get("/api/v1/admin/roles", headers=admin_headers)).json()
        if r["code"] == "admin"
    )
    assert (
        await client.delete(f"/api/v1/admin/roles/{admin_role_id}", headers=admin_headers)
    ).status_code == 400
    assert (
        await client.delete(f"/api/v1/admin/roles/{role_id}", headers=admin_headers)
    ).status_code == 204


# ---------------------------------------------------------------------------
# Effectiveness + 403 matrix
# ---------------------------------------------------------------------------


async def _create_user_with_roles(client, admin_headers, username, role_codes):
    roles = (await client.get("/api/v1/admin/roles", headers=admin_headers)).json()
    role_ids = [r["id"] for r in roles if r["code"] in role_codes]
    resp = await client.post(
        "/api/v1/admin/users",
        headers=admin_headers,
        json={
            "username": username,
            "password": "some-pass-123",
            "role_ids": role_ids,
            "must_change_password": False,
        },
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


async def test_permission_effective_on_next_request(client, db, admin_headers):
    await client.post(
        "/api/v1/admin/roles",
        headers=admin_headers,
        json={"code": "viewer", "name": "Viewer", "permission_codes": ["user:read"]},
    )
    await _create_user_with_roles(client, admin_headers, "bob", ["viewer"])
    token = await login(client, "bob", "some-pass-123")
    bob = {"Authorization": f"Bearer {token}"}

    # Granted: list users.
    assert (await client.get("/api/v1/admin/users", headers=bob)).status_code == 200
    # Not granted: create users / touch roles / read audit.
    assert (await client.post("/api/v1/admin/users", headers=bob, json={})).status_code == 403
    assert (await client.get("/api/v1/admin/roles", headers=bob)).status_code == 403
    assert (await client.get("/api/v1/admin/audit", headers=bob)).status_code == 403

    # Grant role:read mid-session: the very next request passes — permissions
    # resolve per request, never cached inside the token.
    roles = (await client.get("/api/v1/admin/roles", headers=admin_headers)).json()
    viewer = next(r for r in roles if r["code"] == "viewer")
    await client.patch(
        f"/api/v1/admin/roles/{viewer['id']}",
        headers=admin_headers,
        json={"permission_codes": ["user:read", "role:read"]},
    )
    assert (await client.get("/api/v1/admin/roles", headers=bob)).status_code == 200


async def test_permissionless_user_gets_403_everywhere(client, db, admin_headers):
    await _create_user_with_roles(client, admin_headers, "nobody", [])
    token = await login(client, "nobody", "some-pass-123")
    headers = {"Authorization": f"Bearer {token}"}
    for method, path in (
        ("get", "/api/v1/admin/users"),
        ("post", "/api/v1/admin/users"),
        ("get", "/api/v1/admin/roles"),
        ("get", "/api/v1/admin/audit"),
        ("get", "/api/v1/admin/permissions"),
    ):
        resp = await getattr(client, method)(path, headers=headers)
        assert resp.status_code == 403, (method, path, resp.status_code)


# ---------------------------------------------------------------------------
# Self-protections + last admin
# ---------------------------------------------------------------------------


async def _admin_user_id(client, admin_headers) -> int:
    users = (await client.get("/api/v1/admin/users", headers=admin_headers)).json()
    return next(u["id"] for u in users if u["username"] == "admin")


async def test_cannot_delete_deactivate_or_demote_self(client, db, admin_headers):
    me = await _admin_user_id(client, admin_headers)
    assert (
        await client.delete(f"/api/v1/admin/users/{me}", headers=admin_headers)
    ).status_code == 400
    assert (
        await client.patch(
            f"/api/v1/admin/users/{me}", headers=admin_headers, json={"is_active": False}
        )
    ).status_code == 400
    roles = (await client.get("/api/v1/admin/roles", headers=admin_headers)).json()
    user_role_id = next(r["id"] for r in roles if r["code"] == "user")
    assert (
        await client.patch(
            f"/api/v1/admin/users/{me}", headers=admin_headers, json={"role_ids": [user_role_id]}
        )
    ).status_code == 400


async def test_last_admin_protection_and_second_admin_escape(client, db, admin_headers):
    await _create_user_with_roles(client, admin_headers, "admin2", ["user"])
    users = (await client.get("/api/v1/admin/users", headers=admin_headers)).json()
    admin_id = next(u["id"] for u in users if u["username"] == "admin")
    admin2 = next(u for u in users if u["username"] == "admin2")
    roles = (await client.get("/api/v1/admin/roles", headers=admin_headers)).json()
    admin_role_id = next(r["id"] for r in roles if r["code"] == "admin")
    user_role_id = next(r["id"] for r in roles if r["code"] == "user")

    # admin2 is not an admin yet: demoting/deleting admin is refused.
    assert (
        await client.patch(
            f"/api/v1/admin/users/{admin_id}",
            headers=admin_headers,
            json={"role_ids": [user_role_id]},
        )
    ).status_code == 400
    assert (
        await client.delete(f"/api/v1/admin/users/{admin_id}", headers=admin_headers)
    ).status_code == 400

    # Promote admin2 -> an active admin remains, so ANOTHER admin may demote
    # admin. (admin still cannot demote themselves — self-mutation guard.)
    promote = await client.patch(
        f"/api/v1/admin/users/{admin2['id']}",
        headers=admin_headers,
        json={"role_ids": [admin_role_id]},
    )
    assert promote.status_code == 200
    self_demote = await client.patch(
        f"/api/v1/admin/users/{admin_id}",
        headers=admin_headers,
        json={"role_ids": [user_role_id]},
    )
    assert self_demote.status_code == 400

    admin2_token = await login(client, "admin2", "some-pass-123")
    demote = await client.patch(
        f"/api/v1/admin/users/{admin_id}",
        headers={"Authorization": f"Bearer {admin2_token}"},
        json={"role_ids": [user_role_id]},
    )
    assert demote.status_code == 200


# ---------------------------------------------------------------------------
# Token-kind isolation (ADR-0004 predicate discipline)
# ---------------------------------------------------------------------------


async def test_token_kind_isolation(client, db, admin_headers):
    """Static-token rotation must never touch web or OAuth access tokens, and
    vice versa — the discriminators are the only thing standing between the
    three kinds sharing one table."""
    from datetime import timedelta

    from app.auth.tokens import issue_oauth_access_token
    from app.core.timeutil import utcnow

    users = (await client.get("/api/v1/admin/users", headers=admin_headers)).json()
    admin_id = next(u["id"] for u in users if u["username"] == "admin")

    # OAuth access token for a fake client.
    oauth_token, _ = await issue_oauth_access_token(
        db,
        user_id=admin_id,
        client_id="test-client",
        expires_at=utcnow() + timedelta(hours=1),
    )
    await db.commit()

    # Static token, twice: second rotation must revoke only the first static.
    static1, _ = await rotate_static_token(db, user_id=admin_id, label="cli")
    static2, _ = await rotate_static_token(db, user_id=admin_id, label="cli")
    await db.commit()

    assert (await verify_bearer(db, static1)) is None  # rotated out
    assert (await verify_bearer(db, static2)) is not None
    # Web token untouched by static rotation.
    assert (await verify_bearer(db, admin_headers["Authorization"][7:])) is not None
    # OAuth access token untouched by static rotation.
    assert (await verify_bearer(db, oauth_token)) is not None
    # verify_bearer's last_used_at UPDATE leaves this session holding row
    # locks; commit before _revoke_family's separate session touches the same
    # rows, or it would block on us forever.
    await db.commit()

    # OAuth family revocation must not touch static/web tokens.
    from app.auth.oauth21 import _revoke_family

    await _revoke_family(admin_id, "test-client")
    await db.commit()
    assert (await verify_bearer(db, static2)) is not None
    assert (await verify_bearer(db, admin_headers["Authorization"][7:])) is not None
    assert (await verify_bearer(db, oauth_token)) is None  # its own family died


async def test_static_token_authenticates_api(client, db, admin_headers):
    """Static tokens are first-class bearers for programmatic API access."""
    users = (await client.get("/api/v1/admin/users", headers=admin_headers)).json()
    admin_id = next(u["id"] for u in users if u["username"] == "admin")
    static, _ = await rotate_static_token(db, user_id=admin_id, label="ci-script")
    await db.commit()
    resp = await client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {static}"})
    assert resp.status_code == 200
    assert resp.json()["user"]["username"] == "admin"


# ---------------------------------------------------------------------------
# Audit listing
# ---------------------------------------------------------------------------


async def test_audit_listing_and_filter(client, db, admin_headers):
    resp = await client.get("/api/v1/admin/audit", headers=admin_headers)
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] >= 1
    assert any(row["event"] == "auth.login" for row in body["items"])

    filtered = await client.get(
        "/api/v1/admin/audit", headers=admin_headers, params={"event": "auth.login"}
    )
    assert filtered.status_code == 200
    assert all(row["event"] == "auth.login" for row in filtered.json()["items"])
    limited = await client.get("/api/v1/admin/audit", headers=admin_headers, params={"limit": 1})
    assert len(limited.json()["items"]) == 1
