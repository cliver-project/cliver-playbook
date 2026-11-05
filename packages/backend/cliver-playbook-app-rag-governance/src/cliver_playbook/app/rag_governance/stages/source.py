"""Corpus sources: turn source configuration into ``SourceDocument`` values.

A source is deliberately synchronous and side-effect free apart from
reading its input. The pipeline runs ``fetch`` once per ingest batch;
connectors that need pagination or retries wrap that in a job, not in
the source itself.

``upload`` carries one document's bytes as base64 in its config. That
is pragmatic for tests and for a small reference deployment, but it is
not a durable home for customer bytes: the API layer spools an upload
to the configured staging directory and the connector reads it from
there. ``directory`` is the offline batch path: every ``.md``/``.txt``
file under a root becomes a document with a stable logical id derived
from its relative path.
"""

from __future__ import annotations

import base64
from collections.abc import Iterator
from pathlib import Path

from pydantic import BaseModel, Field

from cliver_playbook.app.rag_governance.stages.base import SourceDocument

_EXTENSION_MIME: dict[str, str] = {
    ".md": "text/markdown",
    ".markdown": "text/markdown",
    ".txt": "text/plain",
}


class UploadSourceOptions(BaseModel):
    """One document supplied as base64 content."""

    logical_id: str
    filename: str
    content_b64: str
    title: str = ""
    mime_type: str = "text/plain"


class UploadSource:
    name = "upload"
    version = "1"
    options_model = UploadSourceOptions

    def fetch(self, config: dict) -> Iterator[SourceDocument]:
        opts = UploadSourceOptions.model_validate(config)
        try:
            content = base64.b64decode(opts.content_b64, validate=True)
        except ValueError as exc:
            raise ValueError("upload source content_b64 is not valid base64") from exc
        yield SourceDocument(
            source_uri=opts.filename,
            title=opts.title or Path(opts.filename).stem,
            mime_type=opts.mime_type,
            content=content,
            metadata={"filename": opts.filename, "logical_id": opts.logical_id},
        )


class DirectorySourceOptions(BaseModel):
    """Every matching file under ``path``, in sorted order."""

    path: str
    extensions: list[str] = Field(default_factory=lambda: [".md", ".txt"])
    # Prefixing keeps ids globally unique when several directory
    # sources feed one collection (for example ``policy/`` and
    # ``metrics/``).
    logical_id_prefix: str = ""


class DirectorySource:
    name = "directory"
    version = "1"
    options_model = DirectorySourceOptions

    def fetch(self, config: dict) -> Iterator[SourceDocument]:
        opts = DirectorySourceOptions.model_validate(config)
        root = Path(opts.path).expanduser()
        if not root.is_dir():
            raise ValueError(f"directory source path is not a directory: {opts.path!r}")

        extensions = {extension.lower() for extension in opts.extensions}
        for path in sorted(
            candidate
            for candidate in root.rglob("*")
            if candidate.is_file() and candidate.suffix.lower() in extensions
        ):
            relative = path.relative_to(root)
            logical_id = f"{opts.logical_id_prefix}{relative.with_suffix('').as_posix()}"
            yield SourceDocument(
                source_uri=str(path),
                title=path.stem,
                mime_type=_EXTENSION_MIME.get(path.suffix.lower(), "text/plain"),
                content=path.read_bytes(),
                metadata={
                    "filename": path.name,
                    "relative_path": relative.as_posix(),
                    "logical_id": logical_id,
                },
            )
