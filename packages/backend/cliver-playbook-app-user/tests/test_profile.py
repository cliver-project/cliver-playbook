"""Contact fields (phone) and the self-service profile endpoint.

Covers both write paths over the same columns:

- admin PATCH /admin/users/{id} — privileged, guarded, full field set
- self PATCH /auth/profile — narrow (display_name/email/phone only), no
  admin guards, reachable even behind the must-change-password gate

The absent-vs-empty distinction (_UNSET sentinel) is the subtle contract:
a field omitted from the body must stay untouched, while "" / null must
CLEAR it. Both directions are asserted here because conflating them is
silent data loss either way.
"""

from sqlalchemy import text

from .helpers import login


async def _make_user(client, admin_headers, username, **extra):
    payload = {
        "username": username,
        "password": "some-pass-123",
        "role_ids": [],
        "must_change_password": False,
        **extra,
    }
    resp = await client.post("/api/v1/admin/users", headers=admin_headers, json=payload)
    assert resp.status_code == 201, resp.text
    return resp.json()


# ---------------------------------------------------------------------------
# Admin side: phone roundtrip
# ---------------------------------------------------------------------------


async def test_admin_create_and_patch_phone(client, db, admin_headers):
    created = await _make_user(client, admin_headers, "alice", phone="+1-555-0100")
    assert created["phone"] == "+1-555-0100"

    patched = await client.patch(
        f"/api/v1/admin/users/{created['id']}",
        headers=admin_headers,
        json={"phone": "+1-555-0200"},
    )
    assert patched.status_code == 200, patched.text
    assert patched.json()["phone"] == "+1-555-0200"

    # Absent field = unchanged: patching something else leaves phone alone.
    other = await client.patch(
        f"/api/v1/admin/users/{created['id']}",
        headers=admin_headers,
        json={"display_name": "Alice Liddell"},
    )
    assert other.status_code == 200
    assert other.json()["phone"] == "+1-555-0200"
    assert other.json()["display_name"] == "Alice Liddell"

    # Empty string clears (schema validator maps "" -> None, service clears).
    cleared = await client.patch(
        f"/api/v1/admin/users/{created['id']}", headers=admin_headers, json={"phone": ""}
    )
    assert cleared.status_code == 200
    assert cleared.json()["phone"] is None


async def test_admin_duplicate_email_conflict_409(client, db, admin_headers):
    await _make_user(client, admin_headers, "owner", email="taken@example.com")
    second = await _make_user(client, admin_headers, "other")
    resp = await client.patch(
        f"/api/v1/admin/users/{second['id']}",
        headers=admin_headers,
        json={"email": "taken@example.com"},
    )
    assert resp.status_code == 409
    assert "already in use" in resp.json()["detail"]


# ---------------------------------------------------------------------------
# Self-service profile
# ---------------------------------------------------------------------------


async def test_profile_self_update_and_audit(client, db, admin_headers):
    await _make_user(client, admin_headers, "bob", email="bob@example.com")
    token = await login(client, "bob", "some-pass-123")
    headers = {"Authorization": f"Bearer {token}"}

    resp = await client.patch(
        "/api/v1/auth/profile",
        headers=headers,
        json={"display_name": "Bob Renamed", "email": "bob2@example.com", "phone": "+1-555-9999"},
    )
    assert resp.status_code == 200, resp.text
    user = resp.json()["user"]
    assert user["display_name"] == "Bob Renamed"
    assert user["email"] == "bob2@example.com"
    assert user["phone"] == "+1-555-9999"

    # /me reflects the change (same source of truth).
    me = await client.get("/api/v1/auth/me", headers=headers)
    assert me.json()["user"]["email"] == "bob2@example.com"

    # Audit row written, with the changed-field list (no values — PII stays
    # out of the trail; who/when/what-fields is enough for accountability).
    rows = (
        await db.execute(
            text(
                "SELECT detail FROM audit_logs "
                "WHERE event = 'auth.profile_update' AND username = 'bob'"
            )
        )
    ).all()
    assert len(rows) == 1
    assert sorted(rows[0].detail["fields"]) == ["display_name", "email", "phone"]


async def test_profile_unset_vs_clear(client, db, admin_headers):
    await _make_user(client, admin_headers, "carol", email="carol@example.com", phone="+1-555-0111")
    token = await login(client, "carol", "some-pass-123")
    headers = {"Authorization": f"Bearer {token}"}

    # Omitted fields stay; empty strings clear.
    resp = await client.patch("/api/v1/auth/profile", headers=headers, json={"phone": ""})
    assert resp.status_code == 200, resp.text
    assert resp.json()["user"]["phone"] is None
    assert resp.json()["user"]["email"] == "carol@example.com"  # untouched

    # Empty body is a legal no-op.
    noop = await client.patch("/api/v1/auth/profile", headers=headers, json={})
    assert noop.status_code == 200
    assert noop.json()["user"]["email"] == "carol@example.com"


async def test_profile_email_conflict_409(client, db, admin_headers):
    await _make_user(client, admin_headers, "dave", email="dave@example.com")
    await _make_user(client, admin_headers, "erin")
    token = await login(client, "erin", "some-pass-123")

    resp = await client.patch(
        "/api/v1/auth/profile",
        headers={"Authorization": f"Bearer {token}"},
        json={"email": "dave@example.com"},
    )
    assert resp.status_code == 409
    assert "already in use" in resp.json()["detail"]


async def test_profile_reachable_behind_must_change_gate(client, db, admin_headers):
    """The gate whitelists /auth/profile: fixing your own contact details is
    not a privilege, and blocking it would strand users who need both."""
    resp = await client.post(
        "/api/v1/admin/users",
        headers=admin_headers,
        json={
            "username": "frank",
            "password": "fresh-pass-123",
            "role_ids": [],
            "must_change_password": True,
        },
    )
    assert resp.status_code == 201
    login_resp = await client.post(
        "/api/v1/auth/login", json={"username": "frank", "password": "fresh-pass-123"}
    )
    gated = {"Authorization": f"Bearer {login_resp.json()['token']}"}

    profile = await client.patch(
        "/api/v1/auth/profile", headers=gated, json={"phone": "+1-555-7777"}
    )
    assert profile.status_code == 200, profile.text
    assert profile.json()["user"]["phone"] == "+1-555-7777"

    # Sanity: the gate itself still fires on non-whitelisted paths.
    blocked = await client.get("/api/v1/admin/users", headers=gated)
    assert blocked.status_code == 403
    assert blocked.json()["detail"] == {"code": "must_change_password"}
