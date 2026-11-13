"""The finance-KPI demo application: the governance app plus its tools.

``cliver_playbook.app.rag_governance.app.create_app`` assembles the stack but
deliberately registers no tools: a scenario does that at composition time
(the package README documents the seam). This module is that scenario for the
local demo — the vendor MCP tools (the mock Kingdee server on
``GOV_DEMO_MOCK_URL``, default ``http://127.0.0.1:18080/mcp``) and the finance
composites from :mod:`examples.finance_kpi.tools`.

Registration runs in the app's lifespan and is best effort: when the mock is
not reachable the app still boots with the empty registry, and a governed
query that routes to tools fails with the tool-profile error instead of the
whole demo going down. Fixing the mock and restarting is the remedy.
"""

from __future__ import annotations

import logging
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from cliver_playbook.app.rag_governance.app import create_app as create_governance_app
from cliver_playbook.app.rag_governance.stages import type_classifiers
from cliver_playbook.app.rag_governance.testing.mock_kingdee import ALLOWLISTED_TOOLS
from cliver_playbook.app.rag_governance.tools import McpTool, McpToolClient, ToolRegistry
from cliver_playbook.app.rag_governance.tools.mcp_tool import ToolContractError

from . import stages
from .tools import register

# The corpus taxonomy is a scenario stage: register it at composition time,
# before the worker can claim an ingest job.
stages.register(type_classifiers)

logger = logging.getLogger(__name__)

DEFAULT_MOCK_URL = "http://127.0.0.1:18080/mcp"


async def _register_tools(app: FastAPI, mock_url: str) -> None:
    registry: ToolRegistry = app.state.tool_registry
    client = McpToolClient(mock_url)
    await client._validate_allowlist(frozenset(ALLOWLISTED_TOOLS))
    for descriptor in await client.list_tools():
        registry.register(McpTool.from_descriptor(client, descriptor))
    register(registry)
    registry.validate()
    logger.info("finance demo tools registered from %s", mock_url)


def create_demo_app() -> FastAPI:
    """The governance app with the finance scenario's tools registered."""
    app = create_governance_app()
    mock_url = os.environ.get("GOV_DEMO_MOCK_URL", DEFAULT_MOCK_URL)
    inner = app.router.lifespan_context

    @asynccontextmanager
    async def lifespan(a: FastAPI) -> AsyncIterator[None]:
        async with inner(a):
            try:
                await _register_tools(a, mock_url)
            except (ToolContractError, OSError) as exc:
                logger.warning(
                    "finance demo tools NOT registered (%s: %s); tool-strategy "
                    "queries will fail until the mock is reachable on %s",
                    exc.__class__.__name__,
                    exc,
                    mock_url,
                )
            yield

    app.router.lifespan_context = lifespan
    return app
