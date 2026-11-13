"""Scenario stages: the finance corpus's document taxonomy.

The built-in ``by-extension`` classifier calls every markdown file
``markdown``, but the finance rules scope retrieval by meaning
(``doc_type in ["policy", …]``). A real deployment classifies its corpus
on purpose; this scenario does it from the reference filenames, which are
stable and readable. Registering under a new name is the documented seam —
no built-in is patched.
"""

from __future__ import annotations

from typing import Any

from cliver_playbook.app.rag_governance.stages.base import SourceDocument

#: Filename fragment -> document type. First match wins; the order matters
#: (``fin-warning-policy`` is a policy even though ``warning`` is listed for
#: readability below). Everything unmatched is a policy document: the seed
#: corpus is governance material end to end.
_RULES: tuple[tuple[str, str], ...] = (
    ("catalog", "metric_definition"),
    ("monthly-report", "report"),
    ("compensation", "report"),
    ("policy", "policy"),
)


class FinanceDocTypeClassifier:
    name = "finance-doc-type"
    version = "1"

    def classify(self, document: SourceDocument, options: Any = None) -> str:
        filename = str(document.metadata.get("filename") or document.source_uri).lower()
        for fragment, doc_type in _RULES:
            if fragment in filename:
                return doc_type
        return "policy"


def register(classifier_registry: Any) -> None:
    """Idempotent registration, so repeated app builds are safe."""
    if FinanceDocTypeClassifier.name not in classifier_registry.names():
        classifier_registry.register(FinanceDocTypeClassifier.name, FinanceDocTypeClassifier)
