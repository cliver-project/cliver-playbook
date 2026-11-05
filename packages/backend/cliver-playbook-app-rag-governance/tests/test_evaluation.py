"""Evaluation: evaluator behaviour, the runner and the HTTP surface."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from cliver_playbook.app.rag_governance.evaluation import (
    AccessLeakEvaluator,
    ContextualizationEvaluator,
    EvalContext,
    FreshnessEvaluator,
    GroundednessEvaluator,
    IntentEvaluator,
    MaskingLeakEvaluator,
    ObservedCitation,
    ObservedSource,
    ObservedToolCall,
    QueryObservation,
    RetrievalEvaluator,
    ToolRoutingEvaluator,
    run_evaluation,
)
from cliver_playbook.app.rag_governance.golden import (
    ExpectedSource,
    GoldenCase,
    confirm_set,
    create_candidate_set,
    load_cases,
)
from cliver_playbook.app.rag_governance.models import GovEvalCaseResult, GovEvalRun
from cliver_playbook.app.rag_governance.services import projects as project_service

SHANGHAI = ZoneInfo("Asia/Shanghai")


def _case(**overrides: object) -> GoldenCase:
    payload: dict[str, object] = {
        "id": "case-0001",
        "question": "What was the Q3 revenue?",
        "expected_intent": "financial_overview",
        "expected_answer_facts": ["revenue was 1230 million CNY"],
    }
    payload.update(overrides)
    return GoldenCase.model_validate(payload)


def _project(config: dict | None = None):
    return SimpleNamespace(id="project-1", collection_id="finance", config_json=config or {})


def _ctx(
    *,
    observation: QueryObservation | None = None,
    probe_observation: QueryObservation | None = None,
    reference_time: datetime | None = None,
    config: dict | None = None,
    judge=None,
) -> EvalContext:
    return EvalContext(
        project=_project(config),
        golden_set=None,
        rules=(),
        reference_time=reference_time or datetime(2026, 11, 1, tzinfo=SHANGHAI),
        observation=observation,
        probe_observation=probe_observation,
        config=config or {},
        judge=judge,
    )


class RecordingRunner:
    def __init__(
        self,
        primary: QueryObservation,
        probe: QueryObservation | None = None,
    ) -> None:
        self.primary = primary
        self.probe = probe
        self.calls: list[int] = []

    async def __call__(self, case: GoldenCase, ctx: EvalContext) -> QueryObservation:
        assert ctx.access is not None
        self.calls.append(ctx.access.clearance)
        return self.probe if ctx.access.clearance == case.leak_probe_clearance else self.primary


class FixedClock:
    def __init__(self, moment: datetime) -> None:
        self.moment = moment

    def now(self) -> datetime:
        return self.moment


async def _project_row(db: AsyncSession):
    return await project_service.create_project(db, slug="finance-kpi-demo", name="Finance KPI")


async def _confirmed_set(db: AsyncSession, project_id: str, cases: list[GoldenCase]):
    candidate = await create_candidate_set(db, project_id, cases, actor="tester")
    return await confirm_set(db, candidate.id, actor="reviewer")


async def test_none_strategy_case_requires_zero_retrieval_and_tools() -> None:
    refusal = _case(id="case-refusal", tags=["refusal"])
    observation = QueryObservation(strategy="retrieval", retrieval_calls=1)

    result = await ToolRoutingEvaluator().evaluate(refusal, _ctx(observation=observation))

    assert not result.passed
    assert any("retrieval" in violation for violation in result.violations)


async def test_freshness_uses_injected_reference_time_not_host_clock() -> None:
    case = _case(
        expected_tools=["kingdee.profit_report"],
        as_of=datetime(2026, 11, 1, tzinfo=SHANGHAI),
    )
    observation = QueryObservation(
        strategy="tools",
        answer="Revenue was 1230 million CNY",
        tool_calls=(
            ObservedToolCall(
                name="kingdee.profit_report",
                as_of=datetime(2026, 10, 30, tzinfo=SHANGHAI),
            ),
        ),
    )

    result = await FreshnessEvaluator().evaluate(
        case,
        _ctx(
            observation=observation,
            reference_time=datetime(2026, 11, 1, tzinfo=SHANGHAI),
            config={"freshness": {"max_staleness_seconds": 3600}},
        ),
    )

    assert not result.passed


async def test_access_leak_probe_never_returns_forbidden_source() -> None:
    case = _case(
        id="case-0005",
        leak_probe_clearance=2,
        forbidden_sources=["fin-exec-compensation"],
    )
    observation = QueryObservation(
        sources=(ObservedSource(logical_id="fin-exec-compensation", classification=2),)
    )

    result = await AccessLeakEvaluator().evaluate(
        case, _ctx(observation=observation, probe_observation=observation)
    )

    assert not result.passed
    assert result.violations == ["fin-exec-compensation"]


async def test_null_classification_is_a_hard_access_violation() -> None:
    case = _case(leak_probe_clearance=5)
    observation = QueryObservation(
        sources=(ObservedSource(logical_id="fin-unclassified", classification=None),)
    )

    result = await AccessLeakEvaluator().evaluate(
        case, _ctx(observation=observation, probe_observation=observation)
    )

    assert not result.passed
    assert any("unclassified" in violation for violation in result.violations)


async def test_intent_evaluator_compares_the_expected_intent() -> None:
    observation = QueryObservation(intent="financial_overview")

    passed = await IntentEvaluator().evaluate(_case(), _ctx(observation=observation))
    failed = await IntentEvaluator().evaluate(
        _case(), _ctx(observation=QueryObservation(intent="logistics"))
    )

    assert passed.passed
    assert not failed.passed
    assert failed.metrics["accuracy"] == 0.0


async def test_retrieval_recall_and_mrr() -> None:
    case = _case(expected_sources=[ExpectedSource(logical_id="fin-metric-catalog")])
    observation = QueryObservation(sources=(ObservedSource(logical_id="fin-metric-catalog"),))

    result = await RetrievalEvaluator().evaluate(case, _ctx(observation=observation))

    assert result.passed
    assert result.metrics["recall"] == 1.0
    assert result.metrics["mrr"] == 1.0


async def test_retrieval_reports_a_missing_source() -> None:
    case = _case(expected_sources=[ExpectedSource(logical_id="fin-metric-catalog")])

    result = await RetrievalEvaluator().evaluate(
        case, _ctx(observation=QueryObservation(sources=()))
    )

    assert not result.passed
    assert "fin-metric-catalog" in result.violations[0]


async def test_groundedness_matches_numbers_within_tolerance() -> None:
    case = _case(expected_sources=[ExpectedSource(logical_id="fin-metric-catalog")])
    observation = QueryObservation(
        answer="Revenue was 1,230 million CNY",
        sources=(ObservedSource(logical_id="fin-metric-catalog"),),
        citations=(ObservedCitation(kind="document", ref="fin-metric-catalog"),),
    )

    result = await GroundednessEvaluator().evaluate(case, _ctx(observation=observation))

    assert result.passed
    assert result.metrics["numeric_facts"] == 1.0


async def test_groundedness_rejects_a_numeric_mismatch_and_invented_citation() -> None:
    case = _case(expected_sources=[ExpectedSource(logical_id="fin-metric-catalog")])
    observation = QueryObservation(
        answer="Revenue was 1,100 million CNY",
        sources=(ObservedSource(logical_id="fin-metric-catalog"),),
        citations=(ObservedCitation(kind="document", ref="invented-doc"),),
    )

    result = await GroundednessEvaluator().evaluate(case, _ctx(observation=observation))

    assert not result.passed
    assert any("1230" in violation for violation in result.violations)
    assert any("invented-doc" in violation for violation in result.violations)


async def test_write_tool_is_a_hard_routing_violation() -> None:
    case = _case(
        expected_tools=["kingdee.profit_report"],
        as_of=datetime(2026, 11, 1, tzinfo=SHANGHAI),
    )
    observation = QueryObservation(
        strategy="tools",
        tool_calls=(
            ObservedToolCall(
                name="kingdee.profit_report",
                as_of=datetime(2026, 11, 1, tzinfo=SHANGHAI),
                read_only=False,
            ),
        ),
    )

    result = await ToolRoutingEvaluator().evaluate(case, _ctx(observation=observation))

    assert not result.passed
    assert any("write tool" in violation for violation in result.hard_violations)


async def test_tool_arguments_and_as_of_are_checked() -> None:
    reference = datetime(2026, 11, 1, tzinfo=SHANGHAI)
    case = _case(
        expected_tools=["kingdee.profit_report"],
        expected_tool_args={"kingdee.profit_report": {"period": "2026-09"}},
        as_of=reference,
    )
    observation = QueryObservation(
        strategy="tools",
        tool_calls=(
            ObservedToolCall(
                name="kingdee.profit_report",
                args={"period": "2026-08"},
                as_of=reference,
            ),
        ),
    )

    result = await ToolRoutingEvaluator().evaluate(case, _ctx(observation=observation))

    assert not result.passed
    assert any("2026-08" in violation for violation in result.violations)


async def test_masking_leak_scans_the_whole_trace() -> None:
    observation = QueryObservation(
        answer="Call 13800138000 for the report",
        contexts=("contact: finance@example.com",),
    )

    result = await MaskingLeakEvaluator().evaluate(_case(), _ctx(observation=observation))

    assert not result.passed
    assert any("phone" in violation for violation in result.violations)
    assert any("email" in violation for violation in result.violations)


async def test_contextualization_warns_by_default_and_gates_when_configured() -> None:
    observation = QueryObservation(
        contextual_pairs=(("Revenue grew.", "Revenue grew to 12 billion."),)
    )

    async def judge(parent: str, contextual: str) -> bool:
        return False

    warning = await ContextualizationEvaluator().evaluate(
        _case(), _ctx(observation=observation, judge=judge)
    )
    gated = await ContextualizationEvaluator().evaluate(
        _case(),
        _ctx(observation=observation, judge=judge, config={"contextualization": {"gate": True}}),
    )

    assert warning.passed
    assert warning.violations
    assert not gated.passed


def _passing_observation(case: GoldenCase) -> QueryObservation:
    expected_sources = tuple(
        ObservedSource(logical_id=source.logical_id, classification=1)
        for source in case.expected_sources
    )
    citations = tuple(
        ObservedCitation(kind="document", ref=source.logical_id) for source in case.expected_sources
    )
    return QueryObservation(
        question=case.question,
        intent=case.expected_intent,
        strategy="retrieval",
        answer="Revenue was 1,230 million CNY",
        sources=expected_sources,
        citations=citations,
    )


def _suite() -> list:
    return [
        IntentEvaluator(),
        RetrievalEvaluator(),
        GroundednessEvaluator(),
        ToolRoutingEvaluator(),
        FreshnessEvaluator(),
        MaskingLeakEvaluator(),
        AccessLeakEvaluator(),
    ]


async def test_runner_persists_a_passing_report(db_session: AsyncSession) -> None:
    project = await _project_row(db_session)
    golden_set = await _confirmed_set(
        db_session,
        project.id,
        [_case(expected_sources=[ExpectedSource(logical_id="fin-metric-catalog")])],
    )
    case = (await load_cases(db_session, golden_set.id))[0]
    runner = RecordingRunner(_passing_observation(case))

    report = await run_evaluation(
        db_session,
        project=project,
        golden_set=golden_set,
        rules=[],
        evaluators=_suite(),
        query_runner=runner,
        reference_time=datetime(2026, 11, 1, tzinfo=SHANGHAI),
    )

    assert report.status == "passed"
    assert report.metrics["intent.pass_rate"] == 1.0
    run = await db_session.get(GovEvalRun, report.run_id)
    assert run is not None
    assert run.status == "passed"
    stored = (await db_session.execute(select(GovEvalCaseResult))).scalars().all()
    assert [result.passed for result in stored] == [True]


async def test_runner_fails_on_a_threshold_miss(db_session: AsyncSession) -> None:
    project = await _project_row(db_session)
    golden_set = await _confirmed_set(db_session, project.id, [_case()])
    case = (await load_cases(db_session, golden_set.id))[0]
    observation = replace(_passing_observation(case), intent="wrong_intent")

    report = await run_evaluation(
        db_session,
        project=project,
        golden_set=golden_set,
        rules=[],
        evaluators=_suite(),
        query_runner=RecordingRunner(observation),
        reference_time=datetime(2026, 11, 1, tzinfo=SHANGHAI),
        thresholds={"intent": 1.0},
    )

    assert report.status == "failed"
    assert report.threshold_failures


async def test_runner_fails_on_a_hard_gate(db_session: AsyncSession) -> None:
    project = await _project_row(db_session)
    golden_set = await _confirmed_set(db_session, project.id, [_case()])
    case = (await load_cases(db_session, golden_set.id))[0]
    observation = QueryObservation(
        question=case.question,
        intent=case.expected_intent,
        answer="Call 13800138000 for revenue",
    )

    report = await run_evaluation(
        db_session,
        project=project,
        golden_set=golden_set,
        rules=[],
        evaluators=_suite(),
        query_runner=RecordingRunner(observation),
        reference_time=datetime(2026, 11, 1, tzinfo=SHANGHAI),
    )

    assert report.status == "failed"
    assert any("masking-leak" in violation for violation in report.hard_gate_violations)


async def test_runner_replays_the_leak_probe(db_session: AsyncSession) -> None:
    project = await _project_row(db_session)
    golden_set = await _confirmed_set(
        db_session,
        project.id,
        [
            _case(
                run_as_clearance=4,
                leak_probe_clearance=2,
                forbidden_sources=["fin-exec-compensation"],
            )
        ],
    )
    case = (await load_cases(db_session, golden_set.id))[0]
    primary = QueryObservation(
        question=case.question,
        intent=case.expected_intent,
        answer="Revenue was 1,230 million CNY",
    )
    probe = QueryObservation(
        answer="Revenue was 1,230 million CNY",
        sources=(ObservedSource(logical_id="fin-exec-compensation", classification=1),),
    )
    runner = RecordingRunner(primary, probe)

    report = await run_evaluation(
        db_session,
        project=project,
        golden_set=golden_set,
        rules=[],
        evaluators=_suite(),
        query_runner=runner,
        reference_time=datetime(2026, 11, 1, tzinfo=SHANGHAI),
    )

    assert runner.calls == [4, 2]
    assert report.status == "failed"
    assert any("fin-exec-compensation" in violation for violation in report.hard_gate_violations)


async def test_host_clock_does_not_change_the_metrics(db_session: AsyncSession) -> None:
    project = await _project_row(db_session)
    golden_set = await _confirmed_set(
        db_session,
        project.id,
        [_case(as_of=datetime(2026, 11, 1, tzinfo=SHANGHAI))],
    )
    case = (await load_cases(db_session, golden_set.id))[0]
    observation = _passing_observation(case)
    reference = datetime(2026, 11, 1, tzinfo=SHANGHAI)

    first = await run_evaluation(
        db_session,
        project=project,
        golden_set=golden_set,
        rules=[],
        evaluators=_suite(),
        query_runner=RecordingRunner(observation),
        reference_time=reference,
        clock=FixedClock(reference - timedelta(hours=36)),
    )
    second = await run_evaluation(
        db_session,
        project=project,
        golden_set=golden_set,
        rules=[],
        evaluators=_suite(),
        query_runner=RecordingRunner(observation),
        reference_time=reference,
        clock=FixedClock(reference + timedelta(hours=36)),
    )

    assert first.status == second.status
    assert first.metrics == second.metrics


@pytest.fixture()
async def project(client) -> dict:
    response = await client.post(
        "/api/v1/rag-governance/projects",
        json={"slug": "finance-kpi-demo", "name": "Finance KPI", "approval_mode": "manual"},
    )
    assert response.status_code == 201
    return response.json()


async def test_api_starts_an_evaluation_job(
    client, db_session: AsyncSession, project: dict
) -> None:
    golden_set = await _confirmed_set(db_session, project["id"], [_case()])

    response = await client.post(
        f"/api/v1/rag-governance/projects/{project['id']}/evaluations",
        json={"golden_set_id": golden_set.id},
    )

    assert response.status_code == 202
    assert response.json()["kind"] == "run_eval"
    assert response.json()["status"] == "queued"


async def test_api_rejects_an_unconfirmed_set(
    client, db_session: AsyncSession, project: dict
) -> None:
    candidate = await create_candidate_set(db_session, project["id"], [_case()], actor="tester")

    response = await client.post(
        f"/api/v1/rag-governance/projects/{project['id']}/evaluations",
        json={"golden_set_id": candidate.id},
    )

    assert response.status_code == 409


async def test_api_lists_runs_and_returns_case_details(
    client, db_session: AsyncSession, project: dict
) -> None:
    golden_set = await _confirmed_set(db_session, project["id"], [_case()])
    run = GovEvalRun(
        project_id=project["id"],
        golden_set_id=golden_set.id,
        stage="baseline",
        status="passed",
        metrics_json={"intent.pass_rate": 1.0},
        report_json={"summary": "1/1 cases passed"},
    )
    db_session.add(run)
    await db_session.flush()
    db_session.add(
        GovEvalCaseResult(
            run_id=run.id,
            case_id="case-0001",
            passed=True,
            details_json={"results": []},
        )
    )
    await db_session.commit()

    listing = await client.get(f"/api/v1/rag-governance/projects/{project['id']}/evaluations")
    assert [item["id"] for item in listing.json()["items"]] == [run.id]

    detail = await client.get(f"/api/v1/rag-governance/evaluations/{run.id}")
    assert detail.status_code == 200
    assert detail.json()["summary"] == "1/1 cases passed"
    assert detail.json()["cases"][0]["case_id"] == "case-0001"


async def test_evaluation_endpoints_require_authentication(raw_client) -> None:
    response = await raw_client.get("/api/v1/rag-governance/evaluations/x")
    assert response.status_code == 401
