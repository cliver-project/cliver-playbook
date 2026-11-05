"""Intent rules: matching, scope compilation, versioning and activation.

The activation gate is the heart of this task: a rule version becomes
active only with a passing evaluation run that tested the project's
current confirmed golden set.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from cliver_playbook.app.rag.filters import And, Or, compile_filter
from cliver_playbook.app.rag_governance.golden import (
    GoldenCase,
    confirm_set,
    create_candidate_set,
    fork_set,
)
from cliver_playbook.app.rag_governance.models import GovEvalRun, GovProject
from cliver_playbook.app.rag_governance.rules import (
    IntentMatch,
    IntentRule,
    KeywordRegexClassifier,
    RuleActivationError,
    RuleCompileError,
    activate_rule_set,
    active_rule_set,
    compile_rule_scope,
    compose_scope,
    create_rule_set,
    fallback_rule,
    get_rule_set,
)
from cliver_playbook.app.rag_governance.services import projects as project_service


def _overview_rule(**overrides: object) -> IntentRule:
    payload: dict[str, object] = {
        "intent": "financial_overview",
        "description": "Questions about revenue, gross margin and profit.",
        "priority": 100,
        "classifier": {
            "kind": "keyword-regex",
            "config": {
                "keywords": ["revenue", "gross margin", "profit"],
                "threshold": 0.5,
            },
        },
        "scope": {
            "and": [
                {"field": "doc_type", "op": "in", "value": ["metric", "policy"]},
                {"field": "classification", "op": "lte", "value": 3},
            ]
        },
        "strategy": "retrieval",
    }
    payload.update(overrides)
    return IntentRule.model_validate(payload)


def _match(rule: IntentRule, confidence: float = 0.5) -> IntentMatch:
    return IntentMatch(intent=rule.intent, confidence=confidence, rule=rule)


def _golden_case() -> GoldenCase:
    return GoldenCase(
        id="case-0001",
        question="What was the Q3 revenue?",
        expected_intent="financial_overview",
        expected_answer_facts=["revenue was 1.23 billion CNY"],
    )


async def _project(db: AsyncSession) -> GovProject:
    return await project_service.create_project(db, slug="finance-kpi-demo", name="Finance KPI")


async def _confirmed_set(db: AsyncSession, project_id: str):
    candidate = await create_candidate_set(db, project_id, [_golden_case()], actor="tester")
    return await confirm_set(db, candidate.id, actor="reviewer")


async def _run(
    db: AsyncSession,
    project_id: str,
    golden_set_id: str,
    *,
    status: str = "passed",
) -> GovEvalRun:
    run = GovEvalRun(
        project_id=project_id,
        golden_set_id=golden_set_id,
        stage="baseline",
        status=status,
    )
    db.add(run)
    await db.commit()
    await db.refresh(run)
    return run


@pytest.fixture()
async def project(client) -> dict:
    response = await client.post(
        "/api/v1/rag-governance/projects",
        json={
            "slug": "finance-kpi-demo",
            "name": "Finance KPI",
            "approval_mode": "manual",
        },
    )
    assert response.status_code == 201
    return response.json()


def test_keyword_rule_matches_and_scores() -> None:
    matches = KeywordRegexClassifier().classify(
        "What were revenue and gross margin this month?",
        [_overview_rule()],
        config={},
    )

    assert matches[0].intent == "financial_overview"
    assert matches[0].confidence > 0.5


def test_scope_compiles_to_rag_filter_ast() -> None:
    node = compile_rule_scope(_overview_rule())

    assert isinstance(node, And)
    assert compile_filter(node) is not None


def test_empty_scope_means_no_rule_filter() -> None:
    assert compile_rule_scope(_overview_rule(scope={})) is None


def test_unknown_scope_field_is_rejected() -> None:
    rule = _overview_rule(scope={"field": "domain", "op": "eq", "value": "finance"})

    with pytest.raises(RuleCompileError, match="unknown filter field"):
        compile_rule_scope(rule)


def test_none_strategy_requires_a_refusal_message() -> None:
    with pytest.raises(ValidationError, match="requires a refusal message"):
        _overview_rule(strategy="none")


def test_tool_strategy_requires_at_least_one_tool() -> None:
    with pytest.raises(ValidationError, match="requires at least one tool"):
        _overview_rule(strategy="tools", tools=[])


def test_equal_priority_matches_union_their_scopes() -> None:
    first = _overview_rule(intent="first", scope={"field": "doc_type", "op": "eq", "value": "faq"})
    second = _overview_rule(
        intent="second", scope={"field": "doc_type", "op": "eq", "value": "sop"}
    )
    lower = _overview_rule(
        intent="lower", priority=50, scope={"field": "doc_type", "op": "eq", "value": "policy"}
    )

    node = compose_scope([_match(first), _match(second), _match(lower)])

    assert isinstance(node, Or)
    assert len(node.children) == 2


def test_intersection_combines_every_match() -> None:
    first = _overview_rule(intent="first", scope={"field": "doc_type", "op": "eq", "value": "faq"})
    second = _overview_rule(
        intent="second", scope={"field": "doc_type", "op": "eq", "value": "sop"}
    )

    node = compose_scope([_match(first), _match(second)], scope_combination="intersection")

    assert isinstance(node, And)
    assert len(node.children) == 2


def test_fallback_rule_is_the_lowest_priority_one() -> None:
    low = _overview_rule(intent="fallback", priority=1)
    high = _overview_rule(intent="fallback", priority=1000)

    selected = fallback_rule([high, low])

    assert selected is not None
    assert selected.priority == 1


async def test_activation_requires_a_passing_eval_run(db_session: AsyncSession) -> None:
    project = await _project(db_session)

    with pytest.raises(RuleActivationError, match="passing evaluation run"):
        await activate_rule_set(
            db_session, project.id, [_overview_rule()], eval_run_id=None, actor="u"
        )


async def test_activation_rejects_a_failed_run(db_session: AsyncSession) -> None:
    project = await _project(db_session)
    golden_set = await _confirmed_set(db_session, project.id)
    run = await _run(db_session, project.id, golden_set.id, status="failed")

    with pytest.raises(RuleActivationError, match="only a passing run"):
        await activate_rule_set(
            db_session, project.id, [_overview_rule()], eval_run_id=run.id, actor="u"
        )


async def test_activation_rejects_a_run_from_another_project(
    db_session: AsyncSession,
) -> None:
    project = await _project(db_session)
    other = await project_service.create_project(db_session, slug="another", name="Another")
    other_set = await _confirmed_set(db_session, other.id)
    run = await _run(db_session, other.id, other_set.id)

    with pytest.raises(RuleActivationError, match="another project"):
        await activate_rule_set(
            db_session, project.id, [_overview_rule()], eval_run_id=run.id, actor="u"
        )


async def test_activation_rejects_a_stale_golden_set(db_session: AsyncSession) -> None:
    project = await _project(db_session)
    first = await _confirmed_set(db_session, project.id)
    run = await _run(db_session, project.id, first.id)
    forked = await fork_set(db_session, first.id, actor="u")
    await confirm_set(db_session, forked.id, actor="u")

    with pytest.raises(RuleActivationError, match="current confirmed golden set"):
        await activate_rule_set(
            db_session, project.id, [_overview_rule()], eval_run_id=run.id, actor="u"
        )


async def test_proposed_rules_do_not_serve_queries(db_session: AsyncSession) -> None:
    project = await _project(db_session)

    proposed = await create_rule_set(db_session, project.id, [_overview_rule()], actor="author")

    assert proposed.status == "proposed"
    assert proposed.version == 1
    assert await active_rule_set(db_session, project.id) is None


async def test_activation_archives_the_previous_version(
    db_session: AsyncSession,
) -> None:
    project = await _project(db_session)
    golden_set = await _confirmed_set(db_session, project.id)
    first_run = await _run(db_session, project.id, golden_set.id)

    first = await activate_rule_set(
        db_session,
        project.id,
        [_overview_rule()],
        eval_run_id=first_run.id,
        actor="reviewer",
    )

    second_run = await _run(db_session, project.id, golden_set.id)
    changed = _overview_rule(priority=120)
    second = await activate_rule_set(
        db_session,
        project.id,
        [changed],
        eval_run_id=second_run.id,
        actor="reviewer",
    )

    assert first.version == 1
    assert second.version == 2
    active = await active_rule_set(db_session, project.id)
    assert active is not None
    assert active.version == 2
    assert active.status == "active"
    assert active.rules[0].priority == 120
    archived = await get_rule_set(db_session, project.id, 1)
    assert archived is not None
    assert archived.status == "archived"
    await db_session.refresh(second_run)
    assert second_run.rule_version == 2


async def test_api_propose_preview_and_activate(
    client, db_session: AsyncSession, project: dict
) -> None:
    rule = _overview_rule().model_dump(mode="json")

    proposed = await client.post(
        f"/api/v1/rag-governance/projects/{project['id']}/rules/propose",
        json={"rules": [rule]},
    )
    assert proposed.status_code == 201
    assert proposed.json()["version"] == 1
    assert proposed.json()["status"] == "proposed"

    active = await client.get(f"/api/v1/rag-governance/projects/{project['id']}/rules")
    assert active.status_code == 200
    assert active.json()["version"] is None
    assert active.json()["rules"] == []

    versions = await client.get(f"/api/v1/rag-governance/projects/{project['id']}/rules/versions")
    assert [item["version"] for item in versions.json()["items"]] == [1]

    preview = await client.post(
        f"/api/v1/rag-governance/projects/{project['id']}/rules/preview",
        json={
            "question": "What were revenue and gross margin this month?",
            "rules": [rule],
        },
    )
    assert preview.status_code == 200
    assert preview.json()["matches"][0]["intent"] == "financial_overview"

    golden_set = await _confirmed_set(db_session, project["id"])
    run = await _run(db_session, project["id"], golden_set.id)

    activated = await client.post(
        f"/api/v1/rag-governance/projects/{project['id']}/rules/activate",
        json={"rules": [rule], "eval_run_id": run.id},
    )
    assert activated.status_code == 200
    assert activated.json()["status"] == "active"
    assert activated.json()["version"] == 2

    active = await client.get(f"/api/v1/rag-governance/projects/{project['id']}/rules")
    assert active.json()["version"] == 2
    assert active.json()["rules"][0]["intent"] == "financial_overview"


async def test_api_rejects_an_invalid_scope(client, project: dict) -> None:
    rule = _overview_rule(scope={"field": "unknown", "op": "eq", "value": 1})

    response = await client.post(
        f"/api/v1/rag-governance/projects/{project['id']}/rules/propose",
        json={"rules": [rule.model_dump(mode="json")]},
    )

    assert response.status_code == 422
    assert "unknown filter field" in response.json()["detail"]


async def test_api_activation_with_a_failed_run_is_409(
    client, db_session: AsyncSession, project: dict
) -> None:
    golden_set = await _confirmed_set(db_session, project["id"])
    run = await _run(db_session, project["id"], golden_set.id, status="failed")

    response = await client.post(
        f"/api/v1/rag-governance/projects/{project['id']}/rules/activate",
        json={
            "rules": [_overview_rule().model_dump(mode="json")],
            "eval_run_id": run.id,
        },
    )

    assert response.status_code == 409
    assert "only a passing run" in response.json()["detail"]


async def test_rules_endpoints_require_authentication(raw_client) -> None:
    response = await raw_client.get("/api/v1/rag-governance/projects/x/rules")
    assert response.status_code == 401
