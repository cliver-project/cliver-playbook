"""The governed query facade: routing, access, tools and citations."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from cliver_playbook.app.rag.models.entities import Chunk, ChunkParent, Document
from cliver_playbook.app.rag.retrieval.base import Hit
from cliver_playbook.app.rag_governance.models import (
    GovDocumentAcl,
    GovIntentRule,
    GovPrincipalClearance,
    GovProject,
    GovTool,
)
from cliver_playbook.app.rag_governance.query.facade import (
    PlannedCall,
    QueryConfigError,
    QueryToolError,
    ToolPlan,
    answer_question,
)
from cliver_playbook.app.rag_governance.rules.schema import IntentRule
from cliver_playbook.app.rag_governance.services.projects import create_project
from cliver_playbook.app.rag_governance.tools.base import ToolResult, ToolSpec
from cliver_playbook.app.rag_governance.tools.registry import ToolRegistry
from cliver_playbook.app.user.auth.dependencies import Viewer

SHANGHAI = timezone(timedelta(hours=8))
NOW = datetime(2026, 11, 1, tzinfo=SHANGHAI)


def _viewer(
    *,
    user_id: int = 1,
    permissions: frozenset[str] = frozenset(),
    roles: frozenset[str] = frozenset(),
) -> Viewer:
    return Viewer(
        user_id=user_id,
        username=f"user-{user_id}",
        display_name="Test User",
        must_change_password=False,
        role_codes=roles,
        permissions=permissions,
    )


def _rule(
    intent: str = "financial_overview",
    *,
    keywords: Sequence[str] = (),
    patterns: Sequence[str] = (),
    strategy: str = "retrieval",
    tools: Sequence[str] = (),
    priority: int = 100,
    scope: dict[str, Any] | None = None,
    snapshot_fallback: bool = False,
    refusal: dict[str, Any] | None = None,
    retrieval: dict[str, Any] | None = None,
) -> IntentRule:
    return IntentRule.model_validate(
        {
            "intent": intent,
            "description": "",
            "priority": priority,
            "classifier": {
                "kind": "keyword-regex",
                "config": {"keywords": list(keywords), "patterns": list(patterns)},
            },
            "scope": scope or {},
            "retrieval": retrieval or {},
            "strategy": strategy,
            "tools": list(tools),
            "snapshot_fallback": snapshot_fallback,
            "refusal": refusal,
        }
    )


async def _project(
    db: AsyncSession,
    *,
    config: dict[str, Any] | None = None,
    status: str = "active",
) -> GovProject:
    project = await create_project(
        db,
        slug=f"finance-{uuid4().hex[:8]}",
        name="Finance KPI",
        config=config or {},
    )
    project.status = status
    await db.commit()
    await db.refresh(project)
    return project


async def _activate(db: AsyncSession, project: GovProject, rules: Sequence[IntentRule]) -> None:
    for rule in rules:
        db.add(
            GovIntentRule(
                project_id=project.id,
                version=1,
                intent=rule.intent,
                description=rule.description,
                priority=rule.priority,
                classifier_json=rule.classifier.model_dump(mode="json"),
                scope_json=rule.scope,
                retrieval_json=rule.retrieval.model_dump(mode="json"),
                strategy=rule.strategy,
                tools_json=list(rule.tools),
                snapshot_fallback=rule.snapshot_fallback,
                refusal_json=rule.refusal.model_dump(mode="json") if rule.refusal else {},
                status="active",
                created_by="tester",
            )
        )
    await db.commit()


async def _set_clearance(db: AsyncSession, level: int, *, user_id: int = 1) -> None:
    db.add(
        GovPrincipalClearance(
            principal_type="user",
            principal_id=str(user_id),
            level=level,
        )
    )
    await db.commit()


async def _add_doc(
    db: AsyncSession,
    project: GovProject,
    *,
    logical_id: str,
    text: str,
    classification: int | None = 0,
    published: bool = True,
    section_path: str = "H2#资产负债率",
    metadata: dict[str, Any] | None = None,
) -> Document:
    suffix = uuid4().hex
    document = Document(
        id=f"doc-{suffix}",
        title=logical_id,
        source_uri=f"{logical_id}.md",
        mime_type="text/markdown",
        chunker_id="parent-child",
        chunker_config={},
        embedder_id="stub@1.0",
        dim=64,
        version=1,
        status="indexed",
        chunk_count=1,
        logical_id=logical_id,
        classification=classification,
        collection_id=project.collection_id,
        published=published,
        pipeline_run_id=None,
        metadata_json={"doc_type": "metric_definition", **(metadata or {})},
    )
    parent = ChunkParent(
        id=f"parent-{suffix}",
        document_id=document.id,
        ordinal=0,
        text=text,
        metadata_json={"section_path": section_path},
    )
    chunk = Chunk(
        id=f"chunk-{suffix}",
        document_id=document.id,
        ordinal=0,
        text=text,
        search_text=text,
        token_count=10,
        metadata_json={"section_path": section_path},
        parent_id=parent.id,
    )
    db.add_all([document, parent, chunk])
    await db.commit()
    return document


def _hit(
    *,
    logical_id: str = "fin-closed-report",
    text: str = "September closed-period revenue was 1200.",
    parent_text: str | None = None,
    period: str | None = "2026-09",
    classification: int | None = 2,
    section_path: str = "H2#Revenue",
) -> Hit:
    suffix = uuid4().hex
    return Hit(
        chunk_id=f"chunk-{suffix}",
        document_id=f"doc-{suffix}",
        ordinal=0,
        text=text,
        score=1.0,
        metadata={"section_path": section_path},
        parent_id=f"parent-{suffix}",
        parent_text=parent_text or text,
        document_metadata={"period": period} if period else {},
        logical_id=logical_id,
        classification=classification,
    )


def _binding(
    project: GovProject,
    name: str,
    *,
    min_clearance: int = 0,
    permission_code: str | None = None,
    scope_json: dict[str, Any] | None = None,
    enabled: bool = True,
    masking: dict[str, Any] | None = None,
) -> GovTool:
    return GovTool(
        project_id=project.id,
        name=name,
        kind="internal",
        config_json={},
        schema_json={},
        read_only=True,
        permission_code=permission_code,
        min_clearance=min_clearance,
        scope_json=scope_json or {},
        masking_json=masking or {},
        result_cap_json={},
        enabled=enabled,
    )


class RecordingRetriever:
    name = "recording"
    modes = frozenset({"sparse", "hybrid"})

    def __init__(self, hits: Sequence[Hit] = ()) -> None:
        self.hits = list(hits)
        self.calls = 0
        self.queries = []

    def effective_mode(self, mode: str) -> str:
        return "sparse" if mode == "hybrid" else mode

    async def retrieve(self, query, *, db):
        self.calls += 1
        self.queries.append(query)
        return list(self.hits)


class PassthroughReranker:
    name = "pass"
    model_id = "pass@1"
    produces_relevance_scores = False

    def rerank(self, query: str, hits: list[Hit], *, top_k: int | None = None) -> list[Hit]:
        return hits[:top_k] if top_k else hits


class RecordingLLM:
    name = "recording"
    model_id = "recording@1"

    def __init__(self, text: str | None = None) -> None:
        self.text = text
        self.prompts: list[str] = []

    def generate(self, *, system: str, prompt: str, max_tokens: int = 1024) -> str:
        self.prompts.append(prompt)
        return self.text if self.text is not None else prompt


class RecordingPlanner:
    def __init__(self, calls: Sequence[PlannedCall] = ()) -> None:
        self.calls = list(calls)
        self.offered_tools: list[str] = []
        self.called = 0
        self.as_of = None

    async def plan(
        self,
        *,
        question: str,
        rule: IntentRule,
        tools: Sequence[ToolSpec],
        as_of: datetime,
    ) -> ToolPlan:
        self.called += 1
        self.offered_tools = [tool.name for tool in tools]
        self.as_of = as_of
        calls = self.calls or [PlannedCall(tool.name) for tool in tools]
        return ToolPlan(calls=tuple(calls))


class StaticTool:
    def __init__(
        self,
        name: str,
        *,
        data: Any = None,
        error: str | None = None,
        raises: Exception | None = None,
        result_as_of: datetime | None = None,
    ) -> None:
        self.spec = ToolSpec(name=name, description="test tool", input_schema={})
        self.data = data
        self.error = error
        self.raises = raises
        self.result_as_of = result_as_of
        self.contexts = []

    async def invoke(self, args: dict[str, Any], ctx):
        self.contexts.append(ctx)
        if self.raises is not None:
            raise self.raises
        row_count = len(self.data) if isinstance(self.data, list) else (1 if self.data else 0)
        return ToolResult(
            tool=self.spec.name,
            data=self.data,
            as_of=self.result_as_of or ctx.as_of,
            row_count=row_count,
            error=self.error,
        )


async def test_retrieval_only_answer_cites_document_locators(db_session: AsyncSession) -> None:
    project = await _project(db_session)
    await _activate(db_session, project, [_rule(keywords=["revenue"])])
    await _set_clearance(db_session, 2)
    await _add_doc(
        db_session,
        project,
        logical_id="fin-metric-catalog",
        text="Revenue and debt ratio definitions for the finance catalog.",
        classification=2,
    )
    llm = RecordingLLM(text="Revenue is defined in the catalog.")

    answer = await answer_question(
        db_session,
        project=project,
        question="What is the revenue definition?",
        viewer=_viewer(),
        as_of=NOW,
        llm=llm,
        reranker=PassthroughReranker(),
    )

    assert answer.strategy == "retrieval"
    assert answer.refused is False
    assert any(
        citation.kind == "document"
        and citation.ref == "fin-metric-catalog"
        and citation.locator == "资产负债率"
        for citation in answer.citations
    )
    assert "[doc:fin-metric-catalog#资产负债率]" in answer.text
    assert answer.observation.retrieval_calls == 1
    assert answer.observation.sources[0].logical_id == "fin-metric-catalog"
    assert "Revenue and debt ratio definitions" in llm.prompts[0]


async def test_parent_text_is_what_the_generator_receives(db_session: AsyncSession) -> None:
    project = await _project(db_session)
    await _activate(db_session, project, [_rule(keywords=["revenue"])])
    hit = _hit(
        logical_id="fin-metric-catalog",
        text="child search text only",
        parent_text="PARENT ORIGINAL SECTION",
        period=None,
    )
    llm = RecordingLLM(text="ok")

    await answer_question(
        db_session,
        project=project,
        question="What is revenue?",
        viewer=_viewer(),
        as_of=NOW,
        llm=llm,
        retriever=RecordingRetriever([hit]),
        reranker=PassthroughReranker(),
    )

    assert "PARENT ORIGINAL SECTION" in llm.prompts[0]
    assert "child search text only" not in llm.prompts[0]


async def test_none_strategy_makes_zero_retrieval_and_tool_calls(
    db_session: AsyncSession,
) -> None:
    project = await _project(db_session)
    await _activate(
        db_session,
        project,
        [
            _rule(
                intent="out_of_scope",
                keywords=["write off"],
                strategy="none",
                refusal={"message": "I cannot modify financial records."},
            )
        ],
    )
    retriever = RecordingRetriever([_hit()])
    planner = RecordingPlanner()
    registry = ToolRegistry()
    registry.register(StaticTool("finance_kpi_snapshot", data={"revenue": "1"}))

    answer = await answer_question(
        db_session,
        project=project,
        question="Please write off this receivable",
        viewer=_viewer(),
        as_of=NOW,
        llm=RecordingLLM(),
        retriever=retriever,
        tool_registry=registry,
        planner=planner,
    )

    assert answer.refused is True
    assert answer.strategy == "none"
    assert answer.text == "I cannot modify financial records."
    assert retriever.calls == 0
    assert planner.called == 0
    assert answer.observation.retrieval_calls == 0
    assert answer.observation.tool_calls == ()


async def test_tool_failure_is_explicit_and_never_substituted(
    db_session: AsyncSession,
) -> None:
    project = await _project(db_session)
    await _activate(
        db_session,
        project,
        [_rule(keywords=["revenue"], strategy="tools", tools=["finance_kpi_snapshot"])],
    )
    registry = ToolRegistry()
    registry.register(StaticTool("finance_kpi_snapshot", raises=TimeoutError("the ERP timed out")))
    retriever = RecordingRetriever([_hit()])

    answer = await answer_question(
        db_session,
        project=project,
        question="What was the revenue?",
        viewer=_viewer(),
        as_of=NOW,
        llm=RecordingLLM(),
        retriever=retriever,
        tool_bindings=[_binding(project, "finance_kpi_snapshot")],
        tool_registry=registry,
        planner=RecordingPlanner(),
    )

    assert "live data unavailable" in answer.text.lower()
    assert answer.refused is True
    assert answer.tool_calls[0].error is not None
    assert "TimeoutError" in answer.tool_calls[0].error
    assert retriever.calls == 0  # a tools-only rule never retrieves
    assert answer.observation.unavailability_answer is True


async def test_snapshot_fallback_is_labeled_with_its_period(
    db_session: AsyncSession,
) -> None:
    project = await _project(db_session)
    await _activate(
        db_session,
        project,
        [
            _rule(
                keywords=["revenue"],
                strategy="tools",
                tools=["finance_kpi_snapshot"],
                snapshot_fallback=True,
            )
        ],
    )
    registry = ToolRegistry()
    registry.register(StaticTool("finance_kpi_snapshot", raises=TimeoutError("offline")))
    retriever = RecordingRetriever(
        [_hit(period="2026-09", text="September closed-period revenue was 1200.")]
    )

    answer = await answer_question(
        db_session,
        project=project,
        question="What was the revenue?",
        viewer=_viewer(),
        as_of=NOW,
        llm=RecordingLLM(),
        retriever=retriever,
        tool_bindings=[_binding(project, "finance_kpi_snapshot")],
        tool_registry=registry,
        planner=RecordingPlanner(),
    )

    assert "2026-09" in answer.text
    assert "live data unavailable" in answer.text.lower()
    assert answer.strategy == "retrieval"
    assert answer.tool_calls[0].is_snapshot is True
    assert answer.tool_calls[0].period == "2026-09"
    assert any(citation.kind == "document" for citation in answer.citations)
    assert retriever.calls == 1


async def test_unauthorized_tool_is_never_offered_to_the_planner(
    db_session: AsyncSession,
) -> None:
    project = await _project(db_session)
    await _activate(
        db_session,
        project,
        [
            _rule(
                keywords=["revenue"],
                strategy="agentic",
                tools=["finance_kpi_snapshot"],
            )
        ],
    )
    await _set_clearance(db_session, 2)
    binding = _binding(project, "finance_kpi_snapshot", min_clearance=3)
    registry = ToolRegistry()
    registry.register(StaticTool("finance_kpi_snapshot", data={"revenue": "1"}))
    planner = RecordingPlanner()

    await answer_question(
        db_session,
        project=project,
        question="What was the revenue?",
        viewer=_viewer(),
        as_of=NOW,
        llm=RecordingLLM(),
        retriever=RecordingRetriever(),
        tool_bindings=[binding],
        tool_registry=registry,
        planner=planner,
    )

    assert planner.offered_tools == []
    # The planner still runs with an empty offer, so the denial is
    # observable rather than a silent skip.
    assert planner.called == 1


async def test_a_planner_cannot_select_an_unauthorized_tool(
    db_session: AsyncSession,
) -> None:
    project = await _project(db_session)
    await _activate(
        db_session,
        project,
        [
            _rule(
                keywords=["revenue"],
                strategy="agentic",
                tools=["finance_kpi_snapshot"],
            )
        ],
    )
    await _set_clearance(db_session, 2)
    binding = _binding(project, "finance_kpi_snapshot", min_clearance=3)
    registry = ToolRegistry()
    tool = StaticTool("finance_kpi_snapshot", data={"revenue": "1"})
    registry.register(tool)
    planner = RecordingPlanner([PlannedCall("finance_kpi_snapshot")])

    with pytest.raises(QueryToolError, match="not authorized"):
        await answer_question(
            db_session,
            project=project,
            question="What was the revenue?",
            viewer=_viewer(),
            as_of=NOW,
            llm=RecordingLLM(),
            tool_bindings=[binding],
            tool_registry=registry,
            planner=planner,
        )
    assert tool.contexts == []


async def test_agentic_retrieves_and_calls_tools(db_session: AsyncSession) -> None:
    project = await _project(db_session)
    await _activate(
        db_session,
        project,
        [
            _rule(
                keywords=["revenue"],
                strategy="agentic",
                tools=["finance_kpi_snapshot"],
            )
        ],
    )
    await _set_clearance(db_session, 2)
    await _add_doc(
        db_session,
        project,
        logical_id="fin-metric-catalog",
        text="Revenue definitions for the finance catalog.",
        classification=2,
    )
    binding = _binding(project, "finance_kpi_snapshot", min_clearance=2)
    registry = ToolRegistry()
    tool = StaticTool(
        "finance_kpi_snapshot",
        data={"revenue": "8650", "as_of": "2026-10-31T23:59:59+08:00"},
    )
    registry.register(tool)
    llm = RecordingLLM(text="Revenue was 8650.")

    answer = await answer_question(
        db_session,
        project=project,
        question="What was the revenue?",
        viewer=_viewer(),
        as_of=NOW,
        llm=llm,
        reranker=PassthroughReranker(),
        tool_bindings=[binding],
        tool_registry=registry,
        planner=RecordingPlanner(),
    )

    assert answer.strategy == "agentic"
    assert answer.observation.retrieval_calls == 1
    assert {citation.kind for citation in answer.citations} == {"document", "tool"}
    assert "[tool:finance_kpi_snapshot@2026-10-31]" in answer.text
    assert tool.contexts[0].as_of == NOW
    assert answer.observation.tool_calls[0].as_of == NOW
    assert "Revenue definitions for the finance catalog." in llm.prompts[0]
    assert '"revenue": "8650"' in llm.prompts[0]


async def test_tools_strategy_skips_retrieval(db_session: AsyncSession) -> None:
    project = await _project(db_session)
    await _activate(
        db_session,
        project,
        [_rule(keywords=["revenue"], strategy="tools", tools=["finance_kpi_snapshot"])],
    )
    binding = _binding(project, "finance_kpi_snapshot")
    registry = ToolRegistry()
    registry.register(StaticTool("finance_kpi_snapshot", data={"revenue": "8650"}))
    retriever = RecordingRetriever([_hit()])

    answer = await answer_question(
        db_session,
        project=project,
        question="What was the revenue?",
        viewer=_viewer(),
        as_of=NOW,
        llm=RecordingLLM(text="Revenue was 8650."),
        retriever=retriever,
        tool_bindings=[binding],
        tool_registry=registry,
        planner=RecordingPlanner(),
    )

    assert retriever.calls == 0
    assert answer.observation.retrieval_calls == 0
    assert [citation.kind for citation in answer.citations] == ["tool"]


async def test_rule_scope_limits_retrieval(db_session: AsyncSession) -> None:
    project = await _project(db_session)
    await _activate(
        db_session,
        project,
        [
            _rule(
                keywords=["revenue"],
                scope={"field": "doc_type", "op": "eq", "value": "policy"},
            )
        ],
    )
    await _add_doc(
        db_session,
        project,
        logical_id="revenue-policy",
        text="Revenue policy and recognition rules.",
        metadata={"doc_type": "policy"},
    )
    await _add_doc(
        db_session,
        project,
        logical_id="revenue-metric",
        text="Revenue metric definition and formula.",
        metadata={"doc_type": "metric_definition"},
    )

    answer = await answer_question(
        db_session,
        project=project,
        question="revenue policy",
        viewer=_viewer(),
        as_of=NOW,
        llm=RecordingLLM(text="See the policy."),
        reranker=PassthroughReranker(),
    )

    refs = {citation.ref for citation in answer.citations if citation.kind == "document"}
    assert refs == {"revenue-policy"}


async def test_clearance_and_grants_govern_retrieval(db_session: AsyncSession) -> None:
    project = await _project(db_session)
    await _activate(db_session, project, [_rule(keywords=["revenue"])])
    await _set_clearance(db_session, 2)
    await _add_doc(
        db_session,
        project,
        logical_id="revenue-public",
        text="Revenue public summary.",
        classification=2,
    )
    await _add_doc(
        db_session,
        project,
        logical_id="revenue-secret",
        text="Revenue secret board detail.",
        classification=4,
    )
    await _add_doc(
        db_session,
        project,
        logical_id="revenue-unlabelled",
        text="Revenue unlabelled note.",
        classification=None,
    )

    first = await answer_question(
        db_session,
        project=project,
        question="revenue",
        viewer=_viewer(),
        as_of=NOW,
        llm=RecordingLLM(text="ok"),
        reranker=PassthroughReranker(),
    )
    first_refs = {citation.ref for citation in first.citations}
    assert "revenue-public" in first_refs
    assert "revenue-secret" not in first_refs
    assert "revenue-unlabelled" not in first_refs

    db_session.add(
        GovDocumentAcl(
            logical_id="revenue-secret",
            principal_type="user",
            principal_id="1",
        )
    )
    await db_session.commit()

    second = await answer_question(
        db_session,
        project=project,
        question="revenue",
        viewer=_viewer(),
        as_of=NOW,
        llm=RecordingLLM(text="ok"),
        reranker=PassthroughReranker(),
    )
    second_refs = {citation.ref for citation in second.citations}
    assert "revenue-secret" in second_refs
    assert "revenue-unlabelled" not in second_refs


async def test_fallback_rule_serves_when_no_keyword_matches(
    db_session: AsyncSession,
) -> None:
    project = await _project(db_session)
    await _activate(
        db_session,
        project,
        [
            _rule(intent="financial_overview", keywords=["revenue"]),
            _rule(intent="fallback", priority=0),
        ],
    )

    answer = await answer_question(
        db_session,
        project=project,
        question="How are you today?",
        viewer=_viewer(),
        as_of=NOW,
        llm=RecordingLLM(text="ok"),
        retriever=RecordingRetriever([_hit()]),
        reranker=PassthroughReranker(),
    )

    assert answer.intent == "fallback"
    assert answer.strategy == "retrieval"


async def test_no_match_without_fallback_refuses_without_retrieval(
    db_session: AsyncSession,
) -> None:
    project = await _project(db_session)
    await _activate(db_session, project, [_rule(keywords=["revenue"])])
    retriever = RecordingRetriever([_hit()])
    planner = RecordingPlanner()

    answer = await answer_question(
        db_session,
        project=project,
        question="How are you today?",
        viewer=_viewer(),
        as_of=NOW,
        llm=RecordingLLM(),
        retriever=retriever,
        tool_registry=ToolRegistry(),
        planner=planner,
    )

    assert answer.refused is True
    assert answer.intent is None
    assert retriever.calls == 0
    assert planner.called == 0


async def test_tool_result_masking_is_applied_once(db_session: AsyncSession) -> None:
    project = await _project(
        db_session,
        config={"masking": {"patterns": ["phone"], "replacement": "[REDACTED]"}},
    )
    await _activate(
        db_session,
        project,
        [_rule(keywords=["contact"], strategy="tools", tools=["finance_kpi_snapshot"])],
    )
    binding = _binding(project, "finance_kpi_snapshot")
    registry = ToolRegistry()
    registry.register(
        StaticTool("finance_kpi_snapshot", data={"contact": "Call 13800138000 for details"})
    )
    llm = RecordingLLM(text="Call the finance team.")

    answer = await answer_question(
        db_session,
        project=project,
        question="contact details",
        viewer=_viewer(),
        as_of=NOW,
        llm=llm,
        tool_bindings=[binding],
        tool_registry=registry,
        planner=RecordingPlanner(),
    )

    assert "13800138000" not in llm.prompts[0]
    assert "[REDACTED]" in llm.prompts[0]
    assert answer.tool_calls[0].result["contact"] == "Call [REDACTED] for details"


async def test_tool_permission_code_is_required(db_session: AsyncSession) -> None:
    project = await _project(db_session)
    await _activate(
        db_session,
        project,
        [_rule(keywords=["revenue"], strategy="agentic", tools=["finance_kpi_snapshot"])],
    )
    binding = _binding(project, "finance_kpi_snapshot", permission_code="finance:live")
    registry = ToolRegistry()
    registry.register(StaticTool("finance_kpi_snapshot", data={"revenue": "1"}))
    denied_planner = RecordingPlanner()
    allowed_planner = RecordingPlanner()

    await answer_question(
        db_session,
        project=project,
        question="What was the revenue?",
        viewer=_viewer(),
        as_of=NOW,
        llm=RecordingLLM(),
        retriever=RecordingRetriever(),
        tool_bindings=[binding],
        tool_registry=registry,
        planner=denied_planner,
    )
    await answer_question(
        db_session,
        project=project,
        question="What was the revenue?",
        viewer=_viewer(permissions=frozenset({"finance:live"})),
        as_of=NOW,
        llm=RecordingLLM(),
        retriever=RecordingRetriever(),
        tool_bindings=[binding],
        tool_registry=registry,
        planner=allowed_planner,
    )

    assert denied_planner.offered_tools == []
    assert allowed_planner.offered_tools == ["finance_kpi_snapshot"]


async def test_tool_scope_must_match_the_viewer(db_session: AsyncSession) -> None:
    project = await _project(db_session)
    await _activate(
        db_session,
        project,
        [_rule(keywords=["revenue"], strategy="agentic", tools=["finance_kpi_snapshot"])],
    )
    binding = _binding(project, "finance_kpi_snapshot", scope_json={"company": "CN01"})
    registry = ToolRegistry()
    registry.register(StaticTool("finance_kpi_snapshot", data={"revenue": "1"}))
    no_scope = RecordingPlanner()
    wrong_scope = _viewer()
    wrong_scope.scopes = {"company": "CN02"}  # type: ignore[attr-defined]
    matching = _viewer()
    matching.scopes = {"company": "CN01"}  # type: ignore[attr-defined]

    await answer_question(
        db_session,
        project=project,
        question="What was the revenue?",
        viewer=wrong_scope,
        as_of=NOW,
        llm=RecordingLLM(),
        retriever=RecordingRetriever(),
        tool_bindings=[binding],
        tool_registry=registry,
        planner=no_scope,
    )
    assert no_scope.offered_tools == []

    allowed = RecordingPlanner()
    await answer_question(
        db_session,
        project=project,
        question="What was the revenue?",
        viewer=matching,
        as_of=NOW,
        llm=RecordingLLM(),
        retriever=RecordingRetriever(),
        tool_bindings=[binding],
        tool_registry=registry,
        planner=allowed,
    )
    assert allowed.offered_tools == ["finance_kpi_snapshot"]


async def test_audit_records_the_trace_without_the_question(
    db_session: AsyncSession,
) -> None:
    project = await _project(db_session)
    await _activate(db_session, project, [_rule(keywords=["revenue"])])
    await _add_doc(
        db_session,
        project,
        logical_id="fin-metric-catalog",
        text="Revenue definitions for the finance catalog.",
    )
    records: list[dict[str, Any]] = []

    async def sink(record: dict[str, Any]) -> None:
        records.append(record)

    await answer_question(
        db_session,
        project=project,
        question="What is revenue?",
        viewer=_viewer(),
        as_of=NOW,
        llm=RecordingLLM(text="ok"),
        reranker=PassthroughReranker(),
        audit=sink,
    )

    assert len(records) == 1
    record = records[0]
    assert record["event"] == "rag.governance.query"
    assert record["intent"] == "financial_overview"
    assert record["strategy"] == "retrieval"
    assert record["refused"] is False
    assert record["hit_chunk_ids"] == ["fin-metric-catalog"]
    assert "What is revenue?" not in str(record)
    assert record["question_fingerprint"]


async def test_a_project_without_active_rules_cannot_answer(
    db_session: AsyncSession,
) -> None:
    project = await _project(db_session)

    with pytest.raises(QueryConfigError, match="no active rule set"):
        await answer_question(
            db_session,
            project=project,
            question="What is revenue?",
            viewer=_viewer(),
            as_of=NOW,
            llm=RecordingLLM(),
        )


async def test_naive_as_of_is_rejected(db_session: AsyncSession) -> None:
    project = await _project(db_session)

    with pytest.raises(QueryConfigError, match="timezone-aware"):
        await answer_question(
            db_session,
            project=project,
            question="What is revenue?",
            viewer=_viewer(),
            as_of=datetime(2026, 11, 1),
            llm=RecordingLLM(),
        )


async def test_api_query_returns_citations(client, db_session: AsyncSession) -> None:
    project = await _project(db_session)
    await _activate(db_session, project, [_rule(keywords=["revenue"])])
    await _add_doc(
        db_session,
        project,
        logical_id="fin-metric-catalog",
        text="Revenue definitions for the finance catalog.",
    )

    response = await client.post(
        f"/api/v1/rag-governance/projects/{project.id}/query",
        json={
            "question": "What is the revenue definition?",
            "as_of": "2026-11-01T00:00:00+08:00",
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["strategy"] == "retrieval"
    assert body["refused"] is False
    assert body["rule_version"] == 1
    assert any(item["kind"] == "document" for item in body["citations"])
    assert "[doc:" in body["text"]


async def test_api_query_requires_authentication(raw_client) -> None:
    response = await raw_client.post(
        "/api/v1/rag-governance/projects/x/query",
        json={"question": "What is revenue?"},
    )
    assert response.status_code == 401


async def test_api_query_unknown_project_is_404(client) -> None:
    response = await client.post(
        "/api/v1/rag-governance/projects/missing/query",
        json={"question": "What is revenue?"},
    )
    assert response.status_code == 404


async def test_api_query_without_active_rules_is_a_conflict(
    client, db_session: AsyncSession
) -> None:
    project = await _project(db_session)

    response = await client.post(
        f"/api/v1/rag-governance/projects/{project.id}/query",
        json={"question": "What is revenue?"},
    )

    assert response.status_code == 409
    assert "no active rule set" in response.json()["detail"]


async def test_api_query_rejects_a_naive_as_of(client, db_session: AsyncSession) -> None:
    project = await _project(db_session)

    response = await client.post(
        f"/api/v1/rag-governance/projects/{project.id}/query",
        json={"question": "What is revenue?", "as_of": "2026-11-01T00:00:00"},
    )

    assert response.status_code == 422
