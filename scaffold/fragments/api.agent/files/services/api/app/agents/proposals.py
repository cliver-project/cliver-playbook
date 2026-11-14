"""Model-based experience distillation for improvement proposals.

The learning loop's default proposal is deterministic and useful without a
model. When the project configures an API-plane model, this module turns the
recent redacted outcomes and feedback into a concise prompt proposal through
AgentCore structured output. Any provider or validation failure falls back to
the deterministic proposal in ``learning.py``; approval and the golden-set
gate remain unchanged.
"""

from __future__ import annotations

import json
from typing import Protocol

from cliver_core import AgentCore, ModelBindings
from pydantic import BaseModel, Field

from app.agents.core import build_llm_binding
from app.settings import Settings


class ProposalDraft(BaseModel):
    """The structured result the distillation model must return."""

    title: str = Field(min_length=1, max_length=200)
    rationale: str = Field(min_length=1, max_length=2000)
    prompt_append: str = Field(min_length=1, max_length=2000)


class ProposalGenerator(Protocol):
    """Turn recent outcome evidence into a prompt proposal."""

    async def draft(
        self,
        *,
        agent: str,
        metric: str,
        threshold: float,
        evidence: list[dict],
    ) -> ProposalDraft: ...


class AgentCoreProposalModel:
    """Ask AgentCore to distill recent experiences into a prompt proposal."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    async def draft(
        self,
        *,
        agent: str,
        metric: str,
        threshold: float,
        evidence: list[dict],
    ) -> ProposalDraft:
        binding = build_llm_binding(self.settings)
        if binding is None:
            raise RuntimeError("No API-plane model is configured")
        async with AgentCore.open(ModelBindings(llm=binding)) as core:
            response = await core.chat_structured(
                _proposal_input(agent, metric, threshold, evidence),
                schema=ProposalDraft,
                mode="auto",
                retries=1,
                system_prompt=_proposal_prompt(agent),
                run_timeout=self.settings.agent_llm_timeout,
            )
        value = response.value
        if isinstance(value, ProposalDraft):
            return value
        return ProposalDraft.model_validate(value)


def build_proposal_generator(settings: Settings) -> ProposalGenerator | None:
    """Use model distillation only when the API plane has a model."""
    if not settings.agent_llm_model.strip():
        return None
    return AgentCoreProposalModel(settings)


def _proposal_prompt(agent: str) -> str:
    return "\n".join(
        [
            f"You improve the system prompt of the business-point agent {agent!r}.",
            "You receive recent redacted outcomes, scores and user feedback.",
            "Return a concise, generalizable prompt addition that addresses the",
            "recurring failure pattern; do not repeat user data or invent domain",
            "facts. Do not change tools, permissions, safety rules or data access.",
            "Never propose instructions that reveal secrets, bypass approval,",
            "ignore safety, or take irreversible actions without permission.",
            "The prompt addition must be useful without naming a specific user.",
            "Return title, rationale and prompt_append; keep prompt_append under",
            "2000 characters.",
        ]
    )


def _proposal_input(agent: str, metric: str, threshold: float, evidence: list[dict]) -> str:
    payload = {
        "agent": agent,
        "metric": metric,
        "launch_threshold": threshold,
        "recent_outcomes": evidence,
    }
    return json.dumps(payload, ensure_ascii=False, indent=2, default=str)
