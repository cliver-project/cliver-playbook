"""Wire models for intent rules."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from cliver_playbook.app.rag_governance.rules.schema import IntentRule, Strategy
from cliver_playbook.app.rag_governance.rules.versions import RuleSetVersion


class RuleSetRead(BaseModel):
    project_id: str
    version: int | None = None
    status: str | None = None
    eval_run_id: str | None = None
    rules: list[IntentRule] = Field(default_factory=list)

    @classmethod
    def from_version(cls, project_id: str, rule_set: RuleSetVersion | None) -> RuleSetRead:
        if rule_set is None:
            return cls(project_id=project_id)
        return cls(
            project_id=rule_set.project_id,
            version=rule_set.version,
            status=rule_set.status,
            eval_run_id=rule_set.eval_run_id,
            rules=rule_set.rules,
        )


class RuleSetList(BaseModel):
    items: list[RuleSetRead]


class RuleSetPropose(BaseModel):
    model_config = ConfigDict(extra="forbid")

    rules: list[IntentRule] = Field(min_length=1)


class RuleSetActivate(RuleSetPropose):
    eval_run_id: str = Field(min_length=1, max_length=36)


class RulePreviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    question: str = Field(min_length=1, max_length=4000)
    rules: list[IntentRule] | None = None


class RuleMatchRead(BaseModel):
    intent: str
    confidence: float
    priority: int
    strategy: Strategy


class RulePreviewRead(BaseModel):
    matches: list[RuleMatchRead]
