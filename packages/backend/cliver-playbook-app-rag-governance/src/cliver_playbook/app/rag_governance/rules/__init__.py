"""Intent rules: schema, compiler, classifier, versioning and activation."""

from cliver_playbook.app.rag_governance.rules.compiler import (
    RuleCompileError,
    compile_rule_scope,
    parse_filter_ast,
)
from cliver_playbook.app.rag_governance.rules.engine import (
    SCOPE_COMBINATIONS,
    IntentMatch,
    KeywordRegexClassifier,
    compose_scope,
    fallback_rule,
    rank_matches,
)
from cliver_playbook.app.rag_governance.rules.schema import (
    STRATEGIES,
    ClassifierSpec,
    IntentRule,
    RefusalSpec,
    RetrievalSpec,
    RuleValidationError,
    Strategy,
)
from cliver_playbook.app.rag_governance.rules.versions import (
    RuleActivationError,
    RuleSetNotFoundError,
    RuleSetVersion,
    activate_rule_set,
    active_rule_set,
    create_rule_set,
    get_rule_set,
    get_rule_set_or_raise,
    list_rule_sets,
    rule_from_row,
)

__all__ = [
    "SCOPE_COMBINATIONS",
    "STRATEGIES",
    "ClassifierSpec",
    "IntentMatch",
    "IntentRule",
    "KeywordRegexClassifier",
    "RefusalSpec",
    "RetrievalSpec",
    "RuleActivationError",
    "RuleCompileError",
    "RuleSetNotFoundError",
    "RuleSetVersion",
    "RuleValidationError",
    "Strategy",
    "activate_rule_set",
    "active_rule_set",
    "compile_rule_scope",
    "compose_scope",
    "create_rule_set",
    "fallback_rule",
    "get_rule_set",
    "get_rule_set_or_raise",
    "list_rule_sets",
    "parse_filter_ast",
    "rank_matches",
    "rule_from_row",
]
