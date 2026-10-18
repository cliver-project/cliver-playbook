"""Document upload and indexing endpoints (the ingestion surface).

The ingestion flow is split in two on purpose. ``POST /upload`` runs the
chunker and persists the resulting chunks with ``status="pending"``; the
response carries a preview so the web UI can show the user what the
chosen chunker produced. ``POST /{id}/index`` then runs the embedder over
those chunks and flips the document to ``status="indexed"``. Splitting
the stages lets the user change the embedder after seeing the chunks,
and keeps the (potentially slow, model-loading) embedding step out of
the request that receives the file.

Every chunk id is a content hash (see ``chunking.base.make_chunk_id``)
and document ids hash the source name plus the file content, so
re-uploading the same file targets the same document row and re-indexing
never duplicates rows.

Auth: both endpoints require ``rag:documents:write``. The permission
check runs before the handler, so an unauthenticated caller never
reaches the file parser.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import mimetypes
import os
from typing import Any

from fastapi import APIRouter, Depends, File, Form, HTTPException, Security, UploadFile
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from cliver_playbook.app.basic.db.session import get_db
from cliver_playbook.app.rag.audit import write_rag_audit
from cliver_playbook.app.rag.chunking import Document as SourceDocument
from cliver_playbook.app.rag.chunking import get_chunker
from cliver_playbook.app.rag.chunking.pdf import EmptyDocumentError
from cliver_playbook.app.rag.embedding import get_embedder
from cliver_playbook.app.rag.models.entities import Chunk as ChunkRow
from cliver_playbook.app.rag.models.entities import ChunkEmbedding, Document
from cliver_playbook.app.rag.schemas.documents import (
    ChunkList,
    ChunkRead,
    DocumentList,
    DocumentRead,
)
from cliver_playbook.app.rag.services import documents as document_service
from cliver_playbook.app.rag.settings import settings
from cliver_playbook.app.user.auth.dependencies import Viewer, require_perm

logger = logging.getLogger("cliver_playbook.app.rag.api.documents")

router = APIRouter(prefix="/api/v1/rag/documents", tags=["rag-documents"])

# Built once at import: require_perm validates the code against the live
# permission catalog when the dependency factory is called, so an import
# with a typo fails loudly instead of 403-ing every request at runtime.
_WRITE = Security(require_perm("rag:documents:write"))
_READ = Security(require_perm("rag:documents:read"))

# How many chunks the upload response carries. The full set is in the
# database behind GET /{id}/chunks; the preview is for the UI only.
_PREVIEW_LIMIT = 50


def _document_id_for(source_uri: str, content: bytes) -> str:
    """Stable id for (source name, file bytes).

    Hashing both means the same content uploaded under the same name
    resolves to the same row (re-upload bumps the version), while the
    same bytes under a different name stay distinct documents.
    """
    digest = hashlib.sha256()
    digest.update(source_uri.encode("utf-8"))
    digest.update(b"|")
    digest.update(hashlib.sha256(content).digest())
    return digest.hexdigest()[:32]


def _clean_filename(name: str | None) -> str:
    """Reduce a client-supplied filename to its last path component."""
    return os.path.basename(name) if name else "upload"


def _resolve_mime(content_type: str | None, filename: str) -> str:
    """Prefer the declared upload type; fall back to the file extension."""
    if content_type and content_type != "application/octet-stream":
        return content_type
    guessed, _ = mimetypes.guess_type(filename)
    return guessed or "application/octet-stream"


def _validate_sizes(chunk_size: int, chunk_overlap: int) -> None:
    """Reject sizes that would make the splitter loop or divide by zero."""
    if chunk_size <= 0:
        raise HTTPException(status_code=422, detail="chunk_size must be positive")
    if chunk_overlap < 0 or chunk_overlap >= chunk_size:
        raise HTTPException(
            status_code=422,
            detail="chunk_overlap must be >= 0 and smaller than chunk_size",
        )


async def _delete_chunks(db: AsyncSession, document_id: str) -> None:
    """Remove a document's chunks and embeddings (children first).

    The database also declares ON DELETE CASCADE, but SQLite does not
    enforce foreign keys by default, and the in-memory unit-test engine
    would otherwise keep orphan embeddings. Explicit deletes behave the
    same on both engines.
    """
    await db.execute(
        delete(ChunkEmbedding).where(
            ChunkEmbedding.chunk_id.in_(
                select(ChunkRow.id).where(ChunkRow.document_id == document_id)
            )
        )
    )
    await db.execute(delete(ChunkRow).where(ChunkRow.document_id == document_id))


async def _persist_failed_upload(
    db: AsyncSession,
    *,
    document_id: str,
    title: str,
    source_uri: str,
    mime_type: str,
    chunker_name: str,
    embedder_name: str,
    dim: int,
    reason: str,
) -> None:
    """Record a rejected upload as a ``failed`` document row.

    The row is what the web UI lists, so a user can see that a scan was
    rejected and why. Old chunks from a previous version are dropped:
    the document no longer describes the current content.
    """
    doc = await db.get(Document, document_id)
    if doc is None:
        doc = Document(id=document_id)
        db.add(doc)
    else:
        await _delete_chunks(db, document_id)
    doc.title = title
    doc.source_uri = source_uri
    doc.mime_type = mime_type
    doc.chunker_id = chunker_name
    doc.embedder_id = embedder_name
    doc.dim = dim
    doc.status = "failed"
    doc.failure_reason = reason
    doc.chunk_count = 0
    await db.commit()


@router.post("/upload", status_code=201)
async def upload_document(
    file: UploadFile = File(...),
    chunker: str | None = Form(None),
    embedder: str | None = Form(None),
    chunk_size: int | None = Form(None),
    chunk_overlap: int | None = Form(None),
    title: str | None = Form(None),
    db: AsyncSession = Depends(get_db),
    _viewer: Viewer = _WRITE,
) -> dict[str, Any]:
    """Chunk an uploaded file and persist the chunks for preview.

    Form fields (all optional; omissions fall back to the layered RAG
    settings): ``chunker``, ``embedder``, ``chunk_size``,
    ``chunk_overlap``, ``title``. Returns the document id plus up to
    ``_PREVIEW_LIMIT`` chunks so the UI can render the preview.
    """
    content = await file.read()
    if not content:
        raise HTTPException(status_code=422, detail="empty file: the upload contains 0 bytes")

    filename = _clean_filename(file.filename)
    source_uri = filename
    mime_type = _resolve_mime(file.content_type, filename)

    chunker_name = chunker or settings.rag.chunker
    embedder_name = embedder or settings.rag.embedder
    size = chunk_size if chunk_size is not None else settings.rag.chunk_size
    overlap = chunk_overlap if chunk_overlap is not None else settings.rag.chunk_overlap
    _validate_sizes(size, overlap)

    try:
        chunker_impl = get_chunker(chunker_name)
    except KeyError:
        raise HTTPException(status_code=422, detail=f"unknown chunker: {chunker_name!r}") from None
    try:
        embedder_impl = get_embedder(embedder_name)
    except KeyError:
        raise HTTPException(
            status_code=422, detail=f"unknown embedder: {embedder_name!r}"
        ) from None

    document_id = _document_id_for(source_uri, content)
    existing = await db.get(Document, document_id)
    version = existing.version + 1 if existing is not None else 1

    source_doc = SourceDocument(
        id=document_id,
        source_version=f"v{version}",
        mime_type=mime_type,
        raw=content,
        metadata={"filename": filename},
    )
    try:
        # Chunking may parse a PDF or run a splitter — CPU work that must
        # not block the event loop while other requests are served.
        chunks = await asyncio.to_thread(
            chunker_impl.split,
            source_doc,
            chunk_size=size,
            chunk_overlap=overlap,
        )
        if not chunks:
            raise EmptyDocumentError("the chunker produced no chunks")
    except EmptyDocumentError as exc:
        await _persist_failed_upload(
            db,
            document_id=document_id,
            title=title or filename,
            source_uri=source_uri,
            mime_type=mime_type,
            chunker_name=chunker_name,
            embedder_name=embedder_name,
            dim=embedder_impl.dim,
            reason="empty_after_parse",
        )
        await write_rag_audit(
            event="document.upload",
            target=document_id,
            ok=False,
            args={"chunker": chunker_name, "embedder": embedder_name},
            extra={"error": "empty_after_parse"},
        )
        raise HTTPException(status_code=422, detail=str(exc)) from None
    # A parser failure is user-visible (422 + a failed row), not a crash;
    # catching broadly here also covers third-party parser exceptions.
    except Exception:
        logger.exception("chunking failed for document_id=%s", document_id)
        await _persist_failed_upload(
            db,
            document_id=document_id,
            title=title or filename,
            source_uri=source_uri,
            mime_type=mime_type,
            chunker_name=chunker_name,
            embedder_name=embedder_name,
            dim=embedder_impl.dim,
            reason="chunking_failed",
        )
        await write_rag_audit(
            event="document.upload",
            target=document_id,
            ok=False,
            args={"chunker": chunker_name, "embedder": embedder_name},
            extra={"error": "chunking_failed"},
        )
        raise HTTPException(status_code=422, detail="chunking failed") from None

    # The new content replaces whatever the previous version produced.
    if existing is not None:
        await _delete_chunks(db, document_id)
    else:
        existing = Document(id=document_id)
        db.add(existing)

    existing.title = title or filename
    existing.source_uri = source_uri
    existing.mime_type = mime_type
    existing.chunker_id = chunker_name
    existing.embedder_id = embedder_name
    existing.dim = embedder_impl.dim
    existing.version = version
    existing.status = "pending"
    existing.failure_reason = None
    existing.chunk_count = len(chunks)

    chunk_rows = [
        ChunkRow(
            id=chunk.id,
            document_id=document_id,
            ordinal=ordinal,
            text=chunk.text,
            token_count=embedder_impl.estimate_tokens(chunk.text),
            metadata_json={
                **chunk.metadata,
                "source_offset": chunk.source_offset.model_dump(),
            },
            parent_id=chunk.parent_id,
        )
        for ordinal, chunk in enumerate(chunks)
    ]
    db.add_all(chunk_rows)
    await db.commit()

    await write_rag_audit(
        event="document.upload",
        target=document_id,
        ok=True,
        args={"chunker": chunker_name, "embedder": embedder_name},
        extra={"chunk_count": len(chunks)},
    )

    preview = [
        {
            "ordinal": row.ordinal,
            "text": row.text,
            "token_count": row.token_count,
            "chunk_id_prefix": row.id[:8],
        }
        for row in chunk_rows[:_PREVIEW_LIMIT]
    ]
    return {
        "document_id": document_id,
        "title": existing.title,
        "status": existing.status,
        "chunker": chunker_name,
        "embedder": embedder_name,
        "dim": embedder_impl.dim,
        "version": version,
        "chunk_count": len(chunk_rows),
        "preview_truncated": len(chunk_rows) > len(preview),
        "preview_chunks": preview,
    }


@router.post("/{document_id}/index", status_code=200)
async def index_document(
    document_id: str,
    db: AsyncSession = Depends(get_db),
    _viewer: Viewer = _WRITE,
) -> dict[str, Any]:
    """Embed a pending document's chunks and mark it searchable.

    Idempotent: a document already marked ``indexed`` returns its
    current counters without re-embedding. Any previous embedding rows
    are replaced, so retrying a failed index starts clean.
    """
    doc = await db.get(Document, document_id)
    if doc is None:
        raise HTTPException(status_code=404, detail="document not found")

    if doc.status == "indexed":
        return {
            "document_id": doc.id,
            "status": doc.status,
            "chunk_count": doc.chunk_count,
            "dim": doc.dim,
        }

    try:
        embedder_impl = get_embedder(doc.embedder_id)
    except KeyError:
        doc.status = "failed"
        doc.failure_reason = "unknown_embedder"
        await db.commit()
        raise HTTPException(
            status_code=422,
            detail=f"unknown embedder: {doc.embedder_id!r}",
        ) from None

    rows = (
        (
            await db.execute(
                select(ChunkRow)
                .where(ChunkRow.document_id == document_id)
                .order_by(ChunkRow.ordinal)
            )
        )
        .scalars()
        .all()
    )
    if not rows:
        doc.status = "failed"
        doc.failure_reason = "no_chunks"
        await db.commit()
        raise HTTPException(status_code=422, detail="document has no chunks to index")

    try:
        vectors = await asyncio.to_thread(
            embedder_impl.embed,
            [row.text for row in rows],
            mode="document",
        )
    # Model loading and inference fail in many third-party ways; mark the
    # document failed and surface a stable 500 instead of letting the
    # exception shape leak into the API contract.
    except Exception:
        logger.exception("embedding failed for document_id=%s", document_id)
        doc.status = "failed"
        doc.failure_reason = "embedding_failed"
        await db.commit()
        await write_rag_audit(
            event="document.index",
            target=document_id,
            ok=False,
            args={"embedder": doc.embedder_id},
            extra={"error": "embedding_failed"},
        )
        raise HTTPException(
            status_code=500, detail="indexing failed: the embedder errored"
        ) from None

    # Replacing rather than merging keeps a retried index clean and
    # makes the operation idempotent even if a previous attempt wrote a
    # partial set of embeddings.
    await _delete_chunks_embeddings(db, document_id)
    db.add_all(
        [
            ChunkEmbedding(
                chunk_id=row.id,
                embedding=vector,
                dim=embedder_impl.dim,
                embedder_version=embedder_impl.id,
            )
            for row, vector in zip(rows, vectors, strict=True)
        ]
    )
    doc.status = "indexed"
    doc.dim = embedder_impl.dim
    doc.failure_reason = None
    await db.commit()

    await write_rag_audit(
        event="document.index",
        target=document_id,
        ok=True,
        args={"embedder": doc.embedder_id},
        extra={"chunk_count": len(rows), "embedder_version": embedder_impl.id},
    )
    return {
        "document_id": doc.id,
        "status": doc.status,
        "chunk_count": len(rows),
        "dim": doc.dim,
        "embedder_version": embedder_impl.id,
    }


@router.get("", response_model=DocumentList)
async def list_documents(
    db: AsyncSession = Depends(get_db),
    _viewer: Viewer = _READ,
) -> DocumentList:
    """Every document in the shared knowledge base, newest first."""
    rows = await document_service.list_documents(db)
    return DocumentList(items=[DocumentRead.model_validate(row) for row in rows])


@router.get("/{document_id}", response_model=DocumentRead)
async def get_document(
    document_id: str,
    db: AsyncSession = Depends(get_db),
    _viewer: Viewer = _READ,
) -> DocumentRead:
    """One document's metadata (status, stage choices, counters)."""
    doc = await document_service.get_document(db, document_id)
    if doc is None:
        raise HTTPException(status_code=404, detail="document not found")
    return DocumentRead.model_validate(doc)


@router.get("/{document_id}/chunks", response_model=ChunkList)
async def get_document_chunks(
    document_id: str,
    db: AsyncSession = Depends(get_db),
    _viewer: Viewer = _READ,
) -> ChunkList:
    """A document's chunks in ordinal order, with their metadata."""
    doc = await document_service.get_document(db, document_id)
    if doc is None:
        raise HTTPException(status_code=404, detail="document not found")
    rows = await document_service.list_chunks(db, document_id)
    return ChunkList(
        items=[
            ChunkRead(
                id=row.id,
                ordinal=row.ordinal,
                text=row.text,
                token_count=row.token_count,
                metadata=row.metadata_json or {},
                parent_id=row.parent_id,
            )
            for row in rows
        ]
    )


async def _delete_chunks_embeddings(db: AsyncSession, document_id: str) -> None:
    """Drop only the embedding rows for a document's chunks."""
    await db.execute(
        delete(ChunkEmbedding).where(
            ChunkEmbedding.chunk_id.in_(
                select(ChunkRow.id).where(ChunkRow.document_id == document_id)
            )
        )
    )
