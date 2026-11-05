"""Contextualizers: the retrieval-side representation of a child chunk.

The contextual text is prepended to the short child and stored in
``rag_chunks.search_text``. It is never the generation context: the
generator receives the original parent section, so an LLM-written
prefix cannot become an unverifiable source.

``section-path`` is the offline implementation. It is deterministic and
cheap, and it recovers the single most useful context signal for a
structured document: where the chunk sits in the heading hierarchy.
An LLM contextualizer is a separate registration because it costs a
model call per child and its output must be reviewed as generated text.
"""

from __future__ import annotations

from pydantic import BaseModel

from cliver_playbook.app.rag_governance.stages.base import SourceDocument


class ContextualizerOptions(BaseModel):
    section_path: str = ""


class SectionPathContextualizer:
    name = "section-path"
    version = "1"
    options_model = ContextualizerOptions

    def contextualize(
        self,
        document: SourceDocument,
        chunk: str,
        options: BaseModel | None = None,
    ) -> str:
        opts = options if isinstance(options, ContextualizerOptions) else ContextualizerOptions()
        path = opts.section_path.strip()
        return f"{path}\n{chunk}" if path else chunk
