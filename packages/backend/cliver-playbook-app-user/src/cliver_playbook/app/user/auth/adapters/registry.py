"""Registry of provider adapters, keyed by the ``adapter`` setting value.

Registration happens at import time, like the permission catalog and the RAG
stage registries. A composing project registers a private adapter once, before
the first request, and then selects it from configuration.
"""

from __future__ import annotations

from cliver_playbook.app.user.auth.provider import ProviderAdapter

_adapters: dict[str, ProviderAdapter] = {}


def register_adapter(name: str, adapter: ProviderAdapter) -> None:
    """Register ``adapter`` under ``name``; duplicate names are an error."""
    if not name:
        raise ValueError("provider adapter name must be non-empty")
    if name in _adapters:
        raise ValueError(f"provider adapter already registered: {name!r}")
    _adapters[name] = adapter


def get_adapter(name: str) -> ProviderAdapter:
    """Return the adapter registered under ``name``."""
    try:
        return _adapters[name]
    except KeyError as exc:
        raise KeyError(f"unknown provider adapter: {name!r}") from exc


def adapter_names() -> set[str]:
    """Every currently registered adapter name."""
    return set(_adapters)


def _register_defaults() -> None:
    from cliver_playbook.app.user.auth.adapters import alipay, wechat

    register_adapter("wechat", wechat.WeChatAdapter())
    register_adapter("alipay", alipay.AlipayAdapter())


_register_defaults()
