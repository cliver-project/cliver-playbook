"""The built-in evaluators, one per metric in design §12.3."""

from cliver_playbook.app.rag_governance.evaluation.evaluators.access import (
    AccessLeakEvaluator,
)
from cliver_playbook.app.rag_governance.evaluation.evaluators.contextualization import (
    ContextualizationEvaluator,
)
from cliver_playbook.app.rag_governance.evaluation.evaluators.freshness import (
    FreshnessEvaluator,
)
from cliver_playbook.app.rag_governance.evaluation.evaluators.groundedness import (
    GroundednessEvaluator,
)
from cliver_playbook.app.rag_governance.evaluation.evaluators.intent import IntentEvaluator
from cliver_playbook.app.rag_governance.evaluation.evaluators.masking import (
    MaskingLeakEvaluator,
)
from cliver_playbook.app.rag_governance.evaluation.evaluators.retrieval import (
    RetrievalEvaluator,
)
from cliver_playbook.app.rag_governance.evaluation.evaluators.tool_routing import (
    ToolRoutingEvaluator,
)


def default_evaluators() -> list:
    """The deterministic suite; contextualization joins when a judge exists."""
    return [
        IntentEvaluator(),
        RetrievalEvaluator(),
        GroundednessEvaluator(),
        ToolRoutingEvaluator(),
        FreshnessEvaluator(),
        MaskingLeakEvaluator(),
        AccessLeakEvaluator(),
        ContextualizationEvaluator(),
    ]


__all__ = [
    "AccessLeakEvaluator",
    "ContextualizationEvaluator",
    "FreshnessEvaluator",
    "GroundednessEvaluator",
    "IntentEvaluator",
    "MaskingLeakEvaluator",
    "RetrievalEvaluator",
    "ToolRoutingEvaluator",
    "default_evaluators",
]
