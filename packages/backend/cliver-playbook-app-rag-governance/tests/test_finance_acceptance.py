"""End-to-end acceptance for the finance KPI reference slice.

The scenario is exercised through the real governance loop: a project,
a confirmed golden set, the versioned rules, real BM25 retrieval over
seeded parent/child rows, the restricted composite tools and the default
evaluator suite. The LLM is a stub that returns its prompt, which makes
the answer's numeric facts and citations inspectable without a model.

The offline BM25 fallback tokenizes ASCII only by design; the production
Chinese path is the Postgres full-text/vector leg. These tests augment
the fallback with CJK bigrams so the seeded Chinese corpus is searchable
on SQLite. That is a test-only tokenizer, not a change to `rag`.
"""

from __future__ import annotations

import itertools
import re
from collections.abc import Sequence
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, NamedTuple
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from cliver_playbook.app.rag.access import AccessScope
from cliver_playbook.app.rag.models.entities import Chunk, ChunkParent, Document
from cliver_playbook.app.rag.reranking.noop import NoopReranker
from cliver_playbook.app.rag.retrieval import bm25_only
from cliver_playbook.app.rag_governance.evaluation import (
    EvalContext,
    default_evaluators,
    run_evaluation,
)
from cliver_playbook.app.rag_governance.golden import (
    confirm_set,
    create_candidate_set,
    load_cases,
    parse_jsonl,
)
from cliver_playbook.app.rag_governance.models import GovProject, GovTool
from cliver_playbook.app.rag_governance.query.facade import answer_question
from cliver_playbook.app.rag_governance.services.projects import create_project
from cliver_playbook.app.rag_governance.testing.mock_kingdee import (
    ALLOWLISTED_TOOLS,
    MockKingdeeServer,
)
from cliver_playbook.app.rag_governance.tools import (
    McpTool,
    McpToolClient,
    ToolRegistry,
)
from cliver_playbook.app.user.auth.dependencies import Viewer
from examples.finance_kpi.rules import FINANCE_RULES
from examples.finance_kpi.tools import register

EXAMPLES = Path(__file__).resolve().parents[1] / "examples" / "finance_kpi"
SEED_DIR = EXAMPLES / "seed"
SHANGHAI = timezone(timedelta(hours=8))
REFERENCE = datetime(2026, 11, 1, tzinfo=SHANGHAI)
CASE_AS_OF = datetime(2026, 10, 31, 23, 59, 59, tzinfo=SHANGHAI)

PROJECT_CONFIG: dict[str, Any] = {
    "scope_combination": "highest_priority",
    "retrieval": {
        "mode": "sparse",
        "top_k": 20,
        "rerank_top_k": 10,
        "reranker": "noop",
    },
    "embedding": {"embedder": "stub"},
    "freshness": {"max_staleness_seconds": 86_400},
    "thresholds": {
        "intent.pass_rate": 1.0,
        "retrieval.recall": 1.0,
        "tool-routing.routing_accuracy": 1.0,
        "groundedness.numeric_facts": 1.0,
    },
}

CASE_0001_FACTS = (
    "86500000",
    "15743000",
    "5200000",
    "61000000",
    "43000000",
    "38000000",
    "0.58",
    "0.97",
    "0.11",
)


class Seed(NamedTuple):
    logical_id: str
    filename: str
    classification: int
    doc_type: str
    section_path: str


SEEDS: tuple[Seed, ...] = (
    Seed("fin-metric-catalog", "fin-metric-catalog.md", 2, "metric_definition", "H2#资产负债率"),
    Seed("ar-aging-policy", "ar-aging-policy.md", 3, "policy", "H2#预警阈值"),
    Seed("fin-warning-policy", "fin-warning-policy.md", 3, "policy", "H2#预警升级"),
    Seed(
        "fin-revenue-recognition-policy",
        "fin-revenue-recognition-policy.md",
        3,
        "policy",
        "H2#收入确认",
    ),
    Seed(
        "fin-monthly-report-2026-10",
        "fin-monthly-report-2026-10.md",
        3,
        "report",
        "H2#经营概况",
    ),
    Seed("fin-exec-compensation", "fin-exec-compensation.md", 4, "policy", "H2#高管薪酬"),
)

_CJK = re.compile(r"[一-鿿]")
_ASCII = re.compile(r"[a-z0-9]+")


def _cjk_tokenize(text: str) -> list[str]:
    """ASCII words plus CJK characters and bigrams for the SQLite fallback."""
    chars = _CJK.findall(text)
    bigrams = [first + second for first, second in itertools.pairwise(chars)]
    return [*_ASCII.findall(text.lower()), *chars, *bigrams]


@pytest.fixture(autouse=True)
def _searchable_chinese(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(bm25_only, "_tokenize", _cjk_tokenize)


class StubLLM:
    """A deterministic generator: the prompt is the answer."""

    name = "stub"
    model_id = "stub@1"

    def generate(self, *, system: str, prompt: str, max_tokens: int = 1024) -> str:
        return prompt


class FixedClock:
    def __init__(self, moment: datetime) -> None:
        self._moment = moment

    def now(self) -> datetime:
        return self._moment


def _viewer() -> Viewer:
    return Viewer(
        user_id=1,
        username="finance-analyst",
        display_name="Finance Analyst",
        must_change_password=False,
        permissions=frozenset(),
    )


async def _seed_document(db: AsyncSession, project: GovProject, seed: Seed) -> None:
    text = (SEED_DIR / seed.filename).read_text(encoding="utf-8")
    suffix = uuid4().hex
    document = Document(
        id=f"doc-{suffix}",
        title=seed.logical_id,
        source_uri=seed.filename,
        mime_type="text/markdown",
        chunker_id="parent-child",
        chunker_config={},
        embedder_id="stub@1.0",
        dim=64,
        version=1,
        status="indexed",
        chunk_count=1,
        logical_id=seed.logical_id,
        classification=seed.classification,
        collection_id=project.collection_id,
        published=True,
        pipeline_run_id=None,
        metadata_json={"doc_type": seed.doc_type, "source_file": seed.filename},
    )
    parent = ChunkParent(
        id=f"parent-{suffix}",
        document_id=document.id,
        ordinal=0,
        text=text,
        metadata_json={"section_path": seed.section_path},
    )
    chunk = Chunk(
        id=f"chunk-{suffix}",
        document_id=document.id,
        ordinal=0,
        text=text,
        search_text=text,
        token_count=max(len(text) // 2, 1),
        metadata_json={"section_path": seed.section_path},
        parent_id=parent.id,
    )
    db.add_all([document, parent, chunk])
    await db.commit()


async def _build_registry(server: MockKingdeeServer) -> ToolRegistry:
    client = McpToolClient(server.in_process_transport())
    await client._validate_allowlist(ALLOWLISTED_TOOLS)
    registry = ToolRegistry()
    for descriptor in await client.list_tools():
        registry.register(McpTool.from_descriptor(client, descriptor))
    register(registry)
    registry.validate()
    return registry


def _bindings(project: GovProject) -> list[GovTool]:
    return [
        GovTool(
            project_id=project.id,
            name=name,
            kind="mcp",
            config_json={},
            schema_json={},
            read_only=True,
            permission_code=None,
            min_clearance=3,
            scope_json={},
            masking_json={},
            result_cap_json={},
            enabled=True,
        )
        for name in ("finance_kpi_snapshot", "finance_receivables_aging")
    ]


async def _ask(
    db: AsyncSession,
    project: GovProject,
    registry: ToolRegistry,
    bindings: Sequence[GovTool],
    question: str,
    *,
    as_of: datetime,
    access: AccessScope,
) -> Any:
    return await answer_question(
        db,
        project=project,
        question=question,
        viewer=_viewer(),
        as_of=as_of,
        llm=StubLLM(),
        rules=FINANCE_RULES,
        rule_version=1,
        tool_bindings=bindings,
        tool_registry=registry,
        access=access,
        reranker=NoopReranker(),
    )


@pytest.fixture()
def scenario_server() -> MockKingdeeServer:
    return MockKingdeeServer(EXAMPLES / "fixtures" / "kingdee", period="2026-10")


@pytest.fixture()
async def finance_project(db_session: AsyncSession) -> GovProject:
    project = await create_project(
        db_session,
        slug="finance-kpi-demo",
        name="Finance KPI Demo",
        approval_mode="hybrid",
        collection_id="finance-kpi",
        config=PROJECT_CONFIG,
    )
    for seed in SEEDS:
        await _seed_document(db_session, project, seed)
    return project


@pytest.fixture()
async def golden_set(db_session: AsyncSession, finance_project: GovProject) -> Any:
    cases = parse_jsonl((EXAMPLES / "golden" / "v1.jsonl").read_text(encoding="utf-8"))
    candidate = await create_candidate_set(
        db_session,
        finance_project.id,
        cases,
        actor="golden-generator",
        source="manual",
    )
    return await confirm_set(db_session, candidate.id, actor="finance-reviewer")


@pytest.fixture()
async def finance_registry(scenario_server: MockKingdeeServer) -> ToolRegistry:
    return await _build_registry(scenario_server)


@pytest.fixture()
def query_runner(
    db_session: AsyncSession,
    finance_project: GovProject,
    finance_registry: ToolRegistry,
):
    bindings = _bindings(finance_project)

    async def run(case: Any, ctx: EvalContext) -> Any:
        assert ctx.access is not None
        answer = await _ask(
            db_session,
            finance_project,
            finance_registry,
            bindings,
            case.question,
            as_of=ctx.reference_time,
            access=ctx.access,
        )
        return answer.observation

    return run


async def _evaluate(
    db: AsyncSession,
    project: GovProject,
    golden: Any,
    runner: Any,
    *,
    clock: Any = None,
) -> Any:
    return await run_evaluation(
        db,
        project=project,
        golden_set=golden,
        rules=FINANCE_RULES,
        evaluators=default_evaluators(),
        query_runner=runner,
        reference_time=REFERENCE,
        rule_version=1,
        stage="baseline",
        actor="acceptance-test",
        clock=clock,
    )


async def test_case_0001_returns_eight_metrics_and_citations(
    db_session: AsyncSession,
    finance_project: GovProject,
    golden_set: Any,
    finance_registry: ToolRegistry,
) -> None:
    cases = {case.id: case for case in await load_cases(db_session, golden_set.id)}
    answer = await _ask(
        db_session,
        finance_project,
        finance_registry,
        _bindings(finance_project),
        cases["case-0001"].question,
        as_of=REFERENCE,
        access=AccessScope(
            collection_id=finance_project.collection_id,
            clearance=4,
            governed=True,
        ),
    )

    assert answer.intent == "financial_overview"
    assert answer.strategy == "agentic"
    assert answer.refused is False
    assert answer.observation.retrieval_calls == 1
    assert {call.name for call in answer.tool_calls} == {
        "finance_kpi_snapshot",
        "finance_receivables_aging",
    }
    for fact in CASE_0001_FACTS:
        assert fact in answer.text, fact
    assert "[tool:finance_kpi_snapshot@2026-10-31]" in answer.text
    assert "[tool:finance_receivables_aging@2026-10-31]" in answer.text
    assert all(call.as_of == CASE_AS_OF for call in answer.tool_calls), (
        "tool results must carry the period cutoff"
    )


async def test_finance_golden_set_passes_all_gates(
    db_session: AsyncSession,
    finance_project: GovProject,
    golden_set: Any,
    query_runner: Any,
) -> None:
    report = await _evaluate(db_session, finance_project, golden_set, query_runner)

    assert report.status == "passed", (
        report.hard_gate_violations,
        report.threshold_failures,
        [
            (case.case_id, case.evaluator, case.violations)
            for case in report.cases
            if case.violations
        ],
    )
    assert report.metrics["intent.pass_rate"] == 1.0
    assert report.metrics["retrieval.recall"] == 1.0
    assert report.metrics["tool-routing.routing_accuracy"] == 1.0
    assert report.metrics["groundedness.numeric_facts"] == 1.0


async def test_leak_probe_at_clearance_2_returns_no_forbidden_source(
    db_session: AsyncSession,
    finance_project: GovProject,
    golden_set: Any,
    query_runner: Any,
) -> None:
    report = await _evaluate(db_session, finance_project, golden_set, query_runner)

    case_results = [case for case in report.cases if case.case_id == "case-0005"]
    assert case_results
    assert all(not case.violations for case in case_results), [
        (case.evaluator, case.violations) for case in case_results
    ]
    leak = next(case for case in case_results if case.evaluator == "access-leak")
    assert leak.skipped is False
    assert leak.passed is True


async def test_shifted_host_clock_produces_identical_report(
    db_session: AsyncSession,
    finance_project: GovProject,
    golden_set: Any,
    query_runner: Any,
) -> None:
    first = await _evaluate(
        db_session,
        finance_project,
        golden_set,
        query_runner,
        clock=FixedClock(REFERENCE - timedelta(hours=36)),
    )
    second = await _evaluate(
        db_session,
        finance_project,
        golden_set,
        query_runner,
        clock=FixedClock(REFERENCE + timedelta(hours=36)),
    )

    assert second.metrics == first.metrics
    assert second.status == first.status == "passed"
