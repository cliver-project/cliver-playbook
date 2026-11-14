"""MCP discovery, auth/config loading and per-run client lifecycle.

Server configs are project-owned deployment data, never committed. Discovery
reads cliver's normal places plus an explicit ``CLIVER_AGENT_MCP_CONFIG`` file
(or ``CLIVER_AGENT_MCP_EXTRA_PATHS``). The client is opt-in; a discovery or
start failure logs and leaves the run without MCP tools instead of failing it.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from pathlib import Path

from cliver_core.mcp import MCPClient, MCPDiscoveryResult, discover_mcp_servers

from app.agents.mcp import McpServerDescriptor
from app.settings import Settings

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class McpRuntime:
    client: MCPClient
    servers: tuple[str, ...]
    descriptors: tuple[McpServerDescriptor, ...]
    discovery: MCPDiscoveryResult


def _config_paths(settings: Settings) -> list[str]:
    paths: list[str] = []
    if settings.agent_mcp_config.strip():
        paths.append(str(Path(settings.agent_mcp_config.strip()).expanduser()))
    if settings.agent_mcp_extra_paths.strip():
        paths.extend(
            str(Path(value).expanduser())
            for value in settings.agent_mcp_extra_paths.split(os.pathsep)
            if value.strip()
        )
    return paths


def discover_servers(settings: Settings) -> MCPDiscoveryResult:
    """Discover MCP configs without starting any server."""
    return discover_mcp_servers(extra_paths=_config_paths(settings))


def descriptors_from_discovery(
    discovery: MCPDiscoveryResult,
) -> tuple[McpServerDescriptor, ...]:
    descriptors: list[McpServerDescriptor] = []
    for name, config in discovery.servers.items():
        capabilities = config.get("capabilities")
        descriptors.append(
            McpServerDescriptor(
                name=name,
                description=str(config.get("description", "")),
                capabilities=tuple(str(value) for value in capabilities)
                if isinstance(capabilities, (list, tuple))
                else (),
            )
        )
    return tuple(descriptors)


def build_mcp_client(settings: Settings) -> MCPClient | None:
    """Build a client from discovery without starting it (test/CLI seam)."""
    if not settings.agent_mcp_enabled:
        return None
    discovery = discover_servers(settings)
    _log_problems(discovery)
    if not discovery.servers:
        return None
    return MCPClient(discovery.servers)


async def open_mcp_runtime(settings: Settings) -> McpRuntime | None:
    """Discover, start and return a per-run MCP client, or ``None``."""
    if not settings.agent_mcp_enabled:
        return None
    discovery = discover_servers(settings)
    _log_problems(discovery)
    if not discovery.servers:
        return None
    client = MCPClient(discovery.servers)
    try:
        await client.start()
    except Exception:  # MCP is optional; run without its tools
        logger.exception("MCP client failed to start; continuing without MCP tools")
        try:
            await client.close()
        except Exception:
            logger.exception("MCP client cleanup failed")
        return None
    return McpRuntime(
        client=client,
        servers=tuple(discovery.servers),
        descriptors=descriptors_from_discovery(discovery),
        discovery=discovery,
    )


async def close_mcp_runtime(runtime: McpRuntime | None) -> None:
    if runtime is None:
        return
    try:
        await runtime.client.close()
    except Exception:
        logger.exception("MCP client shutdown failed")


def _log_problems(discovery: MCPDiscoveryResult) -> None:
    for problem in discovery.problems:
        level = logging.ERROR if problem.severity == "error" else logging.WARNING
        logger.log(
            level,
            "MCP discovery %s: %s (source=%s server=%s)",
            problem.code,
            problem.message,
            problem.source,
            problem.server or "-",
        )
