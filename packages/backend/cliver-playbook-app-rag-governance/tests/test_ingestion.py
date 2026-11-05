"""Ingestion stages masked parent/child rows and never publishes them."""

from __future__ import annotations

import base64

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from cliver_playbook.app.rag.embedding.stub import StubEmbedder
from cliver_playbook.app.rag.models.entities import (
    Chunk,
    ChunkEmbedding,
    ChunkParent,
    Document,
)
from cliver_playbook.app.rag_governance.ingestion import IngestConfig, ingest_document
from cliver_playbook.app.rag_governance.models import GovProject
from cliver_playbook.app.rag_governance.stages import (
    ByExtensionClassifier,
    DirectorySource,
    PassthroughCleaner,
    RegexPiiMasker,
    SectionPathContextualizer,
    UploadSource,
)
from cliver_playbook.app.rag_governance.stages.base import SourceDocument


def _source(text: str) -> SourceDocument:
    return SourceDocument(
        source_uri="fin-metric-catalog.md",
        title="Finance metric catalog",
        mime_type="text/markdown",
        content=text.encode(),
        metadata={"filename": "fin-metric-catalog.md"},
    )


def _stages() -> dict:
    return {
        "embedder": StubEmbedder(),
        "cleaner": PassthroughCleaner(),
        "masker": RegexPiiMasker(),
        "classifier": ByExtensionClassifier(),
        "contextualizer": SectionPathContextualizer(),
    }


async def _project(db: AsyncSession) -> GovProject:
    project = GovProject(
        slug="finance-kpi-demo",
        name="Finance KPI",
        collection_id="finance-kpi",
    )
    db.add(project)
    await db.flush()
    return project


async def test_ingestion_stages_unpublished_parents_and_children(
    db_session: AsyncSession,
) -> None:
    project = await _project(db_session)

    result = await ingest_document(
        db_session,
        project=project,
        source_document=_source("# Metrics\nRevenue is up. Call 13800138000 for details.\n"),
        config=IngestConfig(
            logical_id="fin-metric-catalog",
            classification=3,
            pipeline_run_id="batch-1",
            child_size=256,
        ),
        **_stages(),
    )
    await db_session.commit()

    document = await db_session.get(Document, result.document_id)
    assert document is not None
    assert document.published is False
    assert document.logical_id == "fin-metric-catalog"
    assert document.collection_id == "finance-kpi"
    assert document.classification == 3
    assert result.masked_counts["phone"] == 1

    parents = (
        (
            await db_session.execute(
                select(ChunkParent).where(ChunkParent.document_id == document.id)
            )
        )
        .scalars()
        .all()
    )
    assert len(parents) == 1
    assert "[REDACTED]" in parents[0].text
    assert "13800138000" not in parents[0].text

    chunks = (
        (await db_session.execute(select(Chunk).where(Chunk.document_id == document.id)))
        .scalars()
        .all()
    )
    assert chunks
    assert all(chunk.search_text and chunk.parent_id for chunk in chunks)
    assert all("13800138000" not in (chunk.search_text or "") for chunk in chunks)
    assert chunks[0].search_text is not None
    assert chunks[0].search_text.startswith("H1#Metrics")

    embeddings = (
        (
            await db_session.execute(
                select(ChunkEmbedding).where(
                    ChunkEmbedding.chunk_id.in_([chunk.id for chunk in chunks])
                )
            )
        )
        .scalars()
        .all()
    )
    assert len(embeddings) == len(chunks)
    assert all(embedding.embedder_version == "stub@1.0" for embedding in embeddings)


async def test_reingest_bumps_version_and_keeps_each_staged_row(
    db_session: AsyncSession,
) -> None:
    project = await _project(db_session)

    first = await ingest_document(
        db_session,
        project=project,
        source_document=_source("# Metrics\nfirst revision\n"),
        config=IngestConfig(logical_id="fin-metric-catalog", pipeline_run_id="batch-1"),
        **_stages(),
    )
    second = await ingest_document(
        db_session,
        project=project,
        source_document=_source("# Metrics\nsecond revision\n"),
        config=IngestConfig(logical_id="fin-metric-catalog", pipeline_run_id="batch-2"),
        **_stages(),
    )
    await db_session.commit()

    assert second.version == first.version + 1
    rows = (
        (
            await db_session.execute(
                select(Document).where(Document.logical_id == "fin-metric-catalog")
            )
        )
        .scalars()
        .all()
    )
    assert len(rows) == 2
    assert all(row.published is False for row in rows)


async def test_retrying_the_same_run_reuses_the_row_and_replaces_its_chunks(
    db_session: AsyncSession,
) -> None:
    project = await _project(db_session)

    first = await ingest_document(
        db_session,
        project=project,
        source_document=_source("# Metrics\nfirst attempt\n"),
        config=IngestConfig(logical_id="fin-metric-catalog", pipeline_run_id="batch-1"),
        **_stages(),
    )
    second = await ingest_document(
        db_session,
        project=project,
        source_document=_source("# Metrics\nfirst attempt\n"),
        config=IngestConfig(logical_id="fin-metric-catalog", pipeline_run_id="batch-1"),
        **_stages(),
    )
    await db_session.commit()

    assert second.document_id == first.document_id
    assert second.version == first.version
    rows = (
        (
            await db_session.execute(
                select(Document).where(Document.logical_id == "fin-metric-catalog")
            )
        )
        .scalars()
        .all()
    )
    assert len(rows) == 1
    chunks = (
        (await db_session.execute(select(Chunk).where(Chunk.document_id == second.document_id)))
        .scalars()
        .all()
    )
    assert len(chunks) == second.chunk_count


def test_upload_source_decodes_base64_content() -> None:
    documents = list(
        UploadSource().fetch(
            {
                "logical_id": "fin-metric-catalog",
                "filename": "fin.md",
                "content_b64": base64.b64encode(b"# Metrics\nbody").decode(),
                "mime_type": "text/markdown",
            }
        )
    )

    assert len(documents) == 1
    assert documents[0].content == b"# Metrics\nbody"
    assert documents[0].metadata["logical_id"] == "fin-metric-catalog"


def test_directory_source_reads_only_matching_files(tmp_path) -> None:
    (tmp_path / "b.md").write_text("# B\nbeta", encoding="utf-8")
    (tmp_path / "a.txt").write_text("alpha", encoding="utf-8")
    (tmp_path / "skip.pdf").write_bytes(b"%PDF")

    documents = list(
        DirectorySource().fetch({"path": str(tmp_path), "logical_id_prefix": "manual/"})
    )

    assert [document.metadata["relative_path"] for document in documents] == ["a.txt", "b.md"]
    assert [document.metadata["logical_id"] for document in documents] == [
        "manual/a",
        "manual/b",
    ]
    assert documents[1].mime_type == "text/markdown"
