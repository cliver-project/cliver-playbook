"""Document-type classifiers: the first decision in the ingestion pipeline.

The document type selects the chunker and the contextualization mode,
so an unknown type must be explicit rather than silently treated as
plain text. Both offline classifiers return ``"unknown"`` when they
cannot classify; the pipeline can then choose a safe default and record
the fact in the document metadata.

``by-mime`` trusts the declared MIME type, ``by-extension`` the source
URI or filename. In production both are hints: a customer upload often
has ``application/octet-stream`` and a useful filename, or vice versa.
The LLM-assisted classifier (a later registration) is the fallback when
neither offline rule resolves the type.
"""

from __future__ import annotations

from pathlib import PurePosixPath

from pydantic import BaseModel, Field

from cliver_playbook.app.rag_governance.stages.base import SourceDocument

# The document types the reference scenario cares about. A project may
# override the map; the values are also the chunker-map keys in config.
_DEFAULT_MIME_MAP: dict[str, str] = {
    "text/markdown": "markdown",
    "text/x-markdown": "markdown",
    "text/plain": "text",
    "application/pdf": "pdf",
    "application/msword": "docx",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": "docx",
    "application/vnd.ms-excel": "xlsx",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": "xlsx",
    "application/json": "json",
    "text/csv": "csv",
    "text/html": "html",
}

_DEFAULT_EXTENSION_MAP: dict[str, str] = {
    ".md": "markdown",
    ".markdown": "markdown",
    ".txt": "text",
    ".pdf": "pdf",
    ".doc": "docx",
    ".docx": "docx",
    ".xls": "xlsx",
    ".xlsx": "xlsx",
    ".json": "json",
    ".csv": "csv",
    ".html": "html",
    ".htm": "html",
}


class MimeClassifierOptions(BaseModel):
    mapping: dict[str, str] = Field(default_factory=lambda: dict(_DEFAULT_MIME_MAP))


class ExtensionClassifierOptions(BaseModel):
    mapping: dict[str, str] = Field(default_factory=lambda: dict(_DEFAULT_EXTENSION_MAP))


class ByMimeClassifier:
    name = "by-mime"
    version = "1"
    options_model = MimeClassifierOptions

    def classify(self, document: SourceDocument, options: BaseModel | None = None) -> str:
        opts = options if isinstance(options, MimeClassifierOptions) else MimeClassifierOptions()
        mime = document.mime_type.split(";", 1)[0].strip().lower()
        return opts.mapping.get(mime, "unknown")


class ByExtensionClassifier:
    name = "by-extension"
    version = "1"
    options_model = ExtensionClassifierOptions

    def classify(self, document: SourceDocument, options: BaseModel | None = None) -> str:
        opts = (
            options
            if isinstance(options, ExtensionClassifierOptions)
            else ExtensionClassifierOptions()
        )
        filename = document.metadata.get("filename") or document.source_uri
        suffix = PurePosixPath(str(filename)).suffix.lower()
        return opts.mapping.get(suffix, "unknown")
