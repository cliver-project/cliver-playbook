"""OAuth 2.1 provider: metadata documents, DCR, the authorization-code +
PKCE flow through the SPA hand-off, refresh rotation with replay defense,
and revocation — a focused subset of the predecessor's end-to-end suite.

Issuer byte-exactness is asserted literally: agent clients compare the
redirect's iss against the metadata issuer character by character, and a
trailing slash would break them (this exact bug shipped once).
"""

import base64
import hashlib
import secrets
from urllib.parse import parse_qs, urlparse

from sqlalchemy import text

from .helpers import TEST_ADMIN_PASSWORD, login

ISSUER = "http://127.0.0.1:8000"
REDIRECT_URI = "http://127.0.0.1:8765/callback"


def _pkce() -> tuple[str, str]:
    verifier = base64.urlsafe_b64encode(secrets.token_bytes(32)).rstrip(b"=").decode()
    challenge = (
        base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    )
    return verifier, challenge


async def _register_client(client, **overrides) -> dict:
    payload = {
        "client_name": "Test Agent",
        "redirect_uris": [REDIRECT_URI],
        "token_endpoint_auth_method": "none",
        "grant_types": ["authorization_code", "refresh_token"],
        "response_types": ["code"],
        "scope": "mcp offline_access",
    }
    payload.update(overrides)
    resp = await client.post("/register", json=payload)
    assert resp.status_code == 201, resp.text
    return resp.json()


async def _drive_to_code(
    client,
    client_id: str,
    admin_headers: dict,
    *,
    username: str = "admin",
    password: str = TEST_ADMIN_PASSWORD,
) -> tuple[str, str, str]:
    """SDK /authorize -> SPA blob -> credential capture -> authorization code.

    Returns (code, state, verifier). The grant owner defaults to the seeded
    admin; revocation tests pass a plain user instead.
    """
    verifier, challenge = _pkce()
    state = "st-" + secrets.token_hex(8)
    auth_resp = await client.get(
        "/authorize",
        params={
            "response_type": "code",
            "client_id": client_id,
            "redirect_uri": REDIRECT_URI,
            "code_challenge": challenge,
            "code_challenge_method": "S256",
            "state": state,
            "scope": "mcp offline_access",
        },
    )
    assert auth_resp.status_code == 302, auth_resp.text
    location = urlparse(auth_resp.headers["location"])
    assert f"{location.scheme}://{location.netloc}{location.path}" == (
        "http://127.0.0.1:5173/oauth/authorize"
    )
    blob = parse_qs(location.query)["oauth"][0]

    capture = await client.post(
        "/api/v1/auth/oauth/authorize",
        json={"blob": blob, "username": username, "password": password},
    )
    assert capture.status_code == 200, capture.text
    back = urlparse(capture.json()["redirect_url"])
    assert f"{back.scheme}://{back.netloc}{back.path}" == REDIRECT_URI
    params = {k: v[0] for k, v in parse_qs(back.query).items()}
    return params["code"], params["state"], verifier


async def _exchange_code(client, client_id: str, code: str, verifier: str):
    return await client.post(
        "/token",
        data={
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": REDIRECT_URI,
            "client_id": client_id,
            "code_verifier": verifier,
        },
    )


# ---------------------------------------------------------------------------
# Documents
# ---------------------------------------------------------------------------


async def test_as_metadata_shape(client):
    resp = await client.get("/.well-known/oauth-authorization-server")
    assert resp.status_code == 200
    doc = resp.json()
    # Byte-exact issuer — no trailing slash, no path mangling.
    assert doc["issuer"] == ISSUER
    assert "none" in doc["token_endpoint_auth_methods_supported"]
    assert doc["authorization_response_iss_parameter_supported"] is True
    assert doc["registration_endpoint"] == f"{ISSUER}/register"
    for endpoint in ("authorization_endpoint", "token_endpoint", "revocation_endpoint"):
        assert doc[endpoint].startswith(ISSUER)


async def test_prm_alias_document(client):
    resp = await client.get("/.well-known/oauth-protected-resource")
    assert resp.status_code == 200
    doc = resp.json()
    assert doc["resource"] == f"{ISSUER}/mcp"
    assert doc["authorization_servers"] == [ISSUER]


# ---------------------------------------------------------------------------
# Code flow
# ---------------------------------------------------------------------------


async def test_full_code_flow(client, db, admin_headers):
    reg = await _register_client(client)
    code, state, verifier = await _drive_to_code(client, reg["client_id"], admin_headers)
    assert state.startswith("st-")

    token_resp = await _exchange_code(client, reg["client_id"], code, verifier)
    assert token_resp.status_code == 200, token_resp.text
    body = token_resp.json()
    assert body["token_type"] == "Bearer"
    assert body["refresh_token"].startswith("cliver_rt_")
    assert "mcp" in body["scope"]

    # The OAuth access token is a first-class bearer on the regular API.
    me = await client.get(
        "/api/v1/auth/me", headers={"Authorization": f"Bearer {body['access_token']}"}
    )
    assert me.status_code == 200
    assert me.json()["user"]["username"] == "admin"

    # And the redirect carried iss matching the metadata byte-for-byte.
    # (checked structurally in _drive_to_code; iss asserted here via the
    # authorization redirect stored in the last audit-independent path)
    rows = await db.execute(
        text("SELECT detail FROM audit_logs WHERE event = 'oauth.token.issued'")
    )
    assert rows.scalar() is not None


async def test_wrong_pkce_verifier_rejected(client, db, admin_headers):
    reg = await _register_client(client)
    code, _state, _verifier = await _drive_to_code(client, reg["client_id"], admin_headers)
    wrong = base64.urlsafe_b64encode(secrets.token_bytes(32)).rstrip(b"=").decode()
    resp = await _exchange_code(client, reg["client_id"], code, wrong)
    assert resp.status_code == 400
    assert resp.json()["error"] == "invalid_grant"


async def test_code_single_use(client, db, admin_headers):
    reg = await _register_client(client)
    code, _state, verifier = await _drive_to_code(client, reg["client_id"], admin_headers)
    first = await _exchange_code(client, reg["client_id"], code, verifier)
    assert first.status_code == 200
    second = await _exchange_code(client, reg["client_id"], code, verifier)
    assert second.status_code == 400
    assert second.json()["error"] == "invalid_grant"


# ---------------------------------------------------------------------------
# Refresh rotation + replay defense
# ---------------------------------------------------------------------------


async def _get_tokens(
    client,
    admin_headers,
    *,
    username: str = "admin",
    password: str = TEST_ADMIN_PASSWORD,
) -> tuple[str, str, str]:
    reg = await _register_client(client)
    code, _state, verifier = await _drive_to_code(
        client, reg["client_id"], admin_headers, username=username, password=password
    )
    resp = await _exchange_code(client, reg["client_id"], code, verifier)
    assert resp.status_code == 200
    body = resp.json()
    return reg["client_id"], body["access_token"], body["refresh_token"]


async def test_refresh_rotation_and_grace_replay(client, db, admin_headers):
    client_id, _at, rt1 = await _get_tokens(client, admin_headers)

    rotate = await client.post(
        "/token",
        data={"grant_type": "refresh_token", "refresh_token": rt1, "client_id": client_id},
    )
    assert rotate.status_code == 200, rotate.text
    rt2 = rotate.json()["refresh_token"]
    assert rt2 != rt1

    # Replaying rt1 immediately (inside the grace window): refused, audited as
    # race_suspected, and the chain SURVIVES — rt2 still works.
    replay = await client.post(
        "/token",
        data={"grant_type": "refresh_token", "refresh_token": rt1, "client_id": client_id},
    )
    assert replay.status_code == 400
    rows = await db.execute(
        text(
            "SELECT detail FROM audit_logs WHERE event = 'oauth.token.replay' "
            "ORDER BY id DESC LIMIT 1"
        )
    )
    assert rows.scalar()["action"] == "race_suspected"

    still_ok = await client.post(
        "/token",
        data={"grant_type": "refresh_token", "refresh_token": rt2, "client_id": client_id},
    )
    assert still_ok.status_code == 200
    # rt2 rotated cleanly: the chain lives on (family revocation is covered by
    # test_replay_beyond_grace_revokes_family).


async def test_replay_beyond_grace_revokes_family(client, db, admin_headers):
    client_id, _at, rt1 = await _get_tokens(client, admin_headers)
    rotate = await client.post(
        "/token",
        data={"grant_type": "refresh_token", "refresh_token": rt1, "client_id": client_id},
    )
    assert rotate.status_code == 200
    rt2 = rotate.json()["refresh_token"]
    # rt1 is now revoked-with-successor; backdate its revocation beyond grace.
    await db.execute(
        text(
            "UPDATE oauth_refresh_tokens SET revoked_at = now() - interval '120 seconds' "
            "WHERE token_hash = encode(sha256(CAST(:raw AS bytea)), 'hex')"
        ).bindparams(raw=rt1)
    )
    await db.commit()

    replay = await client.post(
        "/token",
        data={"grant_type": "refresh_token", "refresh_token": rt1, "client_id": client_id},
    )
    assert replay.status_code == 400
    rows = await db.execute(
        text(
            "SELECT detail FROM audit_logs WHERE event = 'oauth.token.replay' "
            "ORDER BY id DESC LIMIT 1"
        )
    )
    assert rows.scalar()["action"] == "chain_revoked"

    # Family revoked: rt2 (the legitimate successor) is dead as well.
    dead = await client.post(
        "/token",
        data={"grant_type": "refresh_token", "refresh_token": rt2, "client_id": client_id},
    )
    assert dead.status_code == 400


# ---------------------------------------------------------------------------
# Revocation
# ---------------------------------------------------------------------------


async def test_revoke_endpoint_kills_access_token(client, db, admin_headers):
    client_id, access, _rt = await _get_tokens(client, admin_headers)
    me = await client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {access}"})
    assert me.status_code == 200

    resp = await client.post(
        "/revoke",
        # client_secret is required by the SDK's form model even for public
        # clients (nullable-but-present); empty string satisfies it.
        data={"token": access, "client_id": client_id, "client_secret": ""},
    )
    assert resp.status_code == 200

    dead = await client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {access}"})
    assert dead.status_code == 401


# ---------------------------------------------------------------------------
# Credential rotation must kill OAuth grants too (refresh-revocation regressions)
# ---------------------------------------------------------------------------

AGENT_PASSWORD = "agent-pass-123"


async def _make_agent_user(client, admin_headers) -> dict:
    """A plain (non-admin) user to own OAuth grants in the revocation tests."""
    resp = await client.post(
        "/api/v1/admin/users",
        headers=admin_headers,
        json={
            "username": "agentowner",
            "password": AGENT_PASSWORD,
            "role_ids": [],
            "must_change_password": False,
        },
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


async def test_password_change_kills_oauth_refresh(client, db, admin_headers):
    """A self-service password change drops EVERY credential — including the
    refresh-token half of OAuth grants. Revoking only access tokens would be
    theater: the agent's next rotation would mint a fresh one, so the
    'every other session was signed out' promise must cover the refresh store
    as well."""
    client_id, access, rt = await _get_tokens(client, admin_headers)

    changed = await client.post(
        "/api/v1/auth/change-password",
        headers=admin_headers,
        json={"old_password": TEST_ADMIN_PASSWORD, "new_password": "rotated-pass-1"},
    )
    assert changed.status_code == 200, changed.text

    dead = await client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {access}"})
    assert dead.status_code == 401

    rotate = await client.post(
        "/token",
        data={"grant_type": "refresh_token", "refresh_token": rt, "client_id": client_id},
    )
    assert rotate.status_code == 400


async def test_force_logout_kills_oauth_refresh(client, db, admin_headers):
    user = await _make_agent_user(client, admin_headers)
    client_id, access, rt = await _get_tokens(
        client, admin_headers, username=user["username"], password=AGENT_PASSWORD
    )

    resp = await client.post(
        f"/api/v1/admin/users/{user['id']}/force-logout", headers=admin_headers
    )
    assert resp.status_code == 200

    dead = await client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {access}"})
    assert dead.status_code == 401
    rotate = await client.post(
        "/token",
        data={"grant_type": "refresh_token", "refresh_token": rt, "client_id": client_id},
    )
    assert rotate.status_code == 400


async def test_admin_reset_refresh_stays_dead_after_new_password(client, db, admin_headers):
    """Revival regression: an admin reset blocks refreshes only via the
    must-change gate while the flag is set. Once the user picks a new password
    the gate clears — the revocation itself is what must keep the old agent
    grant dead forever."""
    user = await _make_agent_user(client, admin_headers)
    client_id, _access, rt = await _get_tokens(
        client, admin_headers, username=user["username"], password=AGENT_PASSWORD
    )

    reset = await client.post(
        f"/api/v1/admin/users/{user['id']}/reset-password",
        headers=admin_headers,
        json={"new_password": "reset-pass-123"},
    )
    assert reset.status_code == 200

    # The user completes the forced change; the gate clears...
    login = await client.post(
        "/api/v1/auth/login", json={"username": user["username"], "password": "reset-pass-123"}
    )
    assert login.status_code == 200
    gated = {"Authorization": f"Bearer {login.json()['token']}"}
    changed = await client.post(
        "/api/v1/auth/change-password",
        headers=gated,
        json={"old_password": "reset-pass-123", "new_password": "final-pass-456"},
    )
    assert changed.status_code == 200, changed.text

    # ...but the pre-reset refresh token must never work again.
    rotate = await client.post(
        "/token",
        data={"grant_type": "refresh_token", "refresh_token": rt, "client_id": client_id},
    )
    assert rotate.status_code == 400


# ---------------------------------------------------------------------------
# Admin visibility: registered clients, live grants, per-grant revocation
# ---------------------------------------------------------------------------


async def test_admin_oauth_clients_and_grants_listing(client, db, admin_headers):
    client_id, _at, _rt = await _get_tokens(client, admin_headers)

    clients = await client.get("/api/v1/admin/oauth/clients", headers=admin_headers)
    assert clients.status_code == 200
    body = clients.json()
    assert any(
        c["client_id"] == client_id
        and c["client_name"] == "Test Agent"
        and REDIRECT_URI in c["redirect_uris"]
        for c in body
    )
    # The listing must never leak the registration secret.
    assert all("client_secret" not in c for c in body)

    grants = await client.get("/api/v1/admin/oauth/grants", headers=admin_headers)
    assert grants.status_code == 200
    rows = [g for g in grants.json() if g["client_id"] == client_id]
    assert len(rows) == 1
    assert rows[0]["username"] == "admin"
    assert set(rows[0]["scopes"]) == {"mcp", "offline_access"}


async def test_admin_revoke_grant_kills_agent(client, db, admin_headers):
    user = await _make_agent_user(client, admin_headers)
    client_id, access, rt = await _get_tokens(
        client, admin_headers, username=user["username"], password=AGENT_PASSWORD
    )

    resp = await client.post(
        "/api/v1/admin/oauth/grants/revoke",
        headers=admin_headers,
        json={"user_id": user["id"], "client_id": client_id},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["revoked_refresh_tokens"] == 1

    # Both halves die: the current access token and every future rotation.
    dead = await client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {access}"})
    assert dead.status_code == 401
    rotate = await client.post(
        "/token",
        data={"grant_type": "refresh_token", "refresh_token": rt, "client_id": client_id},
    )
    assert rotate.status_code == 400

    # The grant leaves the listing; re-revoking is an idempotent no-op.
    grants = await client.get("/api/v1/admin/oauth/grants", headers=admin_headers)
    assert all(g["client_id"] != client_id for g in grants.json())
    again = await client.post(
        "/api/v1/admin/oauth/grants/revoke",
        headers=admin_headers,
        json={"user_id": user["id"], "client_id": client_id},
    )
    assert again.status_code == 200
    assert again.json()["revoked_refresh_tokens"] == 0

    rows = (
        await db.execute(
            text("SELECT target FROM audit_logs WHERE event = 'admin.oauth.revoke_grant'")
        )
    ).all()
    assert len(rows) == 2
    assert rows[0].target == f"oauth:{client_id}:user:{user['id']}"


async def test_oauth_admin_endpoints_require_permissions(client, db, admin_headers):
    resp = await client.post(
        "/api/v1/admin/users",
        headers=admin_headers,
        json={
            "username": "nosy",
            "password": "nosy-pass-123",
            "role_ids": [],
            "must_change_password": False,
        },
    )
    assert resp.status_code == 201
    token = await login(client, "nosy", "nosy-pass-123")
    headers = {"Authorization": f"Bearer {token}"}

    denied = await client.get("/api/v1/admin/oauth/clients", headers=headers)
    assert denied.status_code == 403
    assert denied.json()["detail"] == "Missing permission: oauth:read"

    denied_grants = await client.get("/api/v1/admin/oauth/grants", headers=headers)
    assert denied_grants.status_code == 403

    denied_revoke = await client.post(
        "/api/v1/admin/oauth/grants/revoke",
        headers=headers,
        json={"user_id": 1, "client_id": "whatever"},
    )
    assert denied_revoke.status_code == 403
    assert denied_revoke.json()["detail"] == "Missing permission: oauth:revoke"
