"""The ingestion pipeline: mask, split, contextualize, embed, stage.

The order is a privacy guarantee, not a preference. Cleaning and
masking run before the text is split, so a raw phone number or ID
never reaches a parent row, a search representation, a vector, or a
model prompt. The source bytes are decoded, processed and dropped; only
masked text is persisted (R9 in the design).

Every ingest writes ``published=False``. The document row, its parents,
its children and their embeddings are one transaction: a batch either
stages a complete document version or stages nothing. Publishing is a
separate, explicit transition (Task 14), which is why this module never
flips the flag.

Re-ingesting the same logical document creates a new ``version`` and a
new document row. Retrying the same pipeline run (same
``pipeline_run_id``) reuses that row and replaces only the rows it
owns, so a job retry cannot duplicate a document.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
from dataclasses import dataclass
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from cliver_playbook.app.rag.chunking.base import make_chunk_id
from cliver_playbook.app.rag.embedding.base import Embedder
from cliver_playbook.app.rag.models.entities import (
    Chunk,
    ChunkEmbedding,
    ChunkParent,
    Document,
)
from cliver_playbook.app.rag_governance.ingestion.parent_child import (
    ParentSection,
    split_parent_child,
)
from cliver_playbook.app.rag_governance.models.entities import GovProject
from cliver_playbook.app.rag_governance.stages.base import (
    Cleaner,
    Contextualizer,
    Masker,
    SourceDocument,
    TypeClassifier,
)

logger = logging.getLogger("cliver_playbook.app.rag_governance.ingestion.pipeline")

PARENT_CHILD_CHUNKER = "parent-child"


class IngestConfig(BaseModel):
    """The project/source facts one ingest needs.

    This is a narrow view of ``gov_projects.config_json``, not the
    project config itself: the pipeline must not learn about taxonomy,
    rule thresholds or tool profiles it does not use. Extra keys are
    rejected so a renamed field fails at the boundary instead of being
    silently ignored.
    """

    model_config = ConfigDict(extra="forbid")

    logical_id: str
    classification: int = Field(default=0, ge=0, le=5)
    pipeline_run_id: str | None = None
    child_size: int = Field(default=512, gt=0)
    child_overlap: int = Field(default=64, ge=0)
    parent_max_chars: int = Field(default=4000, gt=0)
    # Document type -> chunker policy name. Only ``parent-child`` ships
    # in v1; the map exists so a project can be explicit about types
    # it wants rejected rather than silently coerced.
    type_to_chunker: dict[str, str] = Field(default_factory=dict)
    chunker: str = PARENT_CHILD_CHUNKER

    @model_validator(mode="after")
    def _overlap_within_size(self) -> IngestConfig:
        if self.child_overlap >= self.child_size:
            raise ValueError("child_overlap must be smaller than child_size")
        return self


@dataclass(frozen=True)
class IngestResult:
    """What one ingest staged. Counts feed batch stats and review UI."""

    document_id: str
    logical_id: str
    version: int
    parent_count: int
    chunk_count: int
    masked_counts: dict[str, int]
    doc_type: str


@dataclass(frozen=True)
class _Prepared:
    doc_type: str
    sections: list[ParentSection]
    search_texts: list[str]
    masked_counts: dict[str, int]
    content_hash: str


async def ingest_document(
    db: AsyncSession,
    *,
    project: GovProject,
    source_document: SourceDocument,
    config: IngestConfig,
    embedder: Embedder,
    cleaner: Cleaner,
    masker: Masker,
    classifier: TypeClassifier,
    contextualizer: Contextualizer,
) -> IngestResult:
    """Stage one document version. The caller owns the commit."""
    raw_text = _decode(source_document)
    prepared = await asyncio.to_thread(
        _prepare,
        raw_text,
        source_document,
        config,
        cleaner,
        masker,
        classifier,
        contextualizer,
    )
    vectors = await asyncio.to_thread(embedder.embed, prepared.search_texts, mode="document")
    if len(vectors) != len(prepared.search_texts):
        raise ValueError("embedder returned a different number of vectors than texts")

    existing = await _existing_run_document(db, project, config)
    if existing is not None:
        version = existing.version
        document_id = existing.id
        await _delete_staged_rows(db, document_id)
    else:
        version = await _next_version(db, project, config)
        document_id = _document_id(project.collection_id, config.logical_id, version)

    document = existing if existing is not None else Document(id=document_id)
    if existing is None:
        db.add(document)
    _assign_document_fields(
        document,
        project=project,
        source_document=source_document,
        config=config,
        embedder=embedder,
        prepared=prepared,
        version=version,
    )
    await db.flush()

    parent_rows, chunk_rows, embedding_rows = _build_rows(
        document_id=document_id,
        version=version,
        embedder=embedder,
        prepared=prepared,
        vectors=vectors,
    )
    # Explicit flush order: parents before children, children before
    # embeddings. The foreign keys are plain columns (no ORM
    # relationships), so SQLAlchemy cannot infer the insert order; on
    # PostgreSQL out-of-order inserts would violate the FK.
    db.add_all(parent_rows)
    await db.flush()
    db.add_all(chunk_rows)
    await db.flush()
    db.add_all(embedding_rows)
    await db.flush()

    return IngestResult(
        document_id=document_id,
        logical_id=config.logical_id,
        version=version,
        parent_count=len(parent_rows),
        chunk_count=len(chunk_rows),
        masked_counts=prepared.masked_counts,
        doc_type=prepared.doc_type,
    )


def _decode(source_document: SourceDocument) -> str:
    """Decode the source as UTF-8 text.

    Governance v1 ingests text/markdown sources. A binary format must
    go through a format-specific parser before this pipeline; failing
    loudly here is safer than letting ``errors="replace"`` corrupt the
    stored parents.
    """
    try:
        return source_document.content.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise ValueError(
            f"source document {source_document.source_uri!r} is not UTF-8 text"
        ) from exc


def _prepare(
    raw_text: str,
    source_document: SourceDocument,
    config: IngestConfig,
    cleaner: Cleaner,
    masker: Masker,
    classifier: TypeClassifier,
    contextualizer: Contextualizer,
) -> _Prepared:
    """Pure-text half of the pipeline; safe to run off the event loop."""
    cleaned = cleaner.clean(raw_text)
    masked = masker.mask(cleaned.text)
    doc_type = classifier.classify(source_document)

    chunker = config.type_to_chunker.get(doc_type, config.chunker)
    if chunker != PARENT_CHILD_CHUNKER:
        raise ValueError(
            f"unsupported chunker policy {chunker!r} for document type {doc_type!r}; "
            f"only {PARENT_CHILD_CHUNKER!r} is available"
        )

    sections = split_parent_child(
        masked.text,
        child_size=config.child_size,
        child_overlap=config.child_overlap,
        parent_max_chars=config.parent_max_chars,
    )
    if not sections:
        raise ValueError("the document produced no chunks after cleaning and masking")

    search_texts: list[str] = []
    for section in sections:
        options = _contextualizer_options(contextualizer, section.section_path)
        for child in section.children:
            try:
                contextual = contextualizer.contextualize(source_document, child, options)
            except Exception:
                # Contextualization improves retrieval; it is not
                # allowed to lose an otherwise good document. The raw
                # child remains a valid representation.
                logger.warning(
                    "contextualization failed for %s; using the raw child",
                    source_document.source_uri,
                    exc_info=True,
                )
                contextual = ""
            search_texts.append(_compose_search_text(contextual, child))

    return _Prepared(
        doc_type=doc_type,
        sections=sections,
        search_texts=search_texts,
        masked_counts=masked.counts,
        content_hash=hashlib.sha256(masked.text.encode("utf-8")).hexdigest(),
    )


def _contextualizer_options(contextualizer: Contextualizer, section_path: str) -> BaseModel | None:
    """Give the contextualizer its section path when it asks for one.

    The stage contract allows arbitrary implementations. Passing an
    options model the implementation did not define would bind an
    unrelated class, so the check is on the declared model's fields.
    """
    model = contextualizer.options_model
    if "section_path" in model.model_fields:
        return model(section_path=section_path)
    return None


def _compose_search_text(contextual: str, child: str) -> str:
    """Prepend context without ever duplicating the child.

    An LLM contextualizer returns a situating sentence, while the
    offline section-path implementation returns ``path + child``. Both
    are valid representations; the child is appended only when the
    contextual text does not already end with it.
    """
    context = contextual.strip()
    if not context:
        return child
    if context.endswith(child.strip()):
        return context
    return f"{context}\n\n{child}"


async def _existing_run_document(
    db: AsyncSession, project: GovProject, config: IngestConfig
) -> Document | None:
    """The row this exact pipeline run already staged, if any."""
    if config.pipeline_run_id is None:
        return None
    return await db.scalar(
        select(Document).where(
            Document.logical_id == config.logical_id,
            Document.collection_id == project.collection_id,
            Document.pipeline_run_id == config.pipeline_run_id,
        )
    )


async def _next_version(db: AsyncSession, project: GovProject, config: IngestConfig) -> int:
    latest = await db.scalar(
        select(func.max(Document.version)).where(
            Document.logical_id == config.logical_id,
            Document.collection_id == project.collection_id,
        )
    )
    return int(latest or 0) + 1


def _document_id(collection_id: str, logical_id: str, version: int) -> str:
    """Stable id per staged version, scoped by collection.

    Including the version is what lets two staged versions coexist
    until publishing. Including the collection keeps the same logical
    id in two projects from colliding on the primary key.
    """
    digest = hashlib.sha256()
    digest.update(f"{collection_id}|{logical_id}|v{version}".encode())
    return digest.hexdigest()[:32]


def _assign_document_fields(
    document: Document,
    *,
    project: GovProject,
    source_document: SourceDocument,
    config: IngestConfig,
    embedder: Embedder,
    prepared: _Prepared,
    version: int,
) -> None:
    document.title = source_document.title or source_document.source_uri
    document.source_uri = source_document.source_uri
    document.mime_type = source_document.mime_type
    document.chunker_id = PARENT_CHILD_CHUNKER
    document.chunker_config = {
        "name": PARENT_CHILD_CHUNKER,
        "version": "1",
        "child_size": config.child_size,
        "child_overlap": config.child_overlap,
        "parent_max_chars": config.parent_max_chars,
        "doc_type": prepared.doc_type,
    }
    # Governance retrieval filters embeddings by ``embedder_version``;
    # the model identity is the durable fact, not the registry alias.
    document.embedder_id = embedder.id
    document.dim = embedder.dim
    document.version = version
    document.status = "indexed"
    document.failure_reason = None
    document.chunk_count = len(prepared.search_texts)

    document.logical_id = config.logical_id
    document.classification = config.classification
    document.collection_id = project.collection_id
    document.metadata_json = {
        **source_document.metadata,
        "doc_type": prepared.doc_type,
        "masked_counts": prepared.masked_counts,
    }
    document.published = False
    document.pipeline_run_id = config.pipeline_run_id
    source_updated_at = source_document.metadata.get("source_updated_at")
    document.source_updated_at = (
        source_updated_at if isinstance(source_updated_at, datetime) else None
    )
    document.content_hash = prepared.content_hash
    document.deleted_at = None


def _build_rows(
    *,
    document_id: str,
    version: int,
    embedder: Embedder,
    prepared: _Prepared,
    vectors: list[list[float]],
) -> tuple[list[ChunkParent], list[Chunk], list[ChunkEmbedding]]:
    """Parent, child and embedding rows in one deterministic order."""
    parent_rows: list[ChunkParent] = []
    chunk_rows: list[Chunk] = []
    embedding_rows: list[ChunkEmbedding] = []
    chunk_ordinal = 0

    for parent_ordinal, section in enumerate(prepared.sections):
        parent_id = hashlib.sha256(
            f"{document_id}|{parent_ordinal}|{section.text}".encode()
        ).hexdigest()[:32]
        parent_rows.append(
            ChunkParent(
                id=parent_id,
                document_id=document_id,
                ordinal=parent_ordinal,
                text=section.text,
                metadata_json={"section_path": section.section_path},
            )
        )
        for child in section.children:
            search_text = prepared.search_texts[chunk_ordinal]
            chunk_id = make_chunk_id(document_id, str(version), chunk_ordinal, search_text)
            chunk_rows.append(
                Chunk(
                    id=chunk_id,
                    document_id=document_id,
                    ordinal=chunk_ordinal,
                    text=child,
                    search_text=search_text,
                    token_count=embedder.estimate_tokens(search_text),
                    metadata_json={
                        "section_path": section.section_path,
                        "parent_ordinal": parent_ordinal,
                    },
                    parent_id=parent_id,
                )
            )
            embedding_rows.append(
                ChunkEmbedding(
                    chunk_id=chunk_id,
                    embedder_version=embedder.id,
                    embedding=vectors[chunk_ordinal],
                    dim=embedder.dim,
                )
            )
            chunk_ordinal += 1

    if chunk_ordinal != len(prepared.search_texts):
        raise RuntimeError("prepared search texts and section children are out of sync")
    return parent_rows, chunk_rows, embedding_rows


async def _delete_staged_rows(db: AsyncSession, document_id: str) -> None:
    """Replace this run's previous output, in FK-safe order."""
    await db.execute(
        delete(ChunkEmbedding).where(
            ChunkEmbedding.chunk_id.in_(select(Chunk.id).where(Chunk.document_id == document_id))
        )
    )
    await db.execute(delete(Chunk).where(Chunk.document_id == document_id))
    await db.execute(delete(ChunkParent).where(ChunkParent.document_id == document_id))
