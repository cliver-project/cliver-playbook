"""Password authentication: login, lockout, must-change gate, change-password,
token revocation semantics.

These tests assert security behavior, not implementation: lockout is enforced
server-side, changing a password kills every other session, and the
must-change-password gate is server-enforced (403) with an explicit allow-list.
"""

from sqlalchemy import text

from .helpers import TEST_ADMIN_PASSWORD, seed_admin


async def test_login_success_and_me(client, db):
    await seed_admin(db)
    resp = await client.post(
        "/api/v1/auth/login",
        json={"username": "admin", "password": TEST_ADMIN_PASSWORD},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["token"]
    assert body["must_change_password"] is False
    assert body["user"]["username"] == "admin"
    assert body["user"]["role_codes"] == ["admin"]

    me = await client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {body['token']}"})
    assert me.status_code == 200
    assert me.json()["user"]["username"] == "admin"


async def test_login_wrong_password_401_and_audited(client, db):

    await seed_admin(db)
    resp = await client.post(
        "/api/v1/auth/login", json={"username": "admin", "password": "wrong-pass"}
    )
    assert resp.status_code == 401
    # The failure audit row must survive the 401 (committed before the raise).
    rows = (
        await db.execute(text("SELECT event, ok, error FROM audit_logs WHERE event = 'auth.login'"))
    ).all()
    assert len(rows) == 1
    assert rows[0].ok is False
    assert rows[0].error == "invalid"


async def test_lockout_after_threshold(client, db):
    await seed_admin(db)
    for _ in range(5):
        resp = await client.post(
            "/api/v1/auth/login", json={"username": "admin", "password": "nope-nope"}
        )
    # 5th failure within the window locks the account: even the CORRECT
    # password is now refused with 429.
    resp = await client.post(
        "/api/v1/auth/login",
        json={"username": "admin", "password": TEST_ADMIN_PASSWORD},
    )
    assert resp.status_code == 429


async def test_must_change_password_gate(client, db, admin_headers):
    create = await client.post(
        "/api/v1/admin/users",
        headers=admin_headers,
        json={
            "username": "fresh",
            "password": "fresh-pass-123",
            "display_name": "Fresh",
            "role_ids": [],
        },
    )
    assert create.status_code == 201, create.text
    assert create.json()["must_change_password"] is True

    login = await client.post(
        "/api/v1/auth/login", json={"username": "fresh", "password": "fresh-pass-123"}
    )
    assert login.status_code == 200
    gated = {"Authorization": f"Bearer {login.json()['token']}"}

    # Blocked on any authenticated path outside the allow-list. Admin endpoints
    # are authenticated (the items demo router is intentionally open — basic's
    # demo shape), and the gate fires inside get_current_user BEFORE the
    # permission check, so the 403 carries the gate's dict detail.
    blocked = await client.get("/api/v1/admin/users", headers=gated)
    assert blocked.status_code == 403
    assert blocked.json()["detail"] == {"code": "must_change_password"}

    # ...but /me and change-password work.
    assert (await client.get("/api/v1/auth/me", headers=gated)).status_code == 200

    changed = await client.post(
        "/api/v1/auth/change-password",
        headers=gated,
        json={"old_password": "fresh-pass-123", "new_password": "better-pass-456"},
    )
    assert changed.status_code == 200, changed.text
    assert changed.json()["must_change_password"] is False

    # Old token revoked by the change; the returned token works and clears the
    # gate — an admin endpoint now fails on PERMISSIONS (string detail), not on
    # the gate (dict detail with code).
    assert (await client.post("/api/v1/auth/logout", headers=gated)).status_code == 401
    fresh = {"Authorization": f"Bearer {changed.json()['token']}"}
    assert (await client.get("/api/v1/auth/me", headers=fresh)).status_code == 200
    admin_call = await client.get("/api/v1/admin/users", headers=fresh)
    assert admin_call.status_code == 403
    assert admin_call.json()["detail"] == "Missing permission: user:read"


async def test_change_password_wrong_old_password(client, db):
    await seed_admin(db)
    login = await client.post(
        "/api/v1/auth/login",
        json={"username": "admin", "password": TEST_ADMIN_PASSWORD},
    )
    resp = await client.post(
        "/api/v1/auth/change-password",
        headers={"Authorization": f"Bearer {login.json()['token']}"},
        json={"old_password": "not-the-password", "new_password": "whatever-123"},
    )
    assert resp.status_code == 400


async def test_change_password_revokes_other_sessions(client, db):
    await seed_admin(db)
    first = await client.post(
        "/api/v1/auth/login",
        json={"username": "admin", "password": TEST_ADMIN_PASSWORD},
    )
    second = await client.post(
        "/api/v1/auth/login",
        json={"username": "admin", "password": TEST_ADMIN_PASSWORD},
    )
    token_a, token_b = first.json()["token"], second.json()["token"]

    changed = await client.post(
        "/api/v1/auth/change-password",
        headers={"Authorization": f"Bearer {token_a}"},
        json={"old_password": TEST_ADMIN_PASSWORD, "new_password": "rotated-pass-9"},
    )
    assert changed.status_code == 200
    # Session B died with the password change; session A continues via the
    # newly issued token.
    me_b = await client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token_b}"})
    assert me_b.status_code == 401
    me_a = await client.get(
        "/api/v1/auth/me",
        headers={"Authorization": f"Bearer {changed.json()['token']}"},
    )
    assert me_a.status_code == 200


async def test_expired_token_rejected(client, db, admin_headers):
    resp = await client.get("/api/v1/auth/me", headers=admin_headers)
    assert resp.status_code == 200
    # Age the token row past its expiry: the very next request must 401.
    await db.execute(text("UPDATE auth_tokens SET expires_at = now() - interval '1 hour'"))
    await db.commit()
    resp = await client.get("/api/v1/auth/me", headers=admin_headers)
    assert resp.status_code == 401


async def test_logout_revokes_presented_token(client, db, admin_headers):
    resp = await client.post("/api/v1/auth/logout", headers=admin_headers)
    assert resp.status_code == 204
    assert (await client.get("/api/v1/auth/me", headers=admin_headers)).status_code == 401


async def test_inactive_user_tokens_die_immediately(client, db, admin_headers):
    create = await client.post(
        "/api/v1/admin/users",
        headers=admin_headers,
        json={
            "username": "victim",
            "password": "victim-pass-12",
            "role_ids": [],
            "must_change_password": False,
        },
    )
    user_id = create.json()["id"]
    login = await client.post(
        "/api/v1/auth/login", json={"username": "victim", "password": "victim-pass-12"}
    )
    headers = {"Authorization": f"Bearer {login.json()['token']}"}
    assert (await client.get("/api/v1/auth/me", headers=headers)).status_code == 200

    deactivate = await client.patch(
        f"/api/v1/admin/users/{user_id}", headers=admin_headers, json={"is_active": False}
    )
    assert deactivate.status_code == 200
    # Deactivation is effective on the next request, not at token expiry.
    assert (await client.get("/api/v1/auth/me", headers=headers)).status_code == 401
    # And re-login is refused outright.
    again = await client.post(
        "/api/v1/auth/login", json={"username": "victim", "password": "victim-pass-12"}
    )
    assert again.status_code == 401
