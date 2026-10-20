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

A chunker may expose format-specific, output-shaping options (Word
heading handling, table rendering, HTML boilerplate removal, ...). The
upload accepts them as a JSON object in ``chunker_options``, validates
them against the selected chunker's ``options_model``, and stores the
resolved configuration on the document together with the chunker
version and size budget. The configuration is therefore always
inspectable and travels with the chunks it produced.

Failure semantics: rejecting a re-upload never destroys the previous
version. Only a document that did not exist before gets a ``failed``
row; an existing (possibly indexed and searchable) document is left
untouched, and the failure is recorded in the audit log instead.

Indexing accepts an embedder override so the user can change the model
after reviewing the chunk preview. Re-indexing an already-indexed
document with a different embedder (or with ``force=true``) replaces
the stored vectors; the embeddings' ``embedder_version`` and the
document's ``embedder_id`` always describe the same model, which is
what makes the query-time embedder filter sound.

Auth: every endpoint requires ``rag:documents:write`` except the read
routes, which require ``rag:documents:read``. The permission check runs
before the handler, so an unauthenticated caller never reaches the file
parser.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import mimetypes
import os
from typing import Any

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, Security, UploadFile
from pydantic import BaseModel, ValidationError
from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from cliver_playbook.app.basic.db.session import get_db
from cliver_playbook.app.rag.audit import fingerprint, write_rag_audit
from cliver_playbook.app.rag.chunking import Document as SourceDocument
from cliver_playbook.app.rag.chunking import get_chunker
from cliver_playbook.app.rag.chunking.base import (
    ChunkerInputError,
    ChunkerOptionError,
    EmptyDocumentError,
)
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

# Column widths. Validating at the boundary keeps a client-supplied
# title or filename from failing inside the database with a driver
# error (which would surface as an opaque 500).
_MAX_TITLE = 512
_MAX_SOURCE_URI = 1024
_MAX_MIME = 128

# Bound on the JSON chunker-options form field. Options are flat primitive
# settings, so a few kilobytes is generous; the cap keeps a hostile value
# from turning into a large audit row or an unbounded Pydantic error list.
_MAX_CHUNKER_OPTIONS = 4096


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


def _validate_text_fields(filename: str, title: str, mime_type: str) -> None:
    """Reject values wider than the columns they are stored in."""
    if len(filename) > _MAX_SOURCE_URI:
        raise HTTPException(status_code=422, detail="filename is too long")
    if len(title) > _MAX_TITLE:
        raise HTTPException(status_code=422, detail="title is too long")
    if len(mime_type) > _MAX_MIME:
        raise HTTPException(status_code=422, detail="mime type is too long")


def _parse_chunker_options(raw: str | None, chunker_impl: Any) -> BaseModel | None:
    """Validate the JSON ``chunker_options`` form field.

    Returns the resolved options object with defaults applied, so the
    caller can pass exactly what it persists to the chunker. A chunker
    written against an older contract may not declare ``options_model``;
    such chunkers keep working when the field is absent and are rejected
    only when the client actually sends options.

    Validation errors use FastAPI's structured detail shape
    (``{"loc": [...], "msg": ..., "type": ...}``) so the web client can
    render the offending field name instead of an opaque 422.
    """
    options_model = getattr(chunker_impl, "options_model", None)
    if raw is None or not raw.strip():
        return options_model() if options_model is not None else None
    if options_model is None:
        raise HTTPException(
            status_code=422,
            detail="this chunker does not accept options",
        )
    if len(raw.encode("utf-8")) > _MAX_CHUNKER_OPTIONS:
        raise HTTPException(
            status_code=422,
            detail=f"chunker_options must be at most {_MAX_CHUNKER_OPTIONS} bytes",
        )
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise HTTPException(
            status_code=422,
            detail=f"chunker_options must be valid JSON: {exc.msg}",
        ) from None
    if not isinstance(payload, dict):
        raise HTTPException(status_code=422, detail="chunker_options must be a JSON object")
    try:
        return options_model.model_validate(payload)
    except ValidationError as exc:
        detail = [
            {
                "loc": [
                    "body",
                    "chunker_options",
                    *(str(part) for part in error["loc"]),
                ],
                "msg": error["msg"],
                "type": error["type"],
            }
            for error in exc.errors()
        ]
        raise HTTPException(status_code=422, detail=detail) from None


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
    chunker_config: dict[str, Any],
    embedder_name: str,
    dim: int,
    reason: str,
) -> None:
    """Record a rejected upload as a ``failed`` document row.

    The row is what the web UI lists, so a user can see that a scan was
    rejected and why. Only a genuinely new document gets a row: when
    the id already exists, the previous version (chunks, embeddings and
    ``indexed`` status) is preserved intact — a bad re-upload must not
    silently remove a document that is still searchable. The failure is
    never lost, because the endpoint audits it either way.
    """
    doc = await db.get(Document, document_id)
    if doc is not None:
        return
    doc = Document(id=document_id)
    db.add(doc)
    doc.title = title
    doc.source_uri = source_uri
    doc.mime_type = mime_type
    doc.chunker_id = chunker_name
    doc.chunker_config = chunker_config
    doc.embedder_id = embedder_name
    doc.dim = dim
    doc.status = "failed"
    doc.failure_reason = reason
    doc.chunk_count = 0
    await db.commit()


@router.post("/upload", status_code=201)
async def upload_document(
    request: Request,
    file: UploadFile = File(...),
    chunker: str | None = Form(None),
    embedder: str | None = Form(None),
    chunk_size: int | None = Form(None),
    chunk_overlap: int | None = Form(None),
    chunker_options: str | None = Form(None),
    title: str | None = Form(None),
    db: AsyncSession = Depends(get_db),
    viewer: Viewer = _WRITE,
) -> dict[str, Any]:
    """Chunk an uploaded file and persist the chunks for preview.

    Form fields (all optional; omissions fall back to the layered RAG
    settings): ``chunker``, ``embedder``, ``chunk_size``,
    ``chunk_overlap``, ``chunker_options``, ``title``. Returns the
    document id, the effective chunker configuration and up to
    ``_PREVIEW_LIMIT`` chunks so the UI can render the preview.

    ``chunker_options`` is a JSON object validated against the selected
    chunker's ``options_model``. The resolved object (including defaults)
    is persisted in ``Document.chunker_config`` together with the size
    budget and chunker version, so the configuration behind the current
    chunks is always inspectable.
    """
    filename = _clean_filename(file.filename)
    # Read one byte past the cap: anything at or below it is a valid
    # upload, and anything above is rejected without buffering the
    # whole body. The bound exists so a hostile or accidental huge file
    # cannot exhaust memory or feed an unbounded blob to the parser.
    max_bytes = settings.rag.max_upload_bytes
    content = await file.read(max_bytes + 1)
    if len(content) > max_bytes:
        await write_rag_audit(
            event="document.upload",
            target=fingerprint(filename),
            ok=False,
            extra={"error": "file_too_large", "max_upload_bytes": max_bytes},
            viewer=viewer,
            request=request,
        )
        raise HTTPException(
            status_code=413,
            detail=f"file too large: the limit is {max_bytes} bytes",
        )
    if not content:
        raise HTTPException(status_code=422, detail="empty file: the upload contains 0 bytes")

    source_uri = filename
    mime_type = _resolve_mime(file.content_type, filename)
    title_value = title or filename
    _validate_text_fields(filename, title_value, mime_type)

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

    try:
        options = _parse_chunker_options(chunker_options, chunker_impl)
    except HTTPException:
        # Invalid options are a client mistake, not a property of the
        # file: reject them without creating a failed document row. The
        # audit still records the attempt.
        await write_rag_audit(
            event="document.upload",
            target=document_id,
            ok=False,
            args={"chunker": chunker_name, "embedder": embedder_name},
            extra={"error": "invalid_chunker_options"},
            viewer=viewer,
            request=request,
        )
        raise

    chunker_config = {
        "version": getattr(chunker_impl, "version", None),
        "chunk_size": size,
        "chunk_overlap": overlap,
        "options": options.model_dump(mode="json") if options is not None else {},
    }
    split_kwargs: dict[str, Any] = {"chunk_size": size, "chunk_overlap": overlap}
    if options is not None:
        # Chunkers written before the options contract do not accept the
        # keyword at all; omitting it keeps them usable.
        split_kwargs["options"] = options

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
            **split_kwargs,
        )
        if not chunks:
            raise EmptyDocumentError("the chunker produced no chunks")
    except EmptyDocumentError as exc:
        await _persist_failed_upload(
            db,
            document_id=document_id,
            title=title_value,
            source_uri=source_uri,
            mime_type=mime_type,
            chunker_name=chunker_name,
            chunker_config=chunker_config,
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
            viewer=viewer,
            request=request,
        )
        raise HTTPException(status_code=422, detail=str(exc)) from None
    except ChunkerOptionError as exc:
        # The file may be fine; an option such as a CSS selector was not.
        # No failed row: the live document (if any) stays untouched and
        # the client can correct the option and retry.
        await write_rag_audit(
            event="document.upload",
            target=document_id,
            ok=False,
            args={"chunker": chunker_name, "embedder": embedder_name},
            extra={"error": "invalid_chunker_options", "detail": str(exc)},
            viewer=viewer,
            request=request,
        )
        raise HTTPException(status_code=422, detail=str(exc)) from None
    except ChunkerInputError as exc:
        # The parser recognized the format but the input is unusable
        # (for example a legacy .doc). Record the rejection on a new row
        # and return the parser's specific, actionable message.
        await _persist_failed_upload(
            db,
            document_id=document_id,
            title=title_value,
            source_uri=source_uri,
            mime_type=mime_type,
            chunker_name=chunker_name,
            chunker_config=chunker_config,
            embedder_name=embedder_name,
            dim=embedder_impl.dim,
            reason="chunking_failed",
        )
        await write_rag_audit(
            event="document.upload",
            target=document_id,
            ok=False,
            args={"chunker": chunker_name, "embedder": embedder_name},
            extra={"error": "invalid_chunker_input", "detail": str(exc)},
            viewer=viewer,
            request=request,
        )
        raise HTTPException(status_code=422, detail=str(exc)) from None
    # A parser failure is user-visible (422 + a failed row), not a crash;
    # catching broadly here also covers third-party parser exceptions.
    except Exception:
        logger.exception("chunking failed for document_id=%s", document_id)
        await _persist_failed_upload(
            db,
            document_id=document_id,
            title=title_value,
            source_uri=source_uri,
            mime_type=mime_type,
            chunker_name=chunker_name,
            chunker_config=chunker_config,
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
            viewer=viewer,
            request=request,
        )
        raise HTTPException(status_code=422, detail="chunking failed") from None

    # The new content replaces whatever the previous version produced.
    if existing is not None:
        await _delete_chunks(db, document_id)
    else:
        existing = Document(id=document_id)
        db.add(existing)

    existing.title = title_value
    existing.source_uri = source_uri
    existing.mime_type = mime_type
    existing.chunker_id = chunker_name
    existing.chunker_config = chunker_config
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
    # The document id is derived from (name, content), so two requests
    # for the same file can race on the primary key. One of them wins;
    # the other gets a stable 409 instead of a driver-level 500.
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        logger.warning("concurrent upload for document_id=%s", document_id)
        await write_rag_audit(
            event="document.upload",
            target=document_id,
            ok=False,
            args={"chunker": chunker_name, "embedder": embedder_name},
            extra={"error": "concurrent_upload"},
            viewer=viewer,
            request=request,
        )
        raise HTTPException(
            status_code=409,
            detail="a concurrent upload of the same document is in progress; retry",
        ) from None

    await write_rag_audit(
        event="document.upload",
        target=document_id,
        ok=True,
        args={"chunker": chunker_name, "embedder": embedder_name},
        extra={
            "chunk_count": len(chunks),
            "version": version,
            "chunker_config": chunker_config,
        },
        viewer=viewer,
        request=request,
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
        "chunker_config": chunker_config,
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
    request: Request,
    embedder: str | None = None,
    force: bool = False,
    db: AsyncSession = Depends(get_db),
    viewer: Viewer = _WRITE,
) -> dict[str, Any]:
    """Embed a document's chunks and mark it searchable.

    ``embedder`` overrides the model recorded at upload time, which is
    how the UI lets the user change the embedder after reviewing the
    chunk preview. Re-indexing an already-indexed document is
    idempotent when the embedder is unchanged; a different embedder (or
    ``force=true``) re-embeds and replaces the stored vectors. Any
    previous embedding rows are always replaced, so a retried index
    starts clean.
    """
    doc = await db.get(Document, document_id)
    if doc is None:
        raise HTTPException(status_code=404, detail="document not found")

    target_embedder_name = embedder or doc.embedder_id
    try:
        embedder_impl = get_embedder(target_embedder_name)
    except KeyError:
        # An override is pure client input: rejecting it must not
        # corrupt the document. Only the document's own recorded name
        # being unknown is a persistent data problem worth flagging.
        if embedder is None:
            doc.status = "failed"
            doc.failure_reason = "unknown_embedder"
            await db.commit()
        raise HTTPException(
            status_code=422,
            detail=f"unknown embedder: {target_embedder_name!r}",
        ) from None

    already_indexed = doc.status == "indexed" and target_embedder_name == doc.embedder_id
    if already_indexed and not force:
        return {
            "document_id": doc.id,
            "status": doc.status,
            "chunk_count": doc.chunk_count,
            "dim": doc.dim,
            "embedder": doc.embedder_id,
            "embedder_version": embedder_impl.id,
        }

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
            args={"embedder": target_embedder_name},
            extra={"error": "embedding_failed"},
            viewer=viewer,
            request=request,
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
    # The document row and the embedding rows must agree on the model:
    # retrieval filters by ``embedder_version``, and the catalog reads
    # ``embedder_id`` to tell the chat page which query embedder to use.
    doc.embedder_id = target_embedder_name
    doc.status = "indexed"
    doc.dim = embedder_impl.dim
    doc.failure_reason = None
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        logger.warning("concurrent index for document_id=%s", document_id)
        await write_rag_audit(
            event="document.index",
            target=document_id,
            ok=False,
            args={"embedder": target_embedder_name},
            extra={"error": "concurrent_index"},
            viewer=viewer,
            request=request,
        )
        raise HTTPException(
            status_code=409,
            detail="a concurrent index of this document is in progress; retry",
        ) from None

    await write_rag_audit(
        event="document.index",
        target=document_id,
        ok=True,
        args={
            "embedder": target_embedder_name,
            "requested_embedder": embedder,
            "forced": force,
        },
        extra={"chunk_count": len(rows), "embedder_version": embedder_impl.id},
        viewer=viewer,
        request=request,
    )
    return {
        "document_id": doc.id,
        "status": doc.status,
        "chunk_count": len(rows),
        "dim": doc.dim,
        "embedder": doc.embedder_id,
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


@router.delete("/{document_id}", status_code=200)
async def delete_document(
    document_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
    viewer: Viewer = _WRITE,
) -> dict[str, Any]:
    """Remove a document together with its chunks and embeddings.

    Deletion is permanent and immediate: the next retrieval stops
    seeing the document (any in-flight query still holding a result
    list is unaffected). The audit row is the only remaining record,
    so it keeps the document's stage choices.
    """
    doc = await db.get(Document, document_id)
    if doc is None:
        raise HTTPException(status_code=404, detail="document not found")
    # Explicit child-first deletion behaves identically on Postgres
    # (where the foreign keys would cascade anyway) and on the SQLite
    # test engine (which does not enforce foreign keys by default).
    await _delete_chunks(db, document_id)
    await db.delete(doc)
    await db.commit()

    await write_rag_audit(
        event="document.delete",
        target=document_id,
        ok=True,
        args={"chunker": doc.chunker_id, "embedder": doc.embedder_id},
        viewer=viewer,
        request=request,
    )
    return {"document_id": document_id, "deleted": True}


async def _delete_chunks_embeddings(db: AsyncSession, document_id: str) -> None:
    """Drop only the embedding rows for a document's chunks."""
    await db.execute(
        delete(ChunkEmbedding).where(
            ChunkEmbedding.chunk_id.in_(
                select(ChunkRow.id).where(ChunkRow.document_id == document_id)
            )
        )
    )
