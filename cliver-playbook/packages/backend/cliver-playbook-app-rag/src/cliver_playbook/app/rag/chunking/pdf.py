"""PDF layout-aware chunker.

Wraps ``unstructured.partition.pdf.partition_pdf`` with the "fast"
strategy (no OCR). Each element returned by the partitioner becomes
one chunk; its ``element_type`` ("Title", "NarrativeText", "ListItem",
"Table", ...) lands in the chunk's ``metadata``. If the partitioner
returns no elements (e.g. a scanned PDF with no extractable text
without OCR), the chunker raises ``EmptyDocumentError``; the upload
endpoint catches that and returns 422 with a clear reason.
"""

from __future__ import annotations

from cliver_playbook.app.rag.chunking.base import (
    Chunk,
    Document,
    SourceOffset,
    make_chunk_id,
)

VERSION = "1.0.0"


class EmptyDocumentError(ValueError):
    """The PDF produced no extractable elements.

    Surfaced by the upload endpoint as 422 ``no_extractable_text`` so
    the operator can re-upload a non-OCR-required version or run OCR
    upstream before re-trying.
    """


def _partition(pdf_bytes: bytes) -> list:
    """Thin wrapper around unstructured's partition_pdf, isolated so
    tests can mock it without pulling the heavy dependency."""
    from unstructured.partition.pdf import partition_pdf

    return partition_pdf(file=pdf_bytes, strategy="fast")


class PdfChunker:
    """PDF chunker using unstructured.io's fast strategy."""

    name = "pdf"
    version = VERSION

    def split(
        self,
        doc: Document,
        *,
        chunk_size: int = 512,
        chunk_overlap: int = 64,
    ) -> list[Chunk]:
        if not isinstance(doc.raw, bytes):
            raise TypeError("PdfChunker expects bytes in Document.raw")
        elements = _partition(doc.raw)
        if not elements:
            raise EmptyDocumentError("PDF produced no extractable text (likely an image-only scan)")
        chunks: list[Chunk] = []
        for ordinal, element in enumerate(elements):
            text = getattr(element, "text", "") or ""
            element_type = element.__class__.__name__ if element is not None else "Unknown"
            metadata = {
                **dict(doc.metadata),
                "element_type": element_type,
            }
            # Carry over page_number when unstructured surfaces it
            page_number = getattr(element.metadata, "page_number", None)  # type: ignore[union-attr]
            if page_number is not None:
                metadata["page_number"] = page_number
            chunks.append(
                Chunk(
                    id=make_chunk_id(doc.id, doc.source_version, ordinal, text),
                    text=text,
                    metadata=metadata,
                    parent_id=None,
                    source_offset=SourceOffset(start=0, end=len(text), unit="char"),
                )
            )
        return chunks
