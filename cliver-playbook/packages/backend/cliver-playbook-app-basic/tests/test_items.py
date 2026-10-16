"""Item CRUD endpoint tests: happy paths, 404s, validation, list ordering."""


async def test_create_and_get_item(client):
    payload = {"name": "Widget", "description": "A demo item", "quantity": 3}
    resp = await client.post("/api/v1/items", json=payload)
    assert resp.status_code == 201
    created = resp.json()
    assert created["name"] == "Widget"
    assert created["quantity"] == 3
    assert created["id"] > 0

    resp = await client.get(f"/api/v1/items/{created['id']}")
    assert resp.status_code == 200
    assert resp.json()["name"] == "Widget"


async def test_create_item_validation_errors(client):
    # Empty name and negative quantity are both rejected with 422.
    assert (await client.post("/api/v1/items", json={"name": ""})).status_code == 422
    assert (
        await client.post("/api/v1/items", json={"name": "x", "quantity": -1})
    ).status_code == 422


async def test_get_missing_item_returns_404(client):
    resp = await client.get("/api/v1/items/9999")
    assert resp.status_code == 404


async def test_update_item_partial_patch(client):
    created = (await client.post("/api/v1/items", json={"name": "Old", "quantity": 1})).json()
    resp = await client.patch(f"/api/v1/items/{created['id']}", json={"quantity": 7})
    assert resp.status_code == 200
    body = resp.json()
    assert body["quantity"] == 7
    assert body["name"] == "Old"  # untouched fields survive a partial patch


async def test_update_missing_item_returns_404(client):
    assert (await client.patch("/api/v1/items/9999", json={"name": "x"})).status_code == 404


async def test_delete_item(client):
    created = (await client.post("/api/v1/items", json={"name": "Bye"})).json()
    assert (await client.delete(f"/api/v1/items/{created['id']}")).status_code == 204
    assert (await client.get(f"/api/v1/items/{created['id']}")).status_code == 404


async def test_list_orders_newest_first(client):
    await client.post("/api/v1/items", json={"name": "first"})
    await client.post("/api/v1/items", json={"name": "second"})
    resp = await client.get("/api/v1/items")
    assert resp.status_code == 200
    names = [item["name"] for item in resp.json()]
    assert names == ["second", "first"]
