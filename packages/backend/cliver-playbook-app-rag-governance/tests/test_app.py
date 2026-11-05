"""The package can assemble and serve its own application on top of rag."""

from __future__ import annotations

from httpx import ASGITransport, AsyncClient

from cliver_playbook.app.rag_governance.app import create_app
from cliver_playbook.app.rag_governance.settings import Settings


async def test_create_app_serves_governance_health(settings: Settings) -> None:
    app = create_app(settings)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/api/v1/rag-governance/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
