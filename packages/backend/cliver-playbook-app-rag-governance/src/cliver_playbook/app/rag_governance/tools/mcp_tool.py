"""An outbound, read-only MCP tool adapter.

KingdeeMCP exposes a hundred-odd tools, most of them mutating. Governance
never offers that surface to a model: the client starts with a curated
allowlist of read-only names, validates it against ``tools/list`` (and,
when supplied, a pinned contract fixture), and refuses to start if a
write tool slipped in. Runtime calls are checked again, so a planner
cannot smuggle a name past the startup gate.

The MCP SDK is optional. This module speaks the JSON-RPC shapes over
``httpx`` and accepts any duck-typed transport with ``list_tools`` and
``call_tool``; the ``mcp-client`` extra is only needed when a deployment
wants the SDK's stdio/session helpers. Core governance imports this
module without the extra installed.

A transport failure raises ``ToolContractError``; ``McpTool.invoke``
converts it to a ``ToolResult`` with ``error`` set so the facade narrates
"live data unavailable" instead of substituting a snapshot.
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Collection, Mapping, Sequence
from datetime import datetime
from typing import Any, Protocol

import httpx

from cliver_playbook.app.rag_governance.testing.mock_kingdee.fixtures import (
    ALLOWLISTED_TOOLS,
    is_write_tool,
)
from cliver_playbook.app.rag_governance.tools.base import (
    ToolContext,
    ToolResult,
    ToolSpec,
)

logger = logging.getLogger(__name__)

ENVELOPE_KEYS = (
    "tool",
    "period",
    "as_of",
    "isError",
    "error",
    "error_message",
    "data",
    "row_count",
)


class ToolContractError(Exception):
    """The server contract, allowlist, or transport broke the tool contract."""


class McpTransport(Protocol):
    """The two calls the client needs from an MCP connection."""

    async def list_tools(self) -> list[dict[str, Any]]: ...

    async def call_tool(self, name: str, args: dict[str, Any]) -> dict[str, Any]: ...


def _row_count(data: Any) -> int:
    if isinstance(data, list):
        return len(data)
    return 0 if data is None else 1


def _envelope(
    tool: str,
    *,
    period: str | None = None,
    as_of: str | None = None,
    data: Any = None,
    error: str | None = None,
    error_message: str | None = None,
) -> dict[str, Any]:
    return {
        "tool": tool,
        "period": period,
        "as_of": as_of,
        "isError": error is not None,
        "error": error,
        "error_message": error_message,
        "data": [] if error is not None else data,
        "row_count": 0 if error is not None else _row_count(data),
    }


def _parse_as_of(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value if value.tzinfo is not None else None
    if isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value)
        except ValueError:
            return None
        return parsed if parsed.tzinfo is not None else None
    return None


def _text_content(result: Mapping[str, Any]) -> str:
    parts = result.get("content")
    if not isinstance(parts, list):
        return ""
    return "".join(
        str(part.get("text", ""))
        for part in parts
        if isinstance(part, dict) and part.get("type") == "text"
    )


def _normalize_result(name: str, result: Mapping[str, Any]) -> dict[str, Any]:
    """Turn an MCP ``tools/call`` result into the governance envelope.

    The mock returns the envelope in ``structuredContent``. The real
    KingdeeMCP returns a JSON string in text content, and signals a
    business failure with ``{"error": true, "errors": [...]}`` while the
    MCP-level ``isError`` stays false — both shapes are handled here.
    """
    structured = result.get("structuredContent")
    if isinstance(structured, dict) and "isError" in structured:
        return dict(structured)

    text = _text_content(result)
    try:
        payload = json.loads(text) if text else None
    except ValueError:
        return _envelope(
            name,
            error="invalid_payload",
            error_message="tool content was not valid JSON",
        )

    if isinstance(payload, dict) and payload.get("error") is True:
        errors = payload.get("errors")
        messages: list[str] = []
        if isinstance(errors, list):
            messages = [
                str(item.get("message", item)) if isinstance(item, dict) else str(item)
                for item in errors
            ]
        return _envelope(
            name,
            error="tool_error",
            error_message="; ".join(messages) or "the ERP reported an error",
        )

    as_of = payload.get("as_of") if isinstance(payload, dict) else None
    period = payload.get("period") if isinstance(payload, dict) else None
    return _envelope(
        name,
        period=period if isinstance(period, str) else None,
        as_of=as_of if isinstance(as_of, str) else None,
        data=payload,
    )


def _parse_sse(body: str) -> dict[str, Any]:
    """Take the last JSON object from an SSE response body."""
    for block in reversed(body.split("\n\n")):
        data_lines = [line[5:].strip() for line in block.splitlines() if line.startswith("data:")]
        if data_lines:
            try:
                return json.loads("\n".join(data_lines))
            except ValueError:
                continue
    raise ToolContractError("MCP server returned an unparseable event stream")


class _HttpTransport:
    """JSON-RPC over streamable HTTP; no MCP SDK required."""

    def __init__(
        self,
        url: str,
        *,
        timeout_seconds: float,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._url = url
        self._timeout = timeout_seconds
        self._client = client
        self._owns_client = client is None
        self._initialized = False
        self._session_id: str | None = None
        self._next_id = 0

    async def _ensure_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=self._timeout)
        return self._client

    async def _rpc(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        client = await self._ensure_client()
        if not self._initialized:
            await self._initialize(client)
        self._next_id += 1
        headers = {"accept": "application/json, text/event-stream"}
        if self._session_id is not None:
            headers["mcp-session-id"] = self._session_id
        response = await client.post(
            self._url,
            json={
                "jsonrpc": "2.0",
                "id": self._next_id,
                "method": method,
                "params": params,
            },
            headers=headers,
        )
        response.raise_for_status()
        session_id = response.headers.get("mcp-session-id")
        if session_id:
            self._session_id = session_id
        if "text/event-stream" in response.headers.get("content-type", ""):
            body = _parse_sse(response.text)
        else:
            body = response.json()
        if "error" in body:
            error = body["error"]
            message = error.get("message", error) if isinstance(error, dict) else error
            raise ToolContractError(f"MCP error: {message}")
        result = body.get("result")
        if not isinstance(result, dict):
            raise ToolContractError("MCP response has no result object")
        return result

    async def _initialize(self, client: httpx.AsyncClient) -> None:
        response = await client.post(
            self._url,
            json={
                "jsonrpc": "2.0",
                "id": 0,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {},
                    "clientInfo": {"name": "cliver-governance", "version": "0.1.0"},
                },
            },
            headers={"accept": "application/json, text/event-stream"},
        )
        response.raise_for_status()
        session_id = response.headers.get("mcp-session-id")
        if session_id:
            self._session_id = session_id
        await client.post(
            self._url,
            json={"jsonrpc": "2.0", "method": "notifications/initialized"},
            headers={"accept": "application/json"},
        )
        self._initialized = True

    async def list_tools(self) -> list[dict[str, Any]]:
        result = await self._rpc("tools/list", {})
        tools = result.get("tools")
        if not isinstance(tools, list):
            raise ToolContractError("tools/list did not return a tool list")
        return tools

    async def call_tool(self, name: str, args: dict[str, Any]) -> dict[str, Any]:
        result = await self._rpc("tools/call", {"name": name, "arguments": args})
        if result.get("isError") is True:
            return _envelope(
                name,
                error="mcp_error",
                error_message=_text_content(result) or "the MCP call failed",
            )
        return _normalize_result(name, result)

    async def aclose(self) -> None:
        if self._client is not None and self._owns_client:
            await self._client.aclose()
        self._client = None


class McpToolClient:
    """A contract-validated, read-only client for one MCP endpoint.

    ``server_ref`` is either an HTTP URL or any object implementing
    ``McpTransport`` (the mock's in-process transport, an SDK session
    wrapper, or a test double).
    """

    def __init__(
        self,
        server_ref: str | McpTransport,
        *,
        timeout_seconds: float = 10.0,
        retries: int = 1,
        contract_tools: Sequence[Mapping[str, Any]] | None = None,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        if retries < 0:
            raise ValueError("retries cannot be negative")
        self._transport: McpTransport = (
            _HttpTransport(server_ref, timeout_seconds=timeout_seconds, client=http_client)
            if isinstance(server_ref, str)
            else server_ref
        )
        self._timeout = timeout_seconds
        self._retries = retries
        self._contract_tools = (
            {str(tool["name"]): dict(tool) for tool in contract_tools}
            if contract_tools is not None
            else None
        )
        self._allowlist: frozenset[str] | None = None

    @property
    def allowlist(self) -> frozenset[str] | None:
        return self._allowlist

    async def list_tools(self) -> list[dict[str, Any]]:
        return await self._transport.list_tools()

    async def _validate_allowlist(self, allowlist: Collection[str]) -> frozenset[str]:
        requested = frozenset(allowlist)
        if not requested:
            raise ToolContractError("the allowlist cannot be empty")
        for name in sorted(requested):
            if is_write_tool(name):
                raise ToolContractError(f"write tool {name!r} cannot be exposed to a model")
            if name not in ALLOWLISTED_TOOLS:
                raise ToolContractError(f"tool {name!r} is not in the curated read-only contract")

        discovered = {str(tool["name"]): tool for tool in await self.list_tools()}
        missing = sorted(requested - discovered.keys())
        if missing:
            raise ToolContractError(f"server does not expose allowlisted tool(s): {missing}")

        if self._contract_tools is not None:
            for name in sorted(requested):
                expected = self._contract_tools.get(name)
                if expected is None:
                    raise ToolContractError(f"contract fixture does not describe {name!r}")
                if discovered[name].get("inputSchema") != expected.get("inputSchema"):
                    raise ToolContractError(
                        f"tools/list schema for {name!r} diverges from the pinned contract"
                    )

        self._allowlist = requested
        return requested

    async def call_tool(self, name: str, args: dict[str, Any]) -> dict[str, Any]:
        if self._allowlist is not None and name not in self._allowlist:
            raise ToolContractError(f"tool {name!r} is not allowlisted")
        last_error: Exception | None = None
        for attempt in range(self._retries + 1):
            try:
                return await asyncio.wait_for(
                    self._transport.call_tool(name, args),
                    timeout=self._timeout,
                )
            except (TimeoutError, httpx.TransportError) as exc:
                last_error = exc
                logger.warning(
                    "MCP tool %s failed (attempt %d/%d): %s",
                    name,
                    attempt + 1,
                    self._retries + 1,
                    exc,
                )
        raise ToolContractError(
            f"MCP tool {name!r} failed after {self._retries + 1} attempt(s): {last_error}"
        ) from last_error

    async def aclose(self) -> None:
        close = getattr(self._transport, "aclose", None)
        if close is not None:
            await close()


class McpTool:
    """The ``Tool`` adapter over one allowlisted MCP tool."""

    def __init__(
        self,
        client: McpToolClient,
        name: str,
        *,
        description: str = "",
        input_schema: dict[str, Any] | None = None,
        result_cap: int = 1000,
        max_staleness_seconds: int | None = None,
    ) -> None:
        self._client = client
        self.spec = ToolSpec(
            name=name,
            description=description,
            input_schema=input_schema or {},
            read_only=True,
            result_cap=result_cap,
            max_staleness_seconds=max_staleness_seconds,
        )

    @classmethod
    def from_descriptor(
        cls,
        client: McpToolClient,
        descriptor: Mapping[str, Any],
        **kwargs: Any,
    ) -> McpTool:
        return cls(
            client,
            str(descriptor["name"]),
            description=str(descriptor.get("description", "")),
            input_schema=dict(descriptor.get("inputSchema") or {}),
            **kwargs,
        )

    async def invoke(self, args: dict[str, Any], ctx: ToolContext) -> ToolResult:
        try:
            envelope = await self._client.call_tool(self.spec.name, args)
        except ToolContractError as exc:
            return ToolResult(
                tool=self.spec.name,
                data=None,
                as_of=ctx.as_of,
                row_count=0,
                error=f"tool_contract_error: {exc}",
            )

        if envelope.get("isError"):
            detail = envelope.get("error_message") or envelope.get("error") or "unknown error"
            return ToolResult(
                tool=self.spec.name,
                data=None,
                as_of=ctx.as_of,
                row_count=0,
                error=f"{envelope.get('error')}: {detail}",
            )

        as_of = _parse_as_of(envelope.get("as_of")) or ctx.as_of
        data = envelope.get("data")
        truncated = False
        if isinstance(data, list):
            cap = min(self.spec.result_cap, ctx.caps.max_rows)
            truncated = len(data) > cap
            data = data[:cap]
            row_count = len(data)
        else:
            row_count = _row_count(data)
        return ToolResult(
            tool=self.spec.name,
            data=data,
            as_of=as_of,
            row_count=row_count,
            truncated=truncated,
        )
