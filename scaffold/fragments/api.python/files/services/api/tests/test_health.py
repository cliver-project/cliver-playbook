import pytest


@pytest.mark.asyncio
async def test_health(client) -> None:
    response = await client.get("/api/v1/health")
    assert response.status_code == 200
