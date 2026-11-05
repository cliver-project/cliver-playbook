"""The governed query facade: rules, access, retrieval, tools, generation.

This is the single read path the governance loop is built around. It
implements design §10 in order:

1. resolve the project's active rule version;
2. classify the question into zero or more intents;
3. compose the retrieval scope from the matched rules;
4. build the caller's governed ``AccessScope``;
5. select the strategy — ``none`` is a terminal refusal that performs
   no retrieval, no tool planning and no generation;
6. bind only tools the caller is authorized to see;
7. plan and invoke tools with the injected ``as_of``;
8. retrieve with the composed filter and access predicate;
9. rerank and keep the small-to-big parent context;
10. generate from parent text and normalized tool results;
11. audit the trace.

Two invariants are enforced here rather than left to callers:

- **No host clock.** Every freshness, period and audit timestamp derives
  from the injected ``as_of``; the facade never calls ``datetime.now``.
- **No silent substitution.** A failed live tool yields an explicit
  "live data unavailable" answer. A snapshot is used only when the rule
  enables ``snapshot_fallback``, and then its period is named in the
  answer and in the tool-call record.

The facade returns an ``Answer`` that carries a ``QueryObservation``.
The observation is the evaluator-facing shape, so the same run can be
replayed by the golden-test harness without the facade importing the
evaluation package.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from time import perf_counter
from typing import Any, Literal, Protocol
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from cliver_playbook.app.rag.llm.base import LLM
from cliver_playbook.app.rag.reranking import get_reranker
from cliver_playbook.app.rag.reranking.base import Reranker
from cliver_playbook.app.rag.retrieval import Query, get_retriever
from cliver_playbook.app.rag.retrieval.base import Hit, Retriever
from cliver_playbook.app.rag_governance.evaluation.observation import (
    ObservedCitation,
    ObservedSource,
    ObservedToolCall,
    QueryObservation,
)
from cliver_playbook.app.rag_governance.models.entities import GovProject, GovTool
from cliver_playbook.app.rag_governance.query.access import governed_scope, tool_authorized
from cliver_playbook.app.rag_governance.rules.engine import (
    IntentMatch,
    KeywordRegexClassifier,
    compose_scope,
    fallback_rule,
    rank_matches,
)
from cliver_playbook.app.rag_governance.rules.schema import IntentRule
from cliver_playbook.app.rag_governance.rules.versions import active_rule_set
from cliver_playbook.app.rag_governance.settings import settings
from cliver_playbook.app.rag_governance.stages.masker import MaskerOptions, RegexPiiMasker
from cliver_playbook.app.rag_governance.tools.base import (
    ToolCaps,
    ToolContext,
    ToolDeniedError,
    ToolSpec,
)
from cliver_playbook.app.rag_governance.tools.registry import (
    RestrictedToolInvoker,
    ToolRegistry,
    fingerprint_args,
)

logger = logging.getLogger("cliver_playbook.app.rag_governance.query.facade")

_NO_CONTEXT_ANSWER = (
    "I could not find anything relevant to that question in the knowledge base. "
    "Try rephrasing it, or add a document that covers the topic."
)
_NO_INTENT_ANSWER = (
    "I could not match that question to a supported intent, so I will not answer it."
)
_MAX_TOKENS = 1024

_SYSTEM_PROMPT = (
    "You are a governed retrieval-augmented assistant. Answer the question using ONLY the "
    "provided context and live tool results. Cite every claim with the id shown in square "
    "brackets: policy and definition claims use [doc:<logical_id>#<section>], numeric claims "
    "use [tool:<name>@<data_date>] and the tool result's as_of. If the context is insufficient, "
    "say so plainly instead of guessing. Never present a snapshot as current."
)

_HEADING_PREFIX = re.compile(r"^H[1-6]#")
_PART_SUFFIX = re.compile(r"#part-\d+$")

AuditSink = Callable[[dict[str, Any]], Awaitable[None]]


class QueryError(ValueError):
    """The query cannot be answered as configured."""


class QueryConfigError(QueryError):
    """A rule set, access scope or tool profile is missing or invalid."""


class QueryToolError(QueryError):
    """A planner attempted an unbound tool or a tool call was denied."""


@dataclass(frozen=True)
class Citation:
    """One provenance marker the answer may carry."""

    kind: Literal["document", "tool"]
    ref: str
    locator: str | None = None
    as_of: datetime | None = None

    @property
    def marker(self) -> str:
        if self.kind == "tool":
            suffix = f"@{self.as_of.date().isoformat()}" if self.as_of else ""
            return f"[tool:{self.ref}{suffix}]"
        suffix = f"#{self.locator}" if self.locator else ""
        return f"[doc:{self.ref}{suffix}]"


@dataclass(frozen=True)
class ToolCallRecord:
    """One tool invocation, including the policy facts it ran under.

    ``as_of`` is the tool result's reference instant (normally the
    injected request time). The data cutoff a numeric claim cites lives
    in the payload's ``as_of`` and is exposed through ``Citation``.
    """

    name: str
    args_fingerprint: str
    as_of: datetime
    row_count: int = 0
    latency_ms: int = 0
    error: str | None = None
    authorized: bool = True
    bound: bool = True
    read_only: bool = True
    min_clearance: int | None = None
    is_snapshot: bool = False
    period: str | None = None
    args: dict[str, Any] = field(default_factory=dict)
    result: Any = None


@dataclass(frozen=True)
class Answer:
    """The facade's response plus the evaluator-readable trace."""

    text: str
    intent: str | None
    strategy: str
    citations: tuple[Citation, ...]
    tool_calls: tuple[ToolCallRecord, ...]
    as_of: datetime
    refused: bool = False
    rule_version: int | None = None
    observation: QueryObservation = field(default_factory=QueryObservation)


@dataclass(frozen=True)
class PlannedCall:
    """A tool name and the typed arguments the planner selected."""

    name: str
    args: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ToolPlan:
    """The planner's complete selection for one question."""

    calls: tuple[PlannedCall, ...] = ()


class ToolPlanner(Protocol):
    """Selects tools and typed arguments from the authorized tool list."""

    async def plan(
        self,
        *,
        question: str,
        rule: IntentRule,
        tools: Sequence[ToolSpec],
        as_of: datetime,
    ) -> ToolPlan: ...


class RuleToolPlanner:
    """Deterministic v1 planner: call every tool the rule names.

    The LLM planner is a later, optional implementation. Keeping the
    default rule-driven makes the facade's tool path testable without a
    model and gives a project with no planner a safe, bounded behaviour.
    Tool implementations resolve symbolic arguments (for example
    ``latest_closed``) against the injected ``as_of``.
    """

    async def plan(
        self,
        *,
        question: str,
        rule: IntentRule,
        tools: Sequence[ToolSpec],
        as_of: datetime,
    ) -> ToolPlan:
        return ToolPlan(calls=tuple(PlannedCall(name=spec.name) for spec in tools))


def _require_aware(value: datetime, name: str) -> None:
    if value.tzinfo is None:
        raise QueryConfigError(f"{name} must be timezone-aware")


def _primary(matches: Sequence[IntentMatch]) -> IntentRule:
    return rank_matches(matches)[0].rule


def _resolve_matches(
    question: str,
    rules: Sequence[IntentRule],
    config: dict[str, Any],
) -> list[IntentMatch]:
    classifier_config = config.get("classifier")
    matches = KeywordRegexClassifier().classify(
        question,
        rules,
        classifier_config if isinstance(classifier_config, dict) else None,
    )
    if matches:
        return list(matches)
    fallback = fallback_rule(rules)
    if fallback is None:
        return []
    return [IntentMatch(intent=fallback.intent, confidence=0.0, rule=fallback)]


def _locator(section_path: str | None) -> str | None:
    """``H2#资产负债率`` -> ``资产负债率`` for a readable citation."""
    path = (section_path or "").strip()
    if not path:
        return None
    path = _PART_SUFFIX.sub("", path)
    locator = _HEADING_PREFIX.sub("", path).strip()
    return locator or None


def _hit_locator(hit: Hit) -> str | None:
    return _locator(hit.metadata.get("section_path"))


def _dedupe_hits(hits: Sequence[Hit]) -> list[Hit]:
    """One generation block per parent section, best-ranked first."""
    seen: set[str] = set()
    kept: list[Hit] = []
    for hit in hits:
        key = hit.parent_id or hit.chunk_id
        if key in seen:
            continue
        seen.add(key)
        kept.append(hit)
    return kept


def _document_citation(hit: Hit) -> Citation:
    return Citation(
        kind="document",
        ref=hit.logical_id or hit.document_id,
        locator=_hit_locator(hit),
    )


def _json_default(value: Any) -> str:
    return str(value)


def _result_as_of(data: Any) -> datetime | None:
    """The data cutoff a tool reports inside its payload, if any."""
    if not isinstance(data, dict):
        return None
    value = data.get("as_of")
    if isinstance(value, datetime):
        return value if value.tzinfo is not None else value.replace(tzinfo=UTC)
    if isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value)
        except ValueError:
            return None
        return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=UTC)
    return None


def _tool_citation(record: ToolCallRecord) -> Citation:
    cutoff = _result_as_of(record.result) or record.as_of
    return Citation(kind="tool", ref=record.name, as_of=cutoff)


def _period(hit: Hit) -> str | None:
    for source in (hit.document_metadata, hit.metadata):
        value = source.get("period") if isinstance(source, dict) else None
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _masking_for(config: dict[str, Any], binding: GovTool) -> Callable[[Any], Any] | None:
    """The masking callable for one tool, or None when none is configured.

    Project masking is the baseline; a binding may narrow the pattern
    set. An invalid masking configuration raises instead of silently
    letting raw values through: masking is a hard gate.
    """
    project_masking = config.get("masking")
    tool_masking = binding.masking_json
    merged: dict[str, Any] = {}
    if isinstance(project_masking, dict):
        merged.update(project_masking)
    if isinstance(tool_masking, dict):
        merged.update(tool_masking)
    if not merged:
        return None
    try:
        options = MaskerOptions.model_validate(merged)
    except ValueError as exc:
        raise QueryConfigError(f"invalid masking configuration: {exc}") from None
    masker = RegexPiiMasker()

    def mask(value: Any) -> Any:
        if isinstance(value, str):
            return masker.mask(value, options).text
        return value

    return mask


def _build_prompt(
    question: str,
    documents: Sequence[tuple[Citation, str]],
    tools: Sequence[tuple[Citation, Any]],
) -> str:
    blocks: list[str] = []
    if documents:
        blocks.append("Context:")
        blocks.extend(f"[{citation.marker}] {text}" for citation, text in documents)
    if tools:
        if blocks:
            blocks.append("")
        blocks.append("Live data:")
        for citation, data in tools:
            payload = json.dumps(data, ensure_ascii=False, default=_json_default, sort_keys=True)
            blocks.append(f"[{citation.marker}] {payload}")
    blocks.append("")
    blocks.append(f"Question: {question}")
    return "\n".join(blocks)


def _ensure_citations(text: str, citations: Sequence[Citation]) -> str:
    """Guarantee provenance even when a generator forgets to cite."""
    markers: list[str] = []
    for citation in citations:
        marker = citation.marker
        if marker not in text and marker not in markers:
            markers.append(marker)
    if not markers:
        return text
    return text.rstrip() + "\n\nSources:\n" + "\n".join(markers)


def _observation(
    *,
    question: str,
    text: str,
    intent: str | None,
    strategy: str,
    refused: bool,
    retrieval_calls: int,
    hits: Sequence[Hit],
    citations: Sequence[Citation],
    tool_calls: Sequence[ToolCallRecord],
    contexts: Sequence[str],
    unavailability: bool,
    rule_version: int | None,
    llm: LLM | None,
    extra: dict[str, Any] | None = None,
) -> QueryObservation:
    sources = tuple(
        ObservedSource(
            logical_id=hit.logical_id or hit.document_id,
            locator=_hit_locator(hit),
            classification=hit.classification,
            text=hit.parent_text or hit.text,
        )
        for hit in hits
    )
    metadata: dict[str, Any] = {
        "rule_version": rule_version,
        "model_id": getattr(llm, "model_id", None),
    }
    if extra:
        metadata.update(extra)
    return QueryObservation(
        question=question,
        intent=intent,
        strategy=strategy,
        answer=text,
        refused=refused,
        retrieval_calls=retrieval_calls,
        sources=sources,
        citations=tuple(
            ObservedCitation(kind=citation.kind, ref=citation.ref, locator=citation.locator)
            for citation in citations
        ),
        tool_calls=tuple(
            ObservedToolCall(
                name=record.name,
                args=dict(record.args),
                as_of=record.as_of,
                read_only=record.read_only,
                bound=record.bound,
                authorized=record.authorized,
                min_clearance=record.min_clearance,
                error=record.error,
                result=record.result,
                is_snapshot=record.is_snapshot,
                period=record.period,
            )
            for record in tool_calls
        ),
        contexts=tuple(contexts),
        unavailability_answer=unavailability,
        metadata=metadata,
    )


def _audit_record(
    *,
    project: GovProject,
    question: str,
    answer: Answer,
    llm: LLM | None,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    record: dict[str, Any] = {
        "event": "rag.governance.query",
        "project_id": project.id,
        "question_fingerprint": fingerprint_args({"question": question}),
        "intent": answer.intent,
        "strategy": answer.strategy,
        "rule_version": answer.rule_version,
        "refused": answer.refused,
        "retrieval_calls": answer.observation.retrieval_calls,
        "hit_chunk_ids": [source.logical_id for source in answer.observation.sources],
        "citations": [citation.marker for citation in answer.citations],
        "tool_calls": [
            {
                "name": record.name,
                "args_fingerprint": record.args_fingerprint,
                "as_of": record.as_of.isoformat(),
                "row_count": record.row_count,
                "latency_ms": record.latency_ms,
                "error": record.error,
                "is_snapshot": record.is_snapshot,
                "period": record.period,
            }
            for record in answer.tool_calls
        ],
        "model_id": getattr(llm, "model_id", None),
        "as_of": answer.as_of.isoformat(),
    }
    if extra:
        record.update(extra)
    return record


async def _emit_audit(sink: AuditSink | None, record: dict[str, Any]) -> None:
    if sink is None:
        return
    try:
        await sink(record)
    except Exception:  # audit is best-effort
        logger.warning("governance query audit failed", exc_info=True)


def _terminal_answer(
    *,
    question: str,
    text: str,
    intent: str | None,
    strategy: str,
    as_of: datetime,
    rule_version: int | None,
    llm: LLM | None,
    refused: bool = True,
) -> Answer:
    return Answer(
        text=text,
        intent=intent,
        strategy=strategy,
        citations=(),
        tool_calls=(),
        as_of=as_of,
        refused=refused,
        rule_version=rule_version,
        observation=_observation(
            question=question,
            text=text,
            intent=intent,
            strategy=strategy,
            refused=refused,
            retrieval_calls=0,
            hits=(),
            citations=(),
            tool_calls=(),
            contexts=(),
            unavailability=False,
            rule_version=rule_version,
            llm=llm,
        ),
    )


def _retrieval_options(
    project: GovProject,
    rule: IntentRule,
) -> tuple[str, int, int, str | None]:
    config = dict(project.config_json or {})
    retrieval = config.get("retrieval")
    retrieval = retrieval if isinstance(retrieval, dict) else {}
    embedding = config.get("embedding")
    embedding = embedding if isinstance(embedding, dict) else {}

    mode = rule.retrieval.mode or str(retrieval.get("mode") or "hybrid")
    top_k = int(rule.retrieval.top_k or retrieval.get("top_k") or settings.rag.top_k)
    rerank_top_k = int(
        rule.retrieval.rerank_top_k or retrieval.get("rerank_top_k") or settings.rag.rerank_top_k
    )
    embedder = (
        rule.retrieval.embedder
        or retrieval.get("embedder")
        or embedding.get("embedder")
        or embedding.get("name")
    )
    return mode, top_k, rerank_top_k, str(embedder) if embedder else None


def _reranker_name(project: GovProject) -> str:
    config = dict(project.config_json or {})
    retrieval = config.get("retrieval")
    if isinstance(retrieval, dict) and isinstance(retrieval.get("reranker"), str):
        return retrieval["reranker"]
    return settings.rag.reranker


async def _load_bindings(db: AsyncSession, project_id: str) -> list[GovTool]:
    rows = await db.execute(
        select(GovTool).where(GovTool.project_id == project_id, GovTool.enabled.is_(True))
    )
    return list(rows.scalars().all())


async def _retrieve(
    *,
    db: AsyncSession,
    question: str,
    project: GovProject,
    rule: IntentRule,
    filters: Any,
    access: Any,
    retriever: Retriever | None,
    reranker: Reranker | None,
) -> list[Hit]:
    mode, top_k, rerank_top_k, embedder = _retrieval_options(project, rule)
    resolved = retriever or get_retriever(settings.rag.retriever)
    if mode not in resolved.modes:
        # A mode the implementation cannot honour is a configuration
        # error, not a silent downgrade. The rule author must choose a
        # supported representation.
        raise QueryConfigError(
            f"retriever {resolved.name!r} does not support mode {mode!r}; "
            f"supported: {', '.join(sorted(resolved.modes))}"
        )
    hits = await resolved.retrieve(
        Query(
            text=question,
            top_k=top_k,
            mode=resolved.effective_mode(mode),
            embedder=embedder,
            filters=filters,
            access=access,
        ),
        db=db,
    )
    if not hits:
        return []
    active_reranker = reranker or get_reranker(_reranker_name(project))
    # Cross-encoder inference is CPU/model work; keep it off the loop.
    hits = await asyncio.to_thread(active_reranker.rerank, question, hits, top_k=rerank_top_k)
    floor = settings.rag.score_floor
    if active_reranker.produces_relevance_scores and floor > 0:
        hits = [hit for hit in hits if hit.score >= floor]
    return hits


async def answer_question(
    db: AsyncSession,
    *,
    project: GovProject,
    question: str,
    viewer: Any,
    as_of: datetime,
    llm: LLM,
    rules: Sequence[IntentRule] | None = None,
    rule_version: int | None = None,
    retriever: Retriever | None = None,
    reranker: Reranker | None = None,
    tool_bindings: Sequence[GovTool] | None = None,
    tool_registry: ToolRegistry | None = None,
    planner: ToolPlanner | None = None,
    access: Any = None,
    max_tokens: int = _MAX_TOKENS,
    audit: AuditSink | None = None,
) -> Answer:
    """Answer one question through the governance loop.

    ``access`` lets an evaluation replay inject a specific
    ``AccessScope`` (the primary run or the leak probe); ordinary callers
    omit it and the scope is derived from the viewer's clearance and
    grants. ``as_of`` is the question's reference instant and is passed
    unchanged to every tool.
    """
    _require_aware(as_of, "as_of")
    if not question.strip():
        raise QueryConfigError("question must not be empty")
    config = dict(project.config_json or {})

    if rules is None:
        snapshot = await active_rule_set(db, project.id)
        if snapshot is None:
            raise QueryConfigError("the project has no active rule set")
        rules = snapshot.rules
        rule_version = snapshot.version

    matches = _resolve_matches(question, rules, config)
    if not matches:
        answer = _terminal_answer(
            question=question,
            text=_NO_INTENT_ANSWER,
            intent=None,
            strategy="none",
            as_of=as_of,
            rule_version=rule_version,
            llm=llm,
        )
        await _emit_audit(
            audit,
            _audit_record(
                project=project,
                question=question,
                answer=answer,
                llm=llm,
                extra={"refusal": "no_intent"},
            ),
        )
        return answer

    primary = _primary(matches)
    if primary.strategy == "none":
        text = primary.refusal.message if primary.refusal else _NO_INTENT_ANSWER
        answer = _terminal_answer(
            question=question,
            text=text,
            intent=primary.intent,
            strategy="none",
            as_of=as_of,
            rule_version=rule_version,
            llm=llm,
        )
        await _emit_audit(
            audit,
            _audit_record(
                project=project,
                question=question,
                answer=answer,
                llm=llm,
                extra={"refusal": "rule"},
            ),
        )
        return answer

    try:
        filters = compose_scope(
            matches,
            scope_combination=str(config.get("scope_combination") or "highest_priority"),
        )
    except ValueError as exc:
        raise QueryConfigError(str(exc)) from None

    scope = access if access is not None else await governed_scope(db, project, viewer)
    if scope.collection_id != project.collection_id:
        raise QueryConfigError("the access scope belongs to another collection")

    uses_tools = primary.strategy in ("tools", "agentic")
    tool_calls: list[ToolCallRecord] = []
    tool_pairs: list[tuple[ToolCallRecord, Any]] = []
    failed: ToolCallRecord | None = None
    citations: list[Citation] = []
    hits: list[Hit] = []
    contexts: list[str] = []
    retrieval_calls = 0

    if uses_tools:
        bindings = (
            list(tool_bindings)
            if tool_bindings is not None
            else await _load_bindings(db, project.id)
        )
        if tool_registry is None:
            raise QueryConfigError("a tool strategy requires a tool registry")
        allowed = set(primary.tools)
        authorized: list[tuple[GovTool, ToolSpec]] = []
        for binding in bindings:
            if binding.name not in allowed:
                continue
            if not tool_authorized(binding, viewer=viewer, access=scope):
                continue
            try:
                spec = tool_registry.get(binding.name).spec
            except KeyError:
                logger.warning(
                    "tool %r is bound to project %s but has no registered implementation",
                    binding.name,
                    project.id,
                )
                continue
            authorized.append((binding, spec))
        by_name = {binding.name: (binding, spec) for binding, spec in authorized}

        active_planner = planner or RuleToolPlanner()
        plan = await active_planner.plan(
            question=question,
            rule=primary,
            tools=[spec for _binding, spec in authorized],
            as_of=as_of,
        )
        for call in plan.calls:
            if call.name not in by_name:
                raise QueryToolError(
                    f"the planner selected tool {call.name!r}, which is not authorized for this caller"
                )

        invoker = RestrictedToolInvoker(
            tool_registry,
            allowed=frozenset(by_name),
            audit=None,
            depth=0,
        )
        for call in plan.calls:
            binding, spec = by_name[call.name]
            masking = _masking_for(config, binding)
            ctx = ToolContext(
                viewer=viewer,
                access=scope,
                project_id=project.id,
                as_of=as_of,
                masking=masking,
                caps=ToolCaps(max_rows=settings.rag_governance.max_tool_rows),
                registry=invoker,
                call_id=f"gov-{uuid4()}",
            )
            started = perf_counter()
            try:
                result = await invoker.invoke(call.name, call.args, ctx)
            except ToolDeniedError as exc:
                raise QueryToolError(str(exc)) from None
            except Exception as exc:  # noqa: BLE001 - third-party tool failure
                record = ToolCallRecord(
                    name=call.name,
                    args_fingerprint=fingerprint_args(call.args),
                    as_of=as_of,
                    latency_ms=int((perf_counter() - started) * 1000),
                    error=f"{type(exc).__name__}: {exc}",
                    read_only=spec.read_only,
                    min_clearance=binding.min_clearance,
                    args=dict(call.args),
                )
                tool_calls.append(record)
                failed = record
                break
            record = ToolCallRecord(
                name=call.name,
                args_fingerprint=fingerprint_args(call.args),
                as_of=result.as_of,
                row_count=result.row_count,
                latency_ms=int((perf_counter() - started) * 1000),
                error=result.error,
                read_only=spec.read_only,
                min_clearance=binding.min_clearance,
                args=dict(call.args),
                result=result.data,
            )
            tool_calls.append(record)
            if result.error is not None:
                failed = record
                break
            tool_pairs.append((record, result.data))

        if primary.strategy == "tools" and not tool_calls:
            # A live-only rule with no authorized tools cannot answer.
            # Refuse explicitly rather than falling through to the
            # generic no-context message, which would imply retrieval ran.
            text = "No authorized live data source is available for this question."
            answer = Answer(
                text=text,
                intent=primary.intent,
                strategy="tools",
                citations=(),
                tool_calls=(),
                as_of=as_of,
                refused=True,
                rule_version=rule_version,
                observation=_observation(
                    question=question,
                    text=text,
                    intent=primary.intent,
                    strategy="tools",
                    refused=True,
                    retrieval_calls=0,
                    hits=(),
                    citations=(),
                    tool_calls=(),
                    contexts=(),
                    unavailability=False,
                    rule_version=rule_version,
                    llm=llm,
                ),
            )
            await _emit_audit(
                audit,
                _audit_record(project=project, question=question, answer=answer, llm=llm),
            )
            return answer

    if failed is not None:
        if primary.snapshot_fallback:
            snapshot_hits = await _retrieve(
                db=db,
                question=question,
                project=project,
                rule=primary,
                filters=filters,
                access=scope,
                retriever=retriever,
                reranker=reranker,
            )
            retrieval_calls = 1
            labelled = [hit for hit in snapshot_hits if _period(hit)]
            if labelled:
                hit = labelled[0]
                period = _period(hit) or ""
                index = next(
                    position for position, record in enumerate(tool_calls) if record is failed
                )
                tool_calls[index] = replace(failed, is_snapshot=True, period=period)
                failed = tool_calls[index]
                text = (
                    f"Live data unavailable for {failed.name}. "
                    f"Showing the {period} snapshot instead.\n\n"
                    f"{hit.parent_text or hit.text}"
                )
                citation = _document_citation(hit)
                text = _ensure_citations(text, (citation,))
                answer = Answer(
                    text=text,
                    intent=primary.intent,
                    strategy="retrieval",
                    citations=(citation,),
                    tool_calls=tuple(tool_calls),
                    as_of=as_of,
                    refused=False,
                    rule_version=rule_version,
                    observation=_observation(
                        question=question,
                        text=text,
                        intent=primary.intent,
                        strategy="retrieval",
                        refused=False,
                        retrieval_calls=retrieval_calls,
                        hits=[hit],
                        citations=[citation],
                        tool_calls=tool_calls,
                        contexts=[hit.parent_text or hit.text],
                        unavailability=True,
                        rule_version=rule_version,
                        llm=llm,
                        extra={"snapshot_fallback": True, "period": period},
                    ),
                )
                await _emit_audit(
                    audit,
                    _audit_record(
                        project=project,
                        question=question,
                        answer=answer,
                        llm=llm,
                        extra={"snapshot_fallback": True},
                    ),
                )
                return answer

        text = (
            f"Live data unavailable for {failed.name} ({failed.error}). "
            "I cannot answer this question with current data right now."
        )
        answer = Answer(
            text=text,
            intent=primary.intent,
            strategy=primary.strategy,
            citations=(),
            tool_calls=tuple(tool_calls),
            as_of=as_of,
            refused=True,
            rule_version=rule_version,
            observation=_observation(
                question=question,
                text=text,
                intent=primary.intent,
                strategy=primary.strategy,
                refused=True,
                retrieval_calls=retrieval_calls,
                hits=(),
                citations=(),
                tool_calls=tool_calls,
                contexts=(),
                unavailability=True,
                rule_version=rule_version,
                llm=llm,
            ),
        )
        await _emit_audit(
            audit,
            _audit_record(project=project, question=question, answer=answer, llm=llm),
        )
        return answer

    if primary.strategy in ("retrieval", "agentic"):
        hits = await _retrieve(
            db=db,
            question=question,
            project=project,
            rule=primary,
            filters=filters,
            access=scope,
            retriever=retriever,
            reranker=reranker,
        )
        retrieval_calls = 1
        hits = _dedupe_hits(hits)
        if not hits:
            answer = Answer(
                text=_NO_CONTEXT_ANSWER,
                intent=primary.intent,
                strategy=primary.strategy,
                citations=(),
                tool_calls=tuple(tool_calls),
                as_of=as_of,
                refused=True,
                rule_version=rule_version,
                observation=_observation(
                    question=question,
                    text=_NO_CONTEXT_ANSWER,
                    intent=primary.intent,
                    strategy=primary.strategy,
                    refused=True,
                    retrieval_calls=retrieval_calls,
                    hits=(),
                    citations=(),
                    tool_calls=tool_calls,
                    contexts=(),
                    unavailability=False,
                    rule_version=rule_version,
                    llm=llm,
                ),
            )
            await _emit_audit(
                audit,
                _audit_record(project=project, question=question, answer=answer, llm=llm),
            )
            return answer

    document_blocks: list[tuple[Citation, str]] = []
    for hit in hits:
        parent_text = hit.parent_text or hit.text
        citation = _document_citation(hit)
        document_blocks.append((citation, parent_text))
        contexts.append(parent_text)
        if citation not in citations:
            citations.append(citation)

    tool_blocks: list[tuple[Citation, Any]] = []
    for record, data in tool_pairs:
        citation = _tool_citation(record)
        tool_blocks.append((citation, data))
        if citation not in citations:
            citations.append(citation)

    if not document_blocks and not tool_blocks:
        answer = Answer(
            text=_NO_CONTEXT_ANSWER,
            intent=primary.intent,
            strategy=primary.strategy,
            citations=(),
            tool_calls=tuple(tool_calls),
            as_of=as_of,
            refused=True,
            rule_version=rule_version,
            observation=_observation(
                question=question,
                text=_NO_CONTEXT_ANSWER,
                intent=primary.intent,
                strategy=primary.strategy,
                refused=True,
                retrieval_calls=retrieval_calls,
                hits=(),
                citations=(),
                tool_calls=tool_calls,
                contexts=(),
                unavailability=False,
                rule_version=rule_version,
                llm=llm,
            ),
        )
        await _emit_audit(
            audit,
            _audit_record(project=project, question=question, answer=answer, llm=llm),
        )
        return answer

    prompt = _build_prompt(question, document_blocks, tool_blocks)
    text = await asyncio.to_thread(
        llm.generate,
        system=_SYSTEM_PROMPT,
        prompt=prompt,
        max_tokens=max_tokens,
    )
    text = _ensure_citations(text, citations)

    answer = Answer(
        text=text,
        intent=primary.intent,
        strategy=primary.strategy,
        citations=tuple(citations),
        tool_calls=tuple(tool_calls),
        as_of=as_of,
        refused=False,
        rule_version=rule_version,
        observation=_observation(
            question=question,
            text=text,
            intent=primary.intent,
            strategy=primary.strategy,
            refused=False,
            retrieval_calls=retrieval_calls,
            hits=hits,
            citations=citations,
            tool_calls=tool_calls,
            contexts=contexts,
            unavailability=False,
            rule_version=rule_version,
            llm=llm,
            extra={"prompt_chars": len(prompt)},
        ),
    )
    await _emit_audit(
        audit,
        _audit_record(project=project, question=question, answer=answer, llm=llm),
    )
    return answer
