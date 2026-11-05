"""The access seam: a mandatory predicate every read path applies.

The default policy is the v1 contract (published, not deleted). A
governed scope additionally enforces classification and explicit
grants; crucially, a NULL classification is NOT public — an unlabelled
document is only reachable through an explicit grant. That fail-closed
choice is what makes "forgot to classify" a safe mistake.
"""

from __future__ import annotations

import pytest
from sqlalchemy.dialects import postgresql

from cliver_playbook.app.basic import runtime
from cliver_playbook.app.rag.access import AccessScope, policy_for
from cliver_playbook.app.rag.filters import FieldFilter, FilterOp
from cliver_playbook.app.rag.models.entities import Chunk, Document
from cliver_playbook.app.rag.retrieval import Query
from cliver_playbook.app.rag.retrieval.bm25_only import Bm25OnlyRetriever


def _sql(scope: AccessScope) -> str:
    return str(policy_for(scope).predicate(scope).compile(dialect=postgresql.dialect()))


def test_default_policy_hides_unpublished_and_deleted() -> None:
    sql = _sql(AccessScope())
    assert "rag_documents.published IS true" in sql
    assert "rag_documents.deleted_at IS NULL" in sql


def test_governed_policy_fails_closed_on_null_classification() -> None:
    sql = _sql(AccessScope(governed=True, clearance=5))
    assert "rag_documents.classification IS NOT NULL" in sql
    assert "rag_documents.classification <=" in sql
    # A governed scope still requires the document to be published
    # unless the caller is the privileged staged-preview path.
    assert "rag_documents.published IS true" in sql


def test_grant_is_additive() -> None:
    sql = _sql(AccessScope(governed=True, clearance=0, grants=frozenset({"doc-a"})))
    assert "rag_documents.logical_id IN" in sql


def test_allow_staged_is_the_only_bypass() -> None:
    sql = _sql(AccessScope(governed=True, clearance=0, allow_staged=True))
    assert "rag_documents.published IS true" not in sql
    assert "rag_documents.deleted_at IS NULL" in sql


async def _seed() -> None:
    factory = runtime.session_factory()
    async with factory() as db:
        db.add_all(
            [
                Document(
                    id="d-low",
                    title="Low",
                    mime_type="text/markdown",
                    chunker_id="parent-child",
                    embedder_id="stub",
                    dim=4,
                    status="indexed",
                    published=True,
                    classification=1,
                    collection_id="finance",
                    logical_id="low-doc",
                    metadata_json={"doc_type": "policy"},
                ),
                Document(
                    id="d-high",
                    title="High",
                    mime_type="text/markdown",
                    chunker_id="parent-child",
                    embedder_id="stub",
                    dim=4,
                    status="indexed",
                    published=True,
                    classification=3,
                    collection_id="finance",
                    logical_id="high-doc",
                    metadata_json={"doc_type": "report"},
                ),
                Document(
                    id="d-staged",
                    title="Staged",
                    mime_type="text/markdown",
                    chunker_id="parent-child",
                    embedder_id="stub",
                    dim=4,
                    status="indexed",
                    published=False,
                    classification=1,
                    collection_id="finance",
                    logical_id="staged-doc",
                    metadata_json={"doc_type": "policy"},
                ),
                Document(
                    id="d-null",
                    title="Unlabelled",
                    mime_type="text/markdown",
                    chunker_id="parent-child",
                    embedder_id="stub",
                    dim=4,
                    status="indexed",
                    published=True,
                    classification=None,
                    collection_id="finance",
                    logical_id="null-doc",
                    metadata_json={"doc_type": "policy"},
                ),
            ]
        )
        db.add_all(
            [
                Chunk(
                    id="c-low",
                    document_id="d-low",
                    ordinal=0,
                    text="revenue",
                    search_text="context: revenue",
                    token_count=1,
                ),
                Chunk(
                    id="c-high",
                    document_id="d-high",
                    ordinal=0,
                    text="revenue",
                    search_text="context: revenue",
                    token_count=1,
                ),
                Chunk(
                    id="c-staged",
                    document_id="d-staged",
                    ordinal=0,
                    text="revenue",
                    search_text="context: revenue",
                    token_count=1,
                ),
                Chunk(
                    id="c-null",
                    document_id="d-null",
                    ordinal=0,
                    text="revenue",
                    search_text="context: revenue",
                    token_count=1,
                ),
            ]
        )
        await db.commit()


async def test_bm25_retriever_applies_scope_and_filter(app) -> None:
    await _seed()
    factory = runtime.session_factory()
    async with factory() as db:
        hits = await Bm25OnlyRetriever().retrieve(
            Query(
                text="revenue",
                top_k=10,
                access=AccessScope(collection_id="finance", governed=True, clearance=1),
            ),
            db=db,
        )
        assert {hit.document_id for hit in hits} == {"d-low"}

        granted = await Bm25OnlyRetriever().retrieve(
            Query(
                text="revenue",
                top_k=10,
                access=AccessScope(
                    collection_id="finance",
                    governed=True,
                    clearance=1,
                    grants=frozenset({"high-doc"}),
                ),
            ),
            db=db,
        )
        assert {hit.document_id for hit in granted} == {"d-low", "d-high"}

        filtered = await Bm25OnlyRetriever().retrieve(
            Query(
                text="revenue",
                top_k=10,
                filters=FieldFilter("doc_type", FilterOp.EQ, "report"),
                access=AccessScope(collection_id="finance", governed=True, clearance=3),
            ),
            db=db,
        )
        assert {hit.document_id for hit in filtered} == {"d-high"}


async def test_bm25_searches_contextual_text_and_exposes_the_parent(app) -> None:
    await _seed()
    factory = runtime.session_factory()
    async with factory() as db:
        chunk = await db.get(Chunk, "c-low")
        chunk.text = "irrelevant"
        chunk.search_text = "a contextual preamble about revenue"
        chunk.parent_id = None
        await db.commit()

        hits = await Bm25OnlyRetriever().retrieve(
            Query(
                text="contextual revenue",
                top_k=10,
                access=AccessScope(collection_id="finance", governed=True, clearance=1),
            ),
            db=db,
        )
        assert [hit.chunk_id for hit in hits] == ["c-low"]
        assert hits[0].logical_id == "low-doc"
        assert hits[0].classification == 1
        assert hits[0].document_metadata["doc_type"] == "policy"


@pytest.mark.parametrize(
    ("field", "op", "value"),
    [
        ("doc_type", FilterOp.EQ, "policy"),
        ("title", FilterOp.CONTAINS, "Low"),
    ],
)
def test_filters_compose_with_the_access_predicate(field, op, value) -> None:
    from cliver_playbook.app.rag.filters import compile_filter

    assert compile_filter(FieldFilter(field, op, value)) is not None
