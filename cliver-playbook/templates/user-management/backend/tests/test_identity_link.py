"""Self-service external identity linking: state-blob modes, link start,
callback attach, listing, unlinking, and the last-credential guard.

Builds on test_oidc's mock IdP (handler, registry and fixture imported) —
the linking user is the seeded admin (a password account); OIDC-only
accounts are created directly and given tokens through issue_web_token,
since they have no password to log in with.
"""

import base64
import hashlib
import hmac
import json
import time
from urllib.parse import parse_qs, urlparse

import httpx
import pytest
from sqlalchemy import select

from app.auth.oidc import sign_state_blob, state_cookie_name, verify_state_blob
from app.core.config import get_settings
from app.models.entities import AuditLog, OauthIdentity, User
from tests.helpers import TEST_ADMIN_PASSWORD, login, seed_admin
from tests.test_oidc import FRONTEND, _frag_params, _idp_handler, _provider


@pytest.fixture
def idp(monkeypatch):
    """Same mock IdP as test_oidc: transport seam + provider registry."""
    import app.api.auth as auth_api
    from app.auth import oidc

    monkeypatch.setattr(
        oidc,
        "_open_client",
        lambda: httpx.AsyncClient(transport=httpx.MockTransport(_idp_handler())),
    )
    monkeypatch.setattr(auth_api, "build_provider_registry", _provider)
    monkeypatch.setattr(oidc, "_discovery_cache", {})
    return oidc


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


async def _make_user(db, username: str, *, password_hash: str = "") -> User:
    """Insert a user directly — default shape is an OIDC-only account."""
    user = User(
        username=username,
        password_hash=password_hash,
        display_name=username,
        is_active=True,
        must_change_password=False,
    )
    db.add(user)
    await db.commit()
    return user


async def _token_for(db, user_id: int) -> str:
    """A web token for a directly-created (passwordless) user. Committed:
    routes run on their own session, so a merely-flushed row is invisible."""
    from app.auth.tokens import issue_web_token

    token = await issue_web_token(db, user_id=user_id, ip="127.0.0.1", user_agent="test")
    await db.commit()
    return token


def _sign_raw(payload_dict: dict) -> str:
    """Sign an arbitrary state-blob payload (legacy/corrupt shapes)."""
    payload = json.dumps(payload_dict, separators=(",", ":")).encode()
    sig = hmac.new(get_settings().hmac_secret, payload, hashlib.sha256).hexdigest()
    return base64.urlsafe_b64encode(payload + b"." + sig.encode()).decode()


async def _link_flow(client, token: str, provider: str = "default") -> str:
    """POST link start, then drive the callback with the IdP 'issuing' code
    xyz; returns the final redirect Location."""
    start = await client.post(f"/api/v1/auth/identities/{provider}/link", headers=_auth(token))
    assert start.status_code == 200, start.text
    redirect_url = start.json()["redirect_url"]
    state = {k: v[0] for k, v in parse_qs(urlparse(redirect_url).query).items()}["state"]
    cookie = start.headers["set-cookie"].split(";")[0]
    callback = await client.get(
        f"/api/v1/auth/oauth/{provider}/callback",
        params={"code": "xyz", "state": state},
        headers={"Cookie": cookie},
    )
    assert callback.status_code == 302
    return callback.headers["location"]


# ---------------------------------------------------------------------------
# State blob modes
# ---------------------------------------------------------------------------


def test_state_blob_link_roundtrip():
    blob = sign_state_blob("default", "st1", "verifier-1", mode="link", user_id=42)
    data = verify_state_blob(blob, provider_key="default", state="st1")
    assert data is not None
    assert data["mode"] == "link"
    assert data["user_id"] == 42
    assert data["verifier"] == "verifier-1"


def test_state_blob_defaults_to_login_mode():
    # Current signer without mode arguments -> explicit login.
    data = verify_state_blob(
        sign_state_blob("default", "s1", "v1"), provider_key="default", state="s1"
    )
    assert data is not None
    assert data["mode"] == "login"
    # A blob signed BEFORE the mode field existed (a cookie in flight across
    # a deploy) still verifies, as login.
    legacy = _sign_raw(
        {"provider": "default", "state": "s2", "verifier": "v2", "exp": int(time.time()) + 60}
    )
    data = verify_state_blob(legacy, provider_key="default", state="s2")
    assert data is not None
    assert data["mode"] == "login"
    assert data["verifier"] == "v2"


async def test_link_blob_without_userid_rejected(idp, client, db):
    """A link-mode blob missing its pinned user id is corrupt: fail closed
    through the generic state-mismatch path (no details to an attacker)."""
    await seed_admin(db)
    blob = _sign_raw(
        {
            "provider": "default",
            "state": "s3",
            "verifier": "v3",
            "mode": "link",
            "exp": int(time.time()) + 60,
        }
    )
    callback = await client.get(
        "/api/v1/auth/oauth/default/callback",
        params={"code": "xyz", "state": "s3"},
        headers={"Cookie": f"{state_cookie_name}={blob}"},
    )
    assert callback.status_code == 302
    assert _frag_params(callback.headers["location"]).get("error") == "state_mismatch"


# ---------------------------------------------------------------------------
# Link start
# ---------------------------------------------------------------------------


async def test_link_start_shape_and_cookie(idp, client, db):
    admin_id = await seed_admin(db)
    token = await login(client, "admin", TEST_ADMIN_PASSWORD)
    resp = await client.post("/api/v1/auth/identities/default/link", headers=_auth(token))
    assert resp.status_code == 200
    url = urlparse(resp.json()["redirect_url"])
    assert f"{url.scheme}://{url.netloc}{url.path}" == "https://idp.example.com/authorize"
    params = {k: v[0] for k, v in parse_qs(url.query).items()}
    assert params["client_id"] == "client-1"
    assert params["code_challenge_method"] == "S256"
    assert params["redirect_uri"].endswith("/api/v1/auth/oauth/default/callback")
    set_cookie = resp.headers["set-cookie"]
    assert "cliver_oauth_state=" in set_cookie and "HttpOnly" in set_cookie
    # The signed blob pins the linking user.
    blob = set_cookie.split("cliver_oauth_state=", 1)[1].split(";", 1)[0]
    data = verify_state_blob(blob, provider_key="default", state=params["state"])
    assert data is not None
    assert data["mode"] == "link"
    assert data["user_id"] == admin_id


async def test_link_start_unknown_provider_404(idp, client, db):
    await seed_admin(db)
    token = await login(client, "admin", TEST_ADMIN_PASSWORD)
    resp = await client.post("/api/v1/auth/identities/nope/link", headers=_auth(token))
    assert resp.status_code == 404


async def test_link_start_idp_down_502(monkeypatch, idp, client, db):
    """A direct API call (no redirect chain to steer): IdP unavailability is
    an honest 502, not an SPA error redirect."""

    def broken(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503)

    monkeypatch.setattr(
        idp,
        "_open_client",
        lambda: httpx.AsyncClient(transport=httpx.MockTransport(broken)),
    )
    await seed_admin(db)
    token = await login(client, "admin", TEST_ADMIN_PASSWORD)
    resp = await client.post("/api/v1/auth/identities/default/link", headers=_auth(token))
    assert resp.status_code == 502


# ---------------------------------------------------------------------------
# Callback: attach the identity
# ---------------------------------------------------------------------------


async def test_full_link_flow(idp, client, db):
    admin_id = await seed_admin(db)
    token = await login(client, "admin", TEST_ADMIN_PASSWORD)

    location = await _link_flow(client, token)
    assert location.startswith(f"{FRONTEND}/profile#")
    frag = _frag_params(location)
    assert frag.get("linked") == "default"
    assert "token" not in frag  # link flow NEVER issues a session token

    ident = (await db.execute(select(OauthIdentity))).scalars().one()
    assert ident.user_id == admin_id
    assert ident.provider == "default"
    assert ident.subject == "idp-user-1"
    audit = (
        (await db.execute(select(AuditLog).where(AuditLog.event == "auth.identity.link")))
        .scalars()
        .one()
    )
    assert audit.ok is True
    assert audit.user_id == admin_id
    assert audit.target == "oidc:default"


async def test_link_is_idempotent(idp, client, db):
    await seed_admin(db)
    token = await login(client, "admin", TEST_ADMIN_PASSWORD)
    first = await _link_flow(client, token)
    second = await _link_flow(client, token)
    assert _frag_params(first).get("linked") == "default"
    assert _frag_params(second).get("linked") == "default"
    rows = (await db.execute(select(OauthIdentity))).scalars().all()
    assert len(rows) == 1  # re-linking the same identity adds no row


async def test_link_inactive_user_rejected(idp, client, db):
    """The pinned user is re-checked at callback time: deactivated mid-flow,
    the link lands on #link_error=not_allowed and nothing is stored."""
    admin_id = await seed_admin(db)
    token = await login(client, "admin", TEST_ADMIN_PASSWORD)
    start = await client.post("/api/v1/auth/identities/default/link", headers=_auth(token))
    state = {k: v[0] for k, v in parse_qs(urlparse(start.json()["redirect_url"]).query).items()}[
        "state"
    ]
    cookie = start.headers["set-cookie"].split(";")[0]

    admin = await db.get(User, admin_id)
    admin.is_active = False
    await db.commit()

    callback = await client.get(
        "/api/v1/auth/oauth/default/callback",
        params={"code": "xyz", "state": state},
        headers={"Cookie": cookie},
    )
    assert _frag_params(callback.headers["location"]).get("link_error") == "not_allowed"
    assert (await db.execute(select(OauthIdentity))).scalars().one_or_none() is None


async def test_link_identity_owned_by_other(idp, client, db):
    await seed_admin(db)
    token = await login(client, "admin", TEST_ADMIN_PASSWORD)
    other = await _make_user(db, "other-user")
    db.add(
        OauthIdentity(
            provider="default", subject="idp-user-1", user_id=other.id, display_name="Dev"
        )
    )
    await db.commit()

    location = await _link_flow(client, token)
    assert _frag_params(location).get("link_error") == "already_linked"
    owner = (await db.execute(select(OauthIdentity))).scalars().one()
    assert owner.user_id == other.id  # ownership unchanged
    audit = (
        (await db.execute(select(AuditLog).where(AuditLog.event == "auth.identity.link")))
        .scalars()
        .one()
    )
    assert audit.ok is False
    assert audit.error == "already_linked"


async def test_link_race_already_linked(monkeypatch, idp, client, db):
    """The pre-insert check races a concurrent link: the unique constraint
    on (provider, subject) is the backstop, surfacing as already_linked."""
    import app.api.auth as auth_api

    await seed_admin(db)
    token = await login(client, "admin", TEST_ADMIN_PASSWORD)
    other = await _make_user(db, "other-user")
    db.add(OauthIdentity(provider="default", subject="idp-user-1", user_id=other.id))
    await db.commit()

    async def never_linked(db_, provider_key, subject):
        return None  # simulate the lookup losing the race

    monkeypatch.setattr(auth_api, "find_linked_user", never_linked)
    location = await _link_flow(client, token)
    assert _frag_params(location).get("link_error") == "already_linked"
    owner = (await db.execute(select(OauthIdentity))).scalars().one()
    assert owner.user_id == other.id


# ---------------------------------------------------------------------------
# Listing
# ---------------------------------------------------------------------------


async def test_list_identities_labels(idp, client, db):
    admin_id = await seed_admin(db)
    token = await login(client, "admin", TEST_ADMIN_PASSWORD)
    await _link_flow(client, token)
    # "legacy" was never in the settings registry -> raw-key fallback;
    # "google" resolves through the bundled (disabled) app.yaml preset,
    # proving disabled providers still label their rows.
    db.add(OauthIdentity(provider="legacy", subject="leg-1", user_id=admin_id))
    db.add(OauthIdentity(provider="google", subject="g-1", user_id=admin_id))
    await db.commit()

    resp = await client.get("/api/v1/auth/identities", headers=_auth(token))
    assert resp.status_code == 200
    by_provider = {row["provider"]: row for row in resp.json()}
    assert set(by_provider) == {"default", "legacy", "google"}
    assert by_provider["default"]["provider_label"] == "default"
    assert by_provider["google"]["provider_label"] == "Google"
    assert by_provider["default"]["email"] == "dev@example.com"
    assert "linked_at" in by_provider["default"]
    # Password account: unlinking is always allowed, never "last credential".
    assert all(row["is_last_credential"] is False for row in by_provider.values())


# ---------------------------------------------------------------------------
# Unlink
# ---------------------------------------------------------------------------


async def test_unlink_happy_path(idp, client, db):
    await seed_admin(db)
    token = await login(client, "admin", TEST_ADMIN_PASSWORD)
    await _link_flow(client, token)
    ident = (await db.execute(select(OauthIdentity))).scalars().one()

    resp = await client.delete(f"/api/v1/auth/identities/{ident.id}", headers=_auth(token))
    assert resp.status_code == 204
    assert (await db.execute(select(OauthIdentity))).scalars().one_or_none() is None
    audit = (
        (await db.execute(select(AuditLog).where(AuditLog.event == "auth.identity.unlink")))
        .scalars()
        .one()
    )
    assert audit.ok is True
    assert audit.target == "oidc:default"


async def test_unlink_foreign_identity_404(idp, client, db):
    """Deleting someone else's identity is a plain 404 — no existence leak."""
    await seed_admin(db)
    token = await login(client, "admin", TEST_ADMIN_PASSWORD)
    solo = await _make_user(db, "solo-user")
    db.add(OauthIdentity(provider="default", subject="s1", user_id=solo.id))
    await db.commit()
    ident = (await db.execute(select(OauthIdentity))).scalars().one()

    resp = await client.delete(f"/api/v1/auth/identities/{ident.id}", headers=_auth(token))
    assert resp.status_code == 404
    assert (await db.execute(select(OauthIdentity))).scalars().one_or_none() is not None


async def test_unlink_last_credential_oidc_only_409(idp, client, db):
    """An OIDC-only account may not unlink its last remaining identity —
    server-enforced 409 (the UI's greyed-out button is only courtesy)."""
    await seed_admin(db)
    solo = await _make_user(db, "solo-user")
    db.add(OauthIdentity(provider="default", subject="s1", user_id=solo.id))
    await db.commit()
    token = await _token_for(db, solo.id)
    ident = (await db.execute(select(OauthIdentity))).scalars().one()

    resp = await client.delete(f"/api/v1/auth/identities/{ident.id}", headers=_auth(token))
    assert resp.status_code == 409
    assert (await db.execute(select(OauthIdentity))).scalars().one_or_none() is not None


async def test_oidc_only_unlink_down_to_last(idp, client, db):
    """Two identities on an OIDC-only account: the first unlink succeeds and
    flips is_last_credential on the survivor; the second is refused."""
    await seed_admin(db)
    solo = await _make_user(db, "solo-user")
    db.add(OauthIdentity(provider="default", subject="s1", user_id=solo.id))
    db.add(OauthIdentity(provider="mockhub", subject="777", user_id=solo.id))
    await db.commit()
    token = await _token_for(db, solo.id)

    listing = await client.get("/api/v1/auth/identities", headers=_auth(token))
    ids = {row["provider"]: row["id"] for row in listing.json()}
    assert all(row["is_last_credential"] is False for row in listing.json())

    first = await client.delete(f"/api/v1/auth/identities/{ids['default']}", headers=_auth(token))
    assert first.status_code == 204

    survivor = await client.get("/api/v1/auth/identities", headers=_auth(token))
    rows = survivor.json()
    assert len(rows) == 1
    assert rows[0]["is_last_credential"] is True

    second = await client.delete(f"/api/v1/auth/identities/{ids['mockhub']}", headers=_auth(token))
    assert second.status_code == 409


# ---------------------------------------------------------------------------
# Route gating
# ---------------------------------------------------------------------------


async def test_identity_routes_behind_must_change_gate(idp, client, db):
    """All three identity routes stay behind the must-change-password gate
    (they are deliberately absent from its allowlist)."""
    admin_id = await seed_admin(db)
    token = await login(client, "admin", TEST_ADMIN_PASSWORD)
    admin = await db.get(User, admin_id)
    admin.must_change_password = True
    await db.commit()

    start = await client.post("/api/v1/auth/identities/default/link", headers=_auth(token))
    listing = await client.get("/api/v1/auth/identities", headers=_auth(token))
    delete = await client.delete("/api/v1/auth/identities/1", headers=_auth(token))
    assert start.status_code == 403
    assert listing.status_code == 403
    assert delete.status_code == 403
