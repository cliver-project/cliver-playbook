"""The canonical job handlers: ingest, evaluate, generate.

These run the real domain code against the test database — the ingestion
pipeline, the evaluation runner, the golden generator — so what is pinned
here is the orchestration contract: payload shape, state transitions and
the stats the API surfaces. Domain correctness lives in the domain tests.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from cliver_playbook.app.basic import runtime
from cliver_playbook.app.rag.models.entities import Document
from cliver_playbook.app.rag_governance.models import GovIngestBatch, GovJob
from cliver_playbook.app.rag_governance.models.entities import GovProject
from cliver_playbook.app.rag_governance.runtime import enqueue, run_worker
from cliver_playbook.app.rag_governance.runtime.handlers import (
    JOB_HANDLERS,
    run_generate_golden,
    run_ingest_batch,
)
from cliver_playbook.app.rag_governance.services.projects import create_project
from cliver_playbook.app.rag_governance.services.sources import create_source
from cliver_playbook.app.rag_governance.stages import ParsedBlock, ParsedDocument, ParserOptions
from cliver_playbook.app.rag_governance.stages.base import SourceDocument
from cliver_playbook.app.rag_governance.stages.parser import parsers

EXAMPLES = Path(__file__).resolve().parents[1] / "examples" / "finance_kpi"
SEED_DIR = EXAMPLES / "seed"


class _StubLLM:
    """Returns one canned JSON array of cases, like the real generator."""

    def generate(self, *, system: str, prompt: str, max_tokens: int = 1024) -> str:
        return json.dumps(
            [
                {
                    "id": "case-gen-1",
                    "question": "What is the revenue recognition policy?",
                    "expected_intent": "policy_question",
                }
            ]
        )


async def _project(db: AsyncSession) -> GovProject:
    return await create_project(
        db,
        slug="handlers",
        name="Handlers",
        config={
            "embedding": {"embedder": "stub"},
            "retrieval": {"mode": "sparse", "reranker": "noop"},
        },
    )


async def test_ingest_batch_handler_stages_documents(db_session: AsyncSession) -> None:
    project = await _project(db_session)
    source = await create_source(
        db_session,
        project,
        kind="directory",
        config={"path": str(SEED_DIR), "extensions": [".md"]},
    )
    batch = GovIngestBatch(project_id=project.id, source_id=source.id, status="queued")
    db_session.add(batch)
    await db_session.flush()
    job = await enqueue(
        db_session,
        project_id=project.id,
        kind="ingest_batch",
        payload={"batch_id": batch.id, "source_id": source.id},
    )

    result = await run_ingest_batch(db_session, job)
    await db_session.commit()

    stored = await db_session.get(GovIngestBatch, batch.id)
    assert stored is not None
    assert stored.status == "staged"
    assert stored.stats_json["documents"] == len(list(Path(SEED_DIR).glob("*.md"))) > 0
    assert stored.stats_json["chunks"] > 0
    assert result["batch_id"] == batch.id


class _ConfiguredParser:
    name = "handler-test"
    version = "1"
    options_model = ParserOptions

    def parse(self, document: SourceDocument, options=None) -> ParsedDocument:
        del document, options
        return ParsedDocument(blocks=[ParsedBlock(kind="text", text="configured output")])


async def test_ingest_batch_handler_uses_the_configured_parser(
    db_session: AsyncSession, tmp_path
) -> None:
    if "handler-test" not in parsers.names():
        parsers.register("handler-test", _ConfiguredParser)
    (tmp_path / "doc.md").write_text("ignored by the configured parser", encoding="utf-8")
    project = await create_project(
        db_session,
        slug="configured-parser",
        name="Configured parser",
        config={
            "embedding": {"embedder": "stub"},
            "parsing": {"parser": "handler-test"},
        },
    )
    source = await create_source(
        db_session,
        project,
        kind="directory",
        config={"path": str(tmp_path), "extensions": [".md"]},
    )
    batch = GovIngestBatch(project_id=project.id, source_id=source.id, status="queued")
    db_session.add(batch)
    await db_session.flush()
    job = await enqueue(
        db_session,
        project_id=project.id,
        kind="ingest_batch",
        payload={"batch_id": batch.id, "source_id": source.id},
    )

    await run_ingest_batch(db_session, job)
    await db_session.commit()

    document = await db_session.scalar(select(Document).where(Document.logical_id == "doc"))
    assert document is not None
    assert document.metadata_json["parser_id"] == "handler-test@1"


async def test_ingest_batch_handler_fails_cleanly_for_a_missing_batch(
    db_session: AsyncSession,
) -> None:
    job = await enqueue(
        db_session,
        project_id="p",
        kind="ingest_batch",
        payload={"batch_id": "nope", "source_id": "nope"},
    )
    try:
        await run_ingest_batch(db_session, job)
    except LookupError:
        pass
    else:
        raise AssertionError("missing rows must fail the job, not pass silently")


async def test_generate_golden_handler_writes_a_candidate_set(
    db_session: AsyncSession, monkeypatch
) -> None:
    project = await _project(db_session)
    await create_source(
        db_session,
        project,
        kind="directory",
        config={"path": str(SEED_DIR), "extensions": [".md"]},
    )
    job = await enqueue(
        db_session,
        project_id=project.id,
        kind="generate_golden",
        payload={"project_id": project.id, "scenario": "", "max_cases": 5},
    )

    # The LLM seam is stubbed; everything else runs for real.
    from cliver_playbook.app.rag_governance.runtime import handlers

    monkeypatch.setattr(handlers, "get_llm", lambda name: _StubLLM())

    result = await run_generate_golden(db_session, job)
    await db_session.commit()

    from cliver_playbook.app.rag_governance.golden.versions import get_set

    golden_set = await get_set(db_session, result["golden_set_id"])
    assert golden_set is not None
    assert golden_set.status == "candidate"
    assert golden_set.source == "llm"
    assert result["cases"] == 1


async def test_run_worker_drains_the_queue_with_the_canonical_handlers(
    db_session: AsyncSession,
) -> None:
    """End to end: enqueue through the API's shapes, drain, verify states."""
    project = await _project(db_session)
    source = await create_source(
        db_session,
        project,
        kind="directory",
        config={"path": str(SEED_DIR), "extensions": [".md"]},
    )
    batch = GovIngestBatch(project_id=project.id, source_id=source.id, status="queued")
    db_session.add(batch)
    await db_session.flush()
    await enqueue(
        db_session,
        project_id=project.id,
        kind="ingest_batch",
        payload={"batch_id": batch.id, "source_id": source.id},
    )
    await db_session.commit()

    # The worker never exits on its own; stop it once the job succeeded.
    stop = asyncio.Event()
    task = asyncio.create_task(
        run_worker(
            stop,
            JOB_HANDLERS,
            poll_seconds=0.01,
            session_factory=runtime.session_factory(),
        )
    )
    for _ in range(300):
        await asyncio.sleep(0.01)
        async with runtime.session_factory()() as check:
            job = (
                await check.execute(select(GovJob).where(GovJob.project_id == project.id))
            ).scalar_one_or_none()
            if job is not None and job.status == "succeeded":
                break
    stop.set()
    await asyncio.wait_for(task, timeout=5)

    async with runtime.session_factory()() as check:
        job = (
            await check.execute(select(GovJob).where(GovJob.project_id == project.id))
        ).scalar_one_or_none()
    assert job is not None, "the enqueued job vanished"
    assert job.status == "succeeded", f"job ended {job.status!r}: {job.error}"

    stored = await db_session.get(GovIngestBatch, batch.id)
    assert stored is not None
    # The worker committed through its own session; this session's identity
    # map still holds the pre-worker row.
    await db_session.refresh(stored)
    assert stored.status == "staged"


async def test_eval_handler_records_the_run_on_the_named_batch(db_session: AsyncSession) -> None:
    """The evidence link the approval gate is fail-closed about."""
    from cliver_playbook.app.rag_governance.golden import (
        confirm_set,
        create_candidate_set,
    )
    from cliver_playbook.app.rag_governance.golden.schema import GoldenCase
    from cliver_playbook.app.rag_governance.runtime.handlers import run_eval_job

    project = await _project(db_session)
    golden = await create_candidate_set(
        db_session,
        project.id,
        [GoldenCase(id="case-1", question="Anything?", expected_intent="policy_question")],
    )
    await confirm_set(db_session, golden.id)
    batch = GovIngestBatch(project_id=project.id, status="staged")
    db_session.add(batch)
    await db_session.flush()
    job = await enqueue(
        db_session,
        project_id=project.id,
        kind="run_eval",
        payload={
            "project_id": project.id,
            "golden_set_id": golden.id,
            "rule_version": None,
            "stage": "baseline",
            "reference_time": None,
            "batch_id": batch.id,
        },
    )

    result = await run_eval_job(db_session, job)
    await db_session.commit()

    stored_batch = await db_session.get(GovIngestBatch, batch.id)
    assert stored_batch is not None
    await db_session.refresh(stored_batch)
    assert stored_batch.eval_run_id == result["run_id"]
