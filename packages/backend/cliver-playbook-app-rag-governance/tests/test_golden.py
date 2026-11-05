"""Golden datasets: JSONL codec, version rules, generation and the API.

The central rule under test is that a confirmed set is immutable. It is
what makes an evaluation report reproducible: the report cites a set
and a version, and those cases must still read the same afterwards.
"""

from __future__ import annotations

import json

import pytest
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from cliver_playbook.app.rag_governance.golden import (
    GoldenCase,
    GoldenGenerationError,
    GoldenValidationError,
    GoldenVersionError,
    confirm_set,
    create_candidate_set,
    dump_jsonl,
    fork_set,
    load_cases,
    parse_generated_cases,
    parse_jsonl,
    update_case,
)
from cliver_playbook.app.rag_governance.models import GovJob


def _case(case_id: str = "case-0001", **overrides: object) -> GoldenCase:
    payload: dict[str, object] = {
        "id": case_id,
        "question": "What was the Q3 2025 revenue?",
        "expected_intent": "financial_metric.query",
        "expected_answer_facts": ["revenue was 1.23 billion CNY"],
        **overrides,
    }
    return GoldenCase.model_validate(payload)


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


def test_jsonl_round_trip() -> None:
    cases = [_case("case-0002"), _case("case-0001")]

    text = dump_jsonl(cases)
    parsed = parse_jsonl(text)

    assert text.endswith("\n")
    assert [case.id for case in parsed] == ["case-0001", "case-0002"]
    assert parsed == sorted(cases, key=lambda case: case.id)


def test_unknown_jsonl_field_is_rejected() -> None:
    payload = _case().model_dump(mode="json")
    payload["expected_source"] = [{"logical_id": "fin-metric-catalog"}]

    with pytest.raises(GoldenValidationError, match="line 1"):
        parse_jsonl(json.dumps(payload))


def test_empty_jsonl_document_is_rejected() -> None:
    with pytest.raises(GoldenValidationError, match="no cases"):
        parse_jsonl("\n\n")


def test_tool_case_requires_a_reference_instant() -> None:
    with pytest.raises(ValidationError, match="as_of is required"):
        _case(expected_tools=["kingdee.profit_report"])


async def test_confirming_a_set_makes_it_immutable(db_session: AsyncSession, project: dict) -> None:
    candidate = await create_candidate_set(db_session, project["id"], [_case()], actor="reviewer")

    confirmed = await confirm_set(db_session, candidate.id, actor="reviewer")

    assert confirmed.status == "confirmed"
    assert confirmed.version == 1
    assert confirmed.confirmed_by == "reviewer"
    with pytest.raises(GoldenVersionError, match="immutable"):
        await update_case(db_session, "case-0001", {"question": "An edit?"})


async def test_editing_a_confirmed_set_creates_version_two(
    db_session: AsyncSession, project: dict
) -> None:
    candidate = await create_candidate_set(db_session, project["id"], [_case()], actor="")
    await confirm_set(db_session, candidate.id, actor="reviewer")

    forked = await fork_set(db_session, candidate.id, actor="reviewer")

    assert forked.version == 2
    assert forked.status == "candidate"
    assert [case.id for case in await load_cases(db_session, forked.id)] == ["case-0001"]

    edited = await update_case(
        db_session,
        "case-0001",
        {"question": "What was the Q3 2025 net profit?"},
        set_id=forked.id,
    )

    assert edited.question == "What was the Q3 2025 net profit?"
    unchanged = await load_cases(db_session, candidate.id)
    assert unchanged[0].question == "What was the Q3 2025 revenue?"


async def test_import_edit_confirm_fork_and_export(client, project: dict) -> None:
    import_response = await client.post(
        f"/api/v1/rag-governance/projects/{project['id']}/golden/import",
        json={"jsonl": dump_jsonl([_case("case-0001"), _case("case-0002")])},
    )
    assert import_response.status_code == 201
    imported = import_response.json()
    assert imported["version"] == 1
    assert imported["status"] == "candidate"
    assert imported["source"] == "import"
    assert [case["id"] for case in imported["cases"]] == ["case-0001", "case-0002"]

    set_id = imported["id"]
    export = await client.get(f"/api/v1/rag-governance/golden/{set_id}/export")
    assert export.status_code == 200
    assert parse_jsonl(export.text) == sorted(
        [_case("case-0001"), _case("case-0002")], key=lambda case: case.id
    )

    update = await client.put(
        f"/api/v1/rag-governance/golden/{set_id}",
        json={"cases": [_case("case-0001", question="Edited question?").model_dump(mode="json")]},
    )
    assert update.status_code == 200
    assert update.json()["cases"][0]["question"] == "Edited question?"

    confirmed = await client.post(f"/api/v1/rag-governance/golden/{set_id}/confirm")
    assert confirmed.status_code == 200
    assert confirmed.json()["status"] == "confirmed"
    assert confirmed.json()["confirmed_by"] == "governance-tester"

    rejected = await client.put(
        f"/api/v1/rag-governance/golden/{set_id}",
        json={"cases": [_case().model_dump(mode="json")]},
    )
    assert rejected.status_code == 409

    forked = await client.post(f"/api/v1/rag-governance/golden/{set_id}/fork")
    assert forked.status_code == 200
    assert forked.json()["version"] == 2
    assert forked.json()["status"] == "candidate"

    listing = await client.get(f"/api/v1/rag-governance/projects/{project['id']}/golden")
    assert [item["version"] for item in listing.json()["items"]] == [2, 1]


async def test_import_of_malformed_jsonl_is_rejected(client, project: dict) -> None:
    response = await client.post(
        f"/api/v1/rag-governance/projects/{project['id']}/golden/import",
        json={"jsonl": '{"id": "case-0001", "question": "Q?", "expected_intent": "x", "typo": 1}'},
    )

    assert response.status_code == 422
    assert "typo" in response.json()["detail"]


async def test_generate_enqueues_a_job(client, db_session: AsyncSession, project: dict) -> None:
    response = await client.post(
        f"/api/v1/rag-governance/projects/{project['id']}/golden/generate",
        json={"scenario": "financial metrics", "max_cases": 3},
    )

    assert response.status_code == 202
    accepted = response.json()
    assert accepted["kind"] == "generate_golden"
    assert accepted["status"] == "queued"
    job = await db_session.get(GovJob, accepted["job_id"])
    assert job is not None
    assert job.project_id == project["id"]
    assert job.payload_json["max_cases"] == 3
    assert job.payload_json["scenario"] == "financial metrics"


async def test_golden_endpoints_require_authentication(raw_client) -> None:
    response = await raw_client.get("/api/v1/rag-governance/golden/missing")
    assert response.status_code == 401


async def test_unknown_golden_set_is_404(client) -> None:
    response = await client.get("/api/v1/rag-governance/golden/does-not-exist")
    assert response.status_code == 404


def test_generated_cases_without_ids_are_numbered() -> None:
    raw = (
        "```json\n"
        '[{"question": "What was the Q3 revenue?", "expected_intent": "financial_metric.query"}]\n'
        "```"
    )

    cases = parse_generated_cases(raw)

    assert [case.id for case in cases] == ["case-0001"]


def test_generator_rejects_prose() -> None:
    with pytest.raises(GoldenGenerationError, match="did not return JSON"):
        parse_generated_cases("Here are three great test cases for you.")


def test_generator_rejects_duplicate_ids() -> None:
    raw = json.dumps(
        [
            {"id": "case-0001", "question": "Q1?", "expected_intent": "intent"},
            {"id": "case-0001", "question": "Q2?", "expected_intent": "intent"},
        ]
    )

    with pytest.raises(GoldenGenerationError, match="duplicate case id"):
        parse_generated_cases(raw)
