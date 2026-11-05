"""The outbound MCP client validates the contract before it is trusted."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient

from cliver_playbook.app.rag_governance.testing.mock_kingdee import (
    ALLOWLISTED_TOOLS,
    MockKingdeeServer,
    allowlisted_names,
)
from cliver_playbook.app.rag_governance.tools import (
    McpTool,
    McpToolClient,
    ToolCaps,
    ToolContext,
    ToolContractError,
    ToolResult,
)

CONTRACT = Path(__file__).parent / "fixtures" / "kingdee" / "contract"
PERIOD_END = datetime(2026, 10, 31, 23, 59, 59, tzinfo=timezone(timedelta(hours=8)))
NOW = datetime(2026, 11, 1, tzinfo=timezone(timedelta(hours=8)))


def _contract_tools() -> list[dict[str, Any]]:
    payload = json.loads((CONTRACT / "mcp_tools_v0.2.0.json").read_text(encoding="utf-8"))
    return payload["tools"]


def _ctx() -> ToolContext:
    return ToolContext(
        viewer=None,
        access=None,
        project_id="project-1",
        as_of=NOW,
        masking=None,
        caps=ToolCaps(),
        registry=None,
        call_id="call-1",
    )


class _EmptyTransport:
    async def list_tools(self) -> list[dict[str, Any]]:
        return []

    async def call_tool(self, name: str, args: dict[str, Any]) -> dict[str, Any]:
        raise AssertionError("not called")


class _DriftedTransport:
    def __init__(self, tools: list[dict[str, Any]]) -> None:
        self._tools = tools

    async def list_tools(self) -> list[dict[str, Any]]:
        return self._tools

    async def call_tool(self, name: str, args: dict[str, Any]) -> dict[str, Any]:
        raise AssertionError("not called")


class _FailingOnceTransport:
    def __init__(self, server: MockKingdeeServer) -> None:
        self._server = server
        self.calls = 0

    async def list_tools(self) -> list[dict[str, Any]]:
        return await self._server.list_tools()

    async def call_tool(self, name: str, args: dict[str, Any]) -> dict[str, Any]:
        self.calls += 1
        if self.calls == 1:
            raise TimeoutError("first attempt timed out")
        return await self._server.call_tool(name, args)


class _AlwaysFailingTransport:
    def __init__(self) -> None:
        self.calls = 0

    async def list_tools(self) -> list[dict[str, Any]]:
        return []

    async def call_tool(self, name: str, args: dict[str, Any]) -> dict[str, Any]:
        self.calls += 1
        raise TimeoutError("offline")


async def test_curated_allowlist_validates_against_tools_list(
    mock_kingdee_server: MockKingdeeServer,
) -> None:
    client = McpToolClient(mock_kingdee_server.in_process_transport())

    validated = await client._validate_allowlist(ALLOWLISTED_TOOLS)

    assert validated == frozenset(ALLOWLISTED_TOOLS)
    assert client.allowlist == validated


async def test_expose_write_tool_is_rejected_by_client_startup(
    mock_kingdee_server: MockKingdeeServer,
) -> None:
    client = McpToolClient(mock_kingdee_server.in_process_transport())

    with pytest.raises(ToolContractError, match="write tool"):
        await client._validate_allowlist({"kingdee_save_bill"})


async def test_uncurated_read_tool_is_rejected_by_client_startup(
    mock_kingdee_server: MockKingdeeServer,
) -> None:
    client = McpToolClient(mock_kingdee_server.in_process_transport())

    with pytest.raises(ToolContractError, match="curated read-only contract"):
        await client._validate_allowlist({"kingdee_query_inventory"})


async def test_allowlisted_name_absent_from_server_is_rejected() -> None:
    client = McpToolClient(_EmptyTransport())

    with pytest.raises(ToolContractError, match="does not expose"):
        await client._validate_allowlist({"kingdee_query_report"})


async def test_tools_list_schema_must_match_the_pinned_contract() -> None:
    tools = _contract_tools()
    tools[0]["inputSchema"]["properties"]["form_id"]["type"] = "number"
    client = McpToolClient(_DriftedTransport(tools), contract_tools=_contract_tools())

    with pytest.raises(ToolContractError, match="diverges"):
        await client._validate_allowlist({"kingdee_query_report"})


async def test_runtime_call_outside_the_validated_allowlist_is_refused(
    mock_kingdee_server: MockKingdeeServer,
) -> None:
    client = McpToolClient(mock_kingdee_server.in_process_transport())
    await client._validate_allowlist({"kingdee_query_report"})

    with pytest.raises(ToolContractError, match="not allowlisted"):
        await client.call_tool("kingdee_query_bills", {"form_id": "PUR_PurchaseOrder"})


async def test_client_normalizes_the_success_envelope(
    mock_kingdee_server: MockKingdeeServer,
) -> None:
    client = McpToolClient(mock_kingdee_server.in_process_transport())
    await client._validate_allowlist({"kingdee_query_report"})

    envelope = await client.call_tool(
        "kingdee_query_report",
        {"form_id": "GL_RPT_AccountBalance", "data": {}},
    )

    assert envelope["isError"] is False
    assert envelope["as_of"] == PERIOD_END.isoformat()
    assert envelope["row_count"] == 3
    assert len(envelope["data"]) == 3


async def test_mcp_tool_normalizes_into_a_tool_result(
    mock_kingdee_server: MockKingdeeServer,
) -> None:
    client = McpToolClient(mock_kingdee_server.in_process_transport())
    await client._validate_allowlist({"kingdee_query_report"})
    descriptor = next(
        tool for tool in await client.list_tools() if tool["name"] == "kingdee_query_report"
    )
    tool = McpTool.from_descriptor(client, descriptor)

    result = await tool.invoke({"form_id": "GL_RPT_AccountBalance", "data": {}}, _ctx())

    assert isinstance(result, ToolResult)
    assert result.error is None
    assert result.as_of == PERIOD_END
    assert result.row_count == 3
    assert isinstance(result.data, list)


async def test_mcp_tool_maps_a_business_error_to_an_explicit_result(
    mock_kingdee_server: MockKingdeeServer,
) -> None:
    client = McpToolClient(mock_kingdee_server.in_process_transport())
    await client._validate_allowlist({"kingdee_query_report"})
    descriptor = next(
        tool for tool in await client.list_tools() if tool["name"] == "kingdee_query_report"
    )
    tool = McpTool.from_descriptor(client, descriptor)

    result = await tool.invoke(
        {"form_id": "GL_RPT_AccountBalance", "period": "2025-01", "data": {}},
        _ctx(),
    )

    assert result.error is not None
    assert "not_found" in result.error
    assert result.data is None
    # An outage is never dated to the ERP period it could not read.
    assert result.as_of == NOW


async def test_a_transient_timeout_is_retried_once(
    mock_kingdee_server: MockKingdeeServer,
) -> None:
    transport = _FailingOnceTransport(mock_kingdee_server)
    client = McpToolClient(transport, retries=1, timeout_seconds=1.0)

    envelope = await client.call_tool(
        "kingdee_query_report", {"form_id": "GL_RPT_AccountBalance", "data": {}}
    )

    assert envelope["isError"] is False
    assert transport.calls == 2


async def test_exhausted_retries_raise_a_contract_error() -> None:
    transport = _AlwaysFailingTransport()
    client = McpToolClient(transport, retries=1, timeout_seconds=1.0)

    with pytest.raises(ToolContractError, match="failed after 2 attempt"):
        await client.call_tool("kingdee_query_report", {"form_id": "X", "data": {}})
    assert transport.calls == 2


async def test_http_transport_speaks_the_mock_jsonrpc_surface(
    mock_kingdee_server: MockKingdeeServer,
) -> None:
    async with AsyncClient(
        transport=ASGITransport(app=mock_kingdee_server.asgi_app),
        base_url="http://mock",
    ) as http:
        client = McpToolClient("http://mock/mcp", http_client=http)
        await client._validate_allowlist(allowlisted_names())
        envelope = await client.call_tool(
            "kingdee_query_report", {"form_id": "GL_RPT_AccountBalance", "data": {}}
        )
        await client.aclose()

    assert [tool["name"] for tool in _contract_tools()] == list(allowlisted_names())
    assert envelope["isError"] is False
    assert envelope["as_of"] == PERIOD_END.isoformat()
