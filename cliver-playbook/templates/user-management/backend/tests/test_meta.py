"""Meta endpoint tests: health (with real DB round-trip) and version."""


async def test_health_ok(client):
    resp = await client.get("/api/v1/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


async def test_version_shape(client):
    resp = await client.get("/api/v1/version")
    assert resp.status_code == 200
    body = resp.json()
    assert body["api"] == "v1"
    assert body["app"]
