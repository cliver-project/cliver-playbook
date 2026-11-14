import uuid

import pytest


@pytest.mark.asyncio
async def test_register_login_me_profile(client):
    username = f"user_{uuid.uuid4().hex[:10]}"
    registered = await client.post(
        "/api/v1/auth/register",
        json={
            "username": username,
            "password": "secret123",
            "display_name": "Scaffold Tester",
        },
    )
    assert registered.status_code == 201, registered.text
    token = registered.json()["token"]
    headers = {"Authorization": f"Bearer {token}"}

    me = await client.get("/api/v1/auth/me", headers=headers)
    assert me.status_code == 200, me.text
    assert me.json()["user"]["username"] == username

    profile = await client.patch(
        "/api/v1/auth/profile",
        json={"display_name": "Updated Tester"},
        headers=headers,
    )
    assert profile.status_code == 200, profile.text
    assert profile.json()["user"]["display_name"] == "Updated Tester"

    login = await client.post(
        "/api/v1/auth/login",
        json={"username": username, "password": "secret123"},
    )
    assert login.status_code == 200, login.text
    assert login.json()["token"]


@pytest.mark.asyncio
async def test_duplicate_registration_is_rejected(client):
    username = f"user_{uuid.uuid4().hex[:10]}"
    payload = {"username": username, "password": "secret123"}
    first = await client.post("/api/v1/auth/register", json=payload)
    assert first.status_code == 201, first.text
    second = await client.post("/api/v1/auth/register", json=payload)
    assert second.status_code == 409, second.text


@pytest.mark.asyncio
async def test_me_requires_a_token(client):
    response = await client.get("/api/v1/auth/me")
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_login_rejects_a_wrong_password(client):
    username = f"user_{uuid.uuid4().hex[:10]}"
    registered = await client.post(
        "/api/v1/auth/register",
        json={"username": username, "password": "secret123"},
    )
    assert registered.status_code == 201, registered.text
    response = await client.post(
        "/api/v1/auth/login",
        json={"username": username, "password": "wrong-password"},
    )
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_profile_can_clear_optional_fields(client):
    username = f"user_{uuid.uuid4().hex[:10]}"
    registered = await client.post(
        "/api/v1/auth/register",
        json={
            "username": username,
            "password": "secret123",
            "email": f"{username}@example.com",
            "display_name": "Clear Me",
        },
    )
    assert registered.status_code == 201, registered.text
    headers = {"Authorization": f"Bearer {registered.json()['token']}"}

    cleared = await client.patch(
        "/api/v1/auth/profile",
        json={"email": None, "phone": None},
        headers=headers,
    )
    assert cleared.status_code == 200, cleared.text
    assert cleared.json()["user"]["email"] is None
    assert cleared.json()["user"]["phone"] is None
