"""Smoke test: package imports cleanly and exposes the expected surface."""

from __future__ import annotations

from cliver_playbook.app.rag import ROUTERS, Settings, get_settings, settings
from cliver_playbook.app.rag.settings import RagSettings


def test_settings_inherits_user_settings() -> None:
    s = Settings()
    # Inherits identity-domain fields: the user package exposes OIDC as
    # a nested block and the OAuth 2.1 provider as flat oauth21_*
    # fields (per the existing app.yaml schema — verified by reading
    # packages/backend/cliver-playbook-app-user/src/.../settings.py).
    assert hasattr(s, "oidc")
    assert hasattr(s, "oauth21_enabled")
    assert hasattr(s, "oauth21_issuer_url")
    # Adds the rag block
    assert isinstance(s.rag, RagSettings)


def test_rag_settings_defaults() -> None:
    r = RagSettings()
    # The shipped defaults are the offline-safe set: a fresh install
    # must work with no model download and no API key. Production
    # stages (bge-m3, bge-reranker-v2-m3) are explicit opt-ins in
    # app.yaml or env.
    assert r.chunker == "recursive"
    assert r.embedder == "stub"
    assert r.retriever == "pgvector-hybrid"
    assert r.reranker == "noop"
    assert r.llm == "stub"
    assert r.top_k == 20
    assert r.score_floor == 0.2
    assert r.max_upload_bytes == 20 * 1024 * 1024


def test_routers_is_a_list() -> None:
    assert isinstance(ROUTERS, list)


def test_get_settings_returns_settings_instance() -> None:
    # The proxy resolves to a Settings() when no runtime is bound yet;
    # what matters for the public surface is that the symbol exists and
    # the result carries the rag block.
    s = get_settings()
    assert isinstance(s, Settings)
    assert isinstance(s.rag, RagSettings)


def test_settings_proxy_is_a_lazy_settings() -> None:
    # The module-level `settings` is a process-aware lazy proxy (the
    # same pattern the mcp package uses). Asserting the type is stable
    # catches a regression where someone re-binds it to a plain
    # Settings() at import time and breaks the runtime binding.
    from cliver_playbook.app.basic.runtime import LazySettings

    assert isinstance(settings, LazySettings)
