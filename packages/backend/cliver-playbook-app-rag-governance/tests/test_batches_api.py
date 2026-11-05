"""Batch API: ingest trigger, staged preview and its permission gate."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from cliver_playbook.app.rag.models.entities import Document
from cliver_playbook.app.rag_governance.models import GovIngestBatch, GovJob


async def _project_and_source(client, *, authority: str = "document") -> tuple[dict, dict]:
    project = (
        await client.post(
            "/api/v1/rag-governance/projects",
            json={
                "slug": "finance-kpi-demo",
                "name": "Finance KPI",
                "approval_mode": "manual",
            },
        )
    ).json()
    source = (
        await client.post(
            f"/api/v1/rag-governance/projects/{project['id']}/sources",
            json={
                "kind": "upload",
                "authority": authority,
                "config": {"logical_id": "fin-metric-catalog"},
            },
        )
    ).json()
    return project, source


async def test_ingest_enqueues_a_job(client, db_session: AsyncSession) -> None:
    _, source = await _project_and_source(client)

    response = await client.post(f"/api/v1/rag-governance/sources/{source['id']}/ingest", json={})

    assert response.status_code == 202
    accepted = response.json()
    assert accepted["kind"] == "ingest_batch"
    assert accepted["status"] == "queued"

    batch = await db_session.get(GovIngestBatch, accepted["batch_id"])
    assert batch is not None
    assert batch.status == "queued"
    job = await db_session.get(GovJob, accepted["job_id"])
    assert job is not None
    assert job.kind == "ingest_batch"
    assert job.payload_json["batch_id"] == accepted["batch_id"]


async def test_capability_source_is_not_ingested(client) -> None:
    _, source = await _project_and_source(client, authority="capability")

    response = await client.post(f"/api/v1/rag-governance/sources/{source['id']}/ingest", json={})

    assert response.status_code == 422
    assert "queried live" in response.json()["detail"]


async def test_batch_detail_and_list(client) -> None:
    project, source = await _project_and_source(client)
    accepted = (
        await client.post(f"/api/v1/rag-governance/sources/{source['id']}/ingest", json={})
    ).json()

    detail = await client.get(f"/api/v1/rag-governance/batches/{accepted['batch_id']}")
    assert detail.status_code == 200
    assert detail.json()["id"] == accepted["batch_id"]

    listing = await client.get(f"/api/v1/rag-governance/projects/{project['id']}/batches")
    assert [item["id"] for item in listing.json()["items"]] == [accepted["batch_id"]]


async def test_staged_preview_shows_unpublished_documents(client, db_session: AsyncSession) -> None:
    project, source = await _project_and_source(client)
    accepted = (
        await client.post(f"/api/v1/rag-governance/sources/{source['id']}/ingest", json={})
    ).json()
    db_session.add(
        Document(
            id="doc-staged-1",
            title="Finance catalog",
            mime_type="text/markdown",
            chunker_id="parent-child",
            chunker_config={},
            embedder_id="stub@1.0",
            dim=64,
            version=1,
            status="indexed",
            chunk_count=0,
            logical_id="fin-metric-catalog",
            classification=4,
            collection_id=project["collection_id"],
            published=False,
            pipeline_run_id=accepted["batch_id"],
        )
    )
    await db_session.commit()

    response = await client.get(f"/api/v1/rag-governance/batches/{accepted['batch_id']}/staged")

    assert response.status_code == 200
    items = response.json()["items"]
    assert [item["id"] for item in items] == ["doc-staged-1"]
    assert items[0]["published"] is False
    assert items[0]["classification"] == 4


async def test_staged_endpoint_requires_permission(raw_client) -> None:
    response = await raw_client.get("/api/v1/rag-governance/batches/x/staged")
    assert response.status_code == 401
