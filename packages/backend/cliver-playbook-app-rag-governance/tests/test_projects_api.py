"""Project and source API: validation, permission gate, config versions."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from cliver_playbook.app.rag_governance.models import GovConfigVersion

PROJECT = {
    "slug": "finance-kpi-demo",
    "name": "Finance KPI",
    "approval_mode": "hybrid",
}


async def test_create_project_and_source(client) -> None:
    response = await client.post("/api/v1/rag-governance/projects", json=PROJECT)
    assert response.status_code == 201
    project = response.json()
    assert project["slug"] == "finance-kpi-demo"
    assert project["collection_id"] == "finance-kpi-demo"
    assert project["active_config_version"] == 1

    response = await client.post(
        f"/api/v1/rag-governance/projects/{project['id']}/sources",
        json={
            "kind": "upload",
            "authority": "document",
            "config": {"logical_id": "fin-metric-catalog"},
        },
    )
    assert response.status_code == 201
    source = response.json()
    assert source["authority"] == "document"
    assert source["kind"] == "upload"
    assert source["project_id"] == project["id"]

    listing = await client.get(f"/api/v1/rag-governance/projects/{project['id']}/sources")
    assert [item["id"] for item in listing.json()["items"]] == [source["id"]]


async def test_duplicate_slug_is_rejected(client) -> None:
    assert (await client.post("/api/v1/rag-governance/projects", json=PROJECT)).status_code == 201
    response = await client.post("/api/v1/rag-governance/projects", json=PROJECT)
    assert response.status_code == 409


async def test_unknown_config_key_is_rejected(client) -> None:
    response = await client.post(
        "/api/v1/rag-governance/projects",
        json={**PROJECT, "config": {"threshold": 0.5}},
    )
    assert response.status_code == 422
    assert "threshold" in response.json()["detail"]


async def test_unknown_approval_mode_is_rejected_by_the_schema(client) -> None:
    response = await client.post(
        "/api/v1/rag-governance/projects",
        json={**PROJECT, "approval_mode": "sometimes"},
    )
    assert response.status_code == 422


async def test_update_appends_a_config_version(client, db_session: AsyncSession) -> None:
    project = (await client.post("/api/v1/rag-governance/projects", json=PROJECT)).json()

    response = await client.put(
        f"/api/v1/rag-governance/projects/{project['id']}",
        json={"config": {"thresholds": {"groundedness": 0.8}}},
    )

    assert response.status_code == 200
    updated = response.json()
    assert updated["active_config_version"] == 2
    assert updated["config"] == {"thresholds": {"groundedness": 0.8}}
    versions = (
        (
            await db_session.execute(
                select(GovConfigVersion)
                .where(GovConfigVersion.project_id == project["id"])
                .order_by(GovConfigVersion.version)
            )
        )
        .scalars()
        .all()
    )
    assert [version.version for version in versions] == [1, 2]


async def test_unauthenticated_caller_gets_401(raw_client) -> None:
    response = await raw_client.get("/api/v1/rag-governance/projects")
    assert response.status_code == 401
