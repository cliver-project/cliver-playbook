"""Canonical handlers for the governance job kinds.

The API endpoints enqueue jobs (``ingest_batch``, ``run_eval``,
``generate_golden``); :func:`cliver_playbook.app.rag_governance.runtime.jobs.run_worker`
executes them against this registry. The handlers are thin orchestration:
each loads the rows its payload names, calls the domain entry point that
already exists (the ingestion pipeline, the evaluation runner, the golden
generator) and writes the state transitions the API surfaces. Business rules
stay in those domains — a handler never re-decides them.

Configuration comes from the project's ``config_json``:

- ``embedding.embedder`` names the rag embedder registry entry that embeds
  staged chunks (default ``stub``; a real deployment names a model).
- ``chunking`` carries the optional ``IngestConfig`` knobs (``child_size``,
  ``child_overlap``, ``parent_max_chars``, ``type_to_chunker``).
- ``taxonomy.classifier`` names a ``type_classifiers`` registry entry
  (default ``by-extension``). A scenario registers its own classifier
  implementation under a new name — the same registry seam the other stages
  use. The cleaner, masker and contextualizer remain the built-in defaults
  in v1.
- ``golden.llm`` names the rag LLM registry entry used for golden-case
  generation (default ``cliver-core``); ``golden.max_tokens`` is its output
  budget (default 8192 — a reasoning model needs room beyond its hidden
  reasoning).
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from cliver_playbook.app.rag.embedding import get_embedder
from cliver_playbook.app.rag.llm import get_llm
from cliver_playbook.app.rag_governance.evaluation import (
    default_evaluators,
    run_evaluation,
)
from cliver_playbook.app.rag_governance.golden import create_candidate_set
from cliver_playbook.app.rag_governance.golden.generator import generate_candidates
from cliver_playbook.app.rag_governance.ingestion.pipeline import IngestConfig, ingest_document
from cliver_playbook.app.rag_governance.models.entities import (
    GovIngestBatch,
    GovProject,
    GovSource,
)
from cliver_playbook.app.rag_governance.rules.versions import (
    active_rule_set,
    get_rule_set,
)
from cliver_playbook.app.rag_governance.stages import (
    PassthroughCleaner,
    RegexPiiMasker,
    SectionPathContextualizer,
)
from cliver_playbook.app.rag_governance.stages import (
    sources as source_stages,
)
from cliver_playbook.app.rag_governance.stages import (
    type_classifiers as classifier_stages,
)
from cliver_playbook.app.rag_governance.stages.base import SourceDocument

logger = logging.getLogger(__name__)

_DEFAULT_EMBEDDER = "stub"
_DEFAULT_LLM = "cliver-core"


def _project_config(project: GovProject) -> dict[str, Any]:
    return dict(project.config_json or {})


async def run_ingest_batch(db: AsyncSession, job: Any) -> dict[str, Any]:
    """Stage one batch: fetch the source, pipeline every document.

    Payload: ``{"batch_id": str, "source_id": str}``. The batch row moves to
    ``staged`` (or stays ``failed`` — the worker marks the job, and the batch
    status follows below) with aggregate stats; the job's own success/failure
    is the worker's to record.
    """
    payload = job.payload_json or {}
    batch = await db.get(GovIngestBatch, payload.get("batch_id"))
    if batch is None:
        raise LookupError(f"ingest batch {payload.get('batch_id')!r} no longer exists")
    source = await db.get(GovSource, payload.get("source_id"))
    if source is None:
        raise LookupError(f"source {payload.get('source_id')!r} no longer exists")
    project = await db.get(GovProject, batch.project_id)
    if project is None:
        raise LookupError(f"project {batch.project_id!r} no longer exists")

    config = _project_config(project)
    embedder = get_embedder((config.get("embedding") or {}).get("embedder") or _DEFAULT_EMBEDDER)
    chunking = dict(config.get("chunking") or {})
    taxonomy = dict(config.get("taxonomy") or {})
    batch.status = "running"
    await db.flush()

    documents: list[SourceDocument] = list(
        source_stages.get(source.kind).fetch(dict(source.config_json or {}))
    )
    chunks = parents = masked = 0
    for document in documents:
        logical_id = str(document.metadata.get("logical_id") or document.source_uri)
        result = await ingest_document(
            db,
            project=project,
            source_document=document,
            config=IngestConfig(
                logical_id=logical_id,
                pipeline_run_id=batch.id,
                child_size=chunking.get("child_size", 512),
                child_overlap=chunking.get("child_overlap", 64),
                parent_max_chars=chunking.get("parent_max_chars", 4000),
                type_to_chunker=dict(chunking.get("type_to_chunker") or {}),
            ),
            embedder=embedder,
            cleaner=PassthroughCleaner(),
            masker=RegexPiiMasker(),
            # Scenario stages register by name, like the source and
            # embedder factories: the project's taxonomy picks the
            # implementation, and an unknown name fails the job loudly.
            classifier=classifier_stages.get(taxonomy.get("classifier") or "by-extension"),
            contextualizer=SectionPathContextualizer(),
        )
        chunks += result.chunk_count
        parents += result.parent_count
        masked += sum(result.masked_counts.values())

    batch.status = "staged"
    batch.stats = {
        "documents": len(documents),
        "parents": parents,
        "chunks": chunks,
        "masked": masked,
    }
    source.last_run_at = datetime.now(tz=UTC)
    await db.flush()
    logger.info(
        "ingest batch %s staged %d document(s), %d chunk(s)", batch.id, len(documents), chunks
    )
    return {"batch_id": batch.id, **batch.stats}


async def run_eval_job(db: AsyncSession, job: Any) -> dict[str, Any]:
    """Evaluate one confirmed golden set and persist the immutable run.

    Payload: ``{"project_id", "golden_set_id", "rule_version", "stage",
    "reference_time", "batch_id"}`` — exactly what the evaluation endpoint
    enqueues. The runner creates the ``gov_eval_runs`` row and its per-case
    results; the handler resolves the inputs (including the active rule set
    when no version was pinned) and, when the request named a staged batch,
    records the run on that batch as its approval report.
    """
    from cliver_playbook.app.rag_governance.models.entities import GovGoldenSet

    payload = job.payload_json or {}
    project = await db.get(GovProject, payload.get("project_id"))
    if project is None:
        raise LookupError(f"project {payload.get('project_id')!r} no longer exists")
    golden_set = await db.get(GovGoldenSet, payload.get("golden_set_id"))
    if golden_set is None:
        raise LookupError(f"golden set {payload.get('golden_set_id')!r} no longer exists")

    rule_version = payload.get("rule_version")
    if rule_version is not None:
        version = await get_rule_set(db, project.id, int(rule_version))
        if version is None:
            raise LookupError(f"rule set version {rule_version!r} not found")
    else:
        version = await active_rule_set(db, project.id)
    rules = list(version.rules) if version else []

    reference_time = payload.get("reference_time")
    report = await run_evaluation(
        db,
        project=project,
        golden_set=golden_set,
        rules=rules,
        evaluators=default_evaluators(),
        rule_version=version.version if version else None,
        stage=payload.get("stage") or "baseline",
        reference_time=datetime.fromisoformat(reference_time) if reference_time else None,
    )
    batch_id = payload.get("batch_id")
    if batch_id is not None:
        batch = await db.get(GovIngestBatch, batch_id)
        if batch is None or batch.project_id != project.id:
            raise LookupError(f"batch {batch_id!r} no longer exists")
        # The approval gate is fail-closed: without this link it refuses the
        # batch. A failed run is still recorded — the gate then rejects the
        # batch with the run's threshold misses, which is the honest outcome.
        batch.eval_run_id = report.run_id
        await db.flush()

    logger.info("evaluation run %s finished: %s", report.run_id, report.status)
    return {"run_id": report.run_id, "status": report.status, "summary": report.summary}


async def run_generate_golden(db: AsyncSession, job: Any) -> dict[str, Any]:
    """Generate golden candidates with the configured LLM, as a new candidate set.

    Payload: ``{"project_id", "scenario", "max_cases"}``. Generation writes a
    *candidate* set only; confirming it stays a human act.
    """
    payload = job.payload_json or {}
    project = await db.get(GovProject, payload.get("project_id"))
    if project is None:
        raise LookupError(f"project {payload.get('project_id')!r} no longer exists")

    config = _project_config(project)
    golden_config = dict(config.get("golden") or {})
    llm = get_llm(golden_config.get("llm") or _DEFAULT_LLM)

    documents: list[SourceDocument] = []
    from sqlalchemy import select

    for source in (
        await db.execute(
            select(GovSource).where(
                GovSource.project_id == project.id, GovSource.status == "active"
            )
        )
    ).scalars():
        if source.authority != "document":
            continue
        documents.extend(source_stages.get(source.kind).fetch(dict(source.config_json or {})))

    cases = await generate_candidates(
        project=project,
        documents=documents,
        llm=llm,
        scenario=payload.get("scenario") or "",
        max_cases=int(payload.get("max_cases") or 10),
        max_tokens=int(golden_config.get("max_tokens") or 8192),
    )
    golden_set = await create_candidate_set(db, project.id, cases, actor="worker", source="llm")
    logger.info("golden candidate set %s (v%s) generated", golden_set.id, golden_set.version)
    return {"golden_set_id": golden_set.id, "version": golden_set.version, "cases": len(cases)}


#: The registry ``run_worker`` receives: every job kind this package can
#: enqueue, mapped to its handler. An unlisted kind fails the job instead of
#: being silently dropped (the worker's own rule).
JOB_HANDLERS = {
    "ingest_batch": run_ingest_batch,
    "run_eval": run_eval_job,
    "generate_golden": run_generate_golden,
}
