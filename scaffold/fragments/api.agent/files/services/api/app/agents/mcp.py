"""MCP server selection seam.

The MCP client is an opt-in run resource. This module narrows the servers a
run connects to before AgentCore discovers their tools. An agent's static
``mcp_servers`` list is an allow-list; the run's ``mcp_servers`` resource is
the deployed catalogue; an optional ``mcp_server_selector`` chooses within
that intersection. Selection is fail-open: a selector error returns the full
allowed set instead of breaking the run.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Any, Protocol

from app.agents.contracts import AgentContext, AgentToolkit

logger = logging.getLogger(__name__)

_STOPWORDS = frozenset(
    {
        "about",
        "and",
        "are",
        "can",
        "create",
        "delete",
        "find",
        "for",
        "from",
        "get",
        "how",
        "into",
        "list",
        "our",
        "please",
        "query",
        "read",
        "search",
        "show",
        "that",
        "the",
        "this",
        "update",
        "what",
        "when",
        "where",
        "which",
        "with",
        "write",
        "you",
    }
)


@dataclass(frozen=True)
class McpServerDescriptor:
    name: str
    description: str = ""
    capabilities: tuple[str, ...] = ()


class McpServerSelector(Protocol):
    def select(
        self,
        message: str,
        candidates: list[str],
        catalog: list[McpServerDescriptor],
    ) -> list[str]: ...


class KeywordMcpServerSelector:
    """Small deterministic selector; projects inject a model-backed one."""

    def select(
        self,
        message: str,
        candidates: list[str],
        catalog: list[McpServerDescriptor],
    ) -> list[str]:
        descriptors = {
            descriptor.name: descriptor for descriptor in catalog if descriptor.name in candidates
        }
        if not descriptors:
            return candidates
        words = {
            word
            for word in re.findall(r"[a-z0-9_]+", message.lower())
            if len(word) >= 3 and word not in _STOPWORDS
        }
        matched: list[str] = []
        for name in candidates:
            descriptor = descriptors.get(name)
            if descriptor is None:
                matched.append(name)
                continue
            haystack = " ".join(
                [descriptor.name, descriptor.description, *descriptor.capabilities]
            ).lower()
            terms = {
                word
                for word in re.findall(r"[a-z0-9_]+", haystack)
                if len(word) >= 3 and word not in _STOPWORDS
            }
            if any(
                word == term or word.startswith(term) or term.startswith(word)
                for word in words
                for term in terms
            ):
                matched.append(name)
        return matched or candidates


def _normalize_catalog(raw: Any) -> list[McpServerDescriptor]:
    descriptors: list[McpServerDescriptor] = []
    if not isinstance(raw, (list, tuple)):
        return descriptors
    for item in raw:
        if isinstance(item, McpServerDescriptor):
            descriptors.append(item)
        elif isinstance(item, dict) and item.get("name"):
            descriptors.append(
                McpServerDescriptor(
                    name=str(item["name"]),
                    description=str(item.get("description", "")),
                    capabilities=tuple(
                        str(capability) for capability in item.get("capabilities", ())
                    ),
                )
            )
    return descriptors


def select_mcp_servers(context: AgentContext, toolkit: AgentToolkit) -> list[str] | None:
    """Return the servers to connect for this run, or ``None`` for no MCP."""
    configured = context.resources.get("mcp_servers")
    deployed = (
        [str(server) for server in configured] if isinstance(configured, (list, tuple)) else []
    )
    if toolkit.mcp_servers:
        allowed = [server for server in toolkit.mcp_servers if not deployed or server in deployed]
    else:
        allowed = deployed
    if not allowed:
        return None

    selector = context.resources.get("mcp_server_selector")
    if selector is None:
        selector = KeywordMcpServerSelector()
    catalog = _normalize_catalog(context.resources.get("mcp_server_catalog"))
    try:
        selected = selector.select(context.message, allowed, catalog)
    except Exception:  # selection must fail open
        logger.exception("MCP server selector failed; using all allowed servers")
        return allowed
    allowed_set = set(allowed)
    narrowed = [str(server) for server in selected if str(server) in allowed_set]
    return narrowed
