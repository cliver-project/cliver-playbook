"""AgentCore construction from project settings.

One place builds the LLM binding, the skill manager and the optional System
One selector. The planner and every sub-agent runner step use it, so provider
configuration and catalogue selection never leak into individual agents.
"""

from __future__ import annotations

import logging
import threading
from pathlib import Path
from typing import Any

from cliver_core import ModelBinding, SkillManager, presets
from cliver_core.system_one.selector import SystemOneSelector

from app.settings import Settings

logger = logging.getLogger(__name__)

_local_system_one_lock = threading.Lock()
_local_system_one_providers: dict[str, Any] = {}


def has_agent_model(settings: Settings) -> bool:
    """Whether the project configured an API-plane model."""
    return bool(settings.agent_llm_model.strip())


def build_llm_binding(settings: Settings) -> ModelBinding | None:
    """Build the chat binding, or return ``None`` when no model is configured.

    ``Settings`` already rejects a model without an endpoint or provider, so a
    non-empty model here is complete enough for ``ModelBinding.llm``.
    """
    if not has_agent_model(settings):
        return None
    params: dict[str, object] = {"temperature": settings.agent_llm_temperature}
    if settings.agent_llm_max_tokens is not None:
        params["max_tokens"] = settings.agent_llm_max_tokens
    return ModelBinding.llm(
        model=settings.agent_llm_model,
        api_key=settings.agent_llm_api_key,
        base_url=settings.agent_llm_base_url,
        protocol=settings.agent_llm_protocol,
        provider_name=settings.agent_llm_provider or None,
        client_timeout=settings.agent_llm_timeout,
        **params,
    )


def build_system_one_binding(settings: Settings) -> ModelBinding | None:
    """Build the configured System One binding, or ``None`` when disabled.

    Supported providers:
    - ``local``: in-process laya via ``cliver-core[local-laya]``; the loaded
      provider is cached for the process lifetime.
    - ``bailian``: Aliyun Bailian's decision model (workspace id or an explicit
      base URL).
    - ``typesafe``: TypeSafe Jev.
    - ``http``: any endpoint speaking the shared ``/v1/systemone`` wire.
    """
    provider = settings.agent_system_one_provider.strip().lower()
    if not provider:
        return None

    if provider == "local":
        # Imported lazily: local inference is optional and heavy.
        from cliver_core.local import LocalSystemOneProvider, local_system_one

        model = settings.agent_system_one_model.strip() or "multilingual"
        with _local_system_one_lock:
            local = _local_system_one_providers.get(model)
            if local is None:
                local = LocalSystemOneProvider(model=model, backend="laya")
                _local_system_one_providers[model] = local
        return local_system_one(provider=local)

    if provider == "bailian":
        return presets.bailian_system_one(
            workspace_id=settings.agent_system_one_workspace_id,
            api_key=settings.agent_system_one_api_key or None,
            model=settings.agent_system_one_model or "decision-model-preview",
            region=settings.agent_system_one_region,
            base_url=settings.agent_system_one_base_url,
        )

    if provider == "typesafe":
        return presets.typesafe_system_one(
            api_key=settings.agent_system_one_api_key or None,
            model=settings.agent_system_one_model or "jev-latest",
            base_url=settings.agent_system_one_base_url,
        )

    if provider == "http":
        return ModelBinding.system_one(
            model=settings.agent_system_one_model.strip(),
            api_key=settings.agent_system_one_api_key,
            base_url=settings.agent_system_one_base_url.strip(),
            path="/v1/systemone",
        )

    raise ValueError(f"Unknown System One provider {provider!r}")


def build_system_one_selector(
    settings: Settings, *, binding: ModelBinding | None = None
) -> SystemOneSelector | None:
    """Build the fail-open tool/skill selector, or ``None`` when disabled.

    Any construction failure (missing optional local dependency, bad endpoint,
    invalid selector bounds) degrades to no selector; the run continues with
    the full catalogue. The selector itself is also fail-open at call time.
    """
    try:
        resolved = binding or build_system_one_binding(settings)
        if resolved is None:
            return None
        provider = settings.agent_system_one_provider.strip().lower()
        return SystemOneSelector(
            binding=resolved,
            min_tools=settings.agent_system_one_min_tools,
            min_skills=settings.agent_system_one_min_skills,
            top_k_tools=settings.agent_system_one_top_k_tools,
            top_k_skills=settings.agent_system_one_top_k_skills,
            fit_threshold=settings.agent_system_one_fit_threshold,
            # The local provider rejects the HTTP `timeout` option.
            timeout=(None if provider == "local" else settings.agent_system_one_timeout),
        )
    except Exception as exc:  # noqa: BLE001 — selection must fail open
        logger.warning("System One selector disabled: %s", exc)
        return None


async def close_system_one_providers() -> None:
    """Release cached local decision models (application shutdown/tests)."""
    with _local_system_one_lock:
        providers = list(_local_system_one_providers.values())
        _local_system_one_providers.clear()
    for provider in providers:
        try:
            await provider.close()
        except Exception as exc:  # noqa: BLE001 — best-effort shutdown
            logger.warning("Could not close local System One provider: %s", exc)


def build_skill_manager(settings: Settings, agent_name: str | None = None) -> SkillManager | None:
    """Load project skills with per-agent scoping.

    ``agent_skills_dir`` is the skills root. It may contain skills directly
    (the previous layout), a ``shared/`` directory visible to every agent, and
    one directory per agent name. Later sources override earlier ones by skill
    name, so the precedence is: root < shared < agent. An empty setting
    disables discovery, and missing directories are harmless.
    """
    root_text = settings.agent_skills_dir.strip()
    if not root_text:
        return None
    root = Path(root_text)
    sources: list[Path] = [root]
    sources.append(root / "shared")
    if agent_name:
        sources.append(root / agent_name)
    return SkillManager([str(path) for path in sources])
