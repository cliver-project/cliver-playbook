"""The mock Kingdee server stays inside the pinned read-only contract."""

from __future__ import annotations

import json
from pathlib import Path

from httpx import ASGITransport, AsyncClient

from cliver_playbook.app.rag_governance.testing.mock_kingdee import (
    ALLOWLISTED_TOOLS,
    MockKingdeeServer,
    allowlisted_names,
)

CONTRACT = Path(__file__).parent / "fixtures" / "kingdee" / "contract"
PERIOD_END = "2026-10-31T23:59:59+08:00"


def _contract(name: str) -> dict:
    return json.loads((CONTRACT / name).read_text(encoding="utf-8"))


async def test_tools_list_matches_contract(mock_kingdee_server: MockKingdeeServer) -> None:
    tools = await mock_kingdee_server.list_tools()

    assert [tool["name"] for tool in tools] == list(allowlisted_names())
    assert tools == _contract("mcp_tools_v0.2.0.json")["tools"]


async def test_tools_call_envelope_matches_contract(
    mock_kingdee_server: MockKingdeeServer,
) -> None:
    result = await mock_kingdee_server.call_tool(
        "kingdee_query_report",
        {
            "form_id": "GL_RPT_AccountBalance",
            "period": "2026-10",
            "data": {"StartRow": 0, "Limit": 10},
        },
    )
    contract = _contract("mcp_calls_v0.2.0.json")

    assert set(result) == set(contract["kingdee_query_report"]["success"])
    assert result["isError"] is False
    assert result["period"] == "2026-10"
    assert result["row_count"] == 3


async def test_unknown_period_is_not_substituted(mock_kingdee_server: MockKingdeeServer) -> None:
    result = await mock_kingdee_server.call_tool(
        "kingdee_query_report",
        {"form_id": "GL_RPT_AccountBalance", "period": "2025-01", "data": {}},
    )

    assert result["isError"] is True
    assert result["error"] == "not_found"
    assert result["data"] == []
    assert result["as_of"] is None


async def test_report_year_mismatch_is_not_substituted(
    mock_kingdee_server: MockKingdeeServer,
) -> None:
    result = await mock_kingdee_server.call_tool(
        "kingdee_query_report",
        {
            "form_id": "GL_RPT_AccountBalance",
            "data": {"Model": {"FENDYEAR": 2025, "FENDPERIOD": 1}},
        },
    )

    assert result["isError"] is True
    assert result["error"] == "not_found"


async def test_mock_reads_period_metadata_not_host_clock(
    mock_kingdee_server: MockKingdeeServer,
) -> None:
    result = await mock_kingdee_server.call_tool(
        "kingdee_query_report",
        {"form_id": "GL_RPT_AccountBalance", "data": {}},
    )

    assert result["as_of"] == PERIOD_END


async def test_every_allowlisted_tool_has_both_contract_envelopes() -> None:
    contract = _contract("mcp_calls_v0.2.0.json")

    for name in ALLOWLISTED_TOOLS:
        assert set(contract[name]["success"]) == set(contract[name]["error"])


async def test_every_allowlisted_tool_returns_a_success_envelope(
    mock_kingdee_server: MockKingdeeServer,
) -> None:
    calls = {
        "kingdee_query_report": {"form_id": "GL_RPT_AccountBalance", "data": {}},
        "kingdee_query_bills": {"form_id": "PUR_PurchaseOrder"},
        "kingdee_query_receipts": {},
        "kingdee_query_partners": {"partner_type": "BD_Customer"},
        "kingdee_get_fields": {"form_id": "GL_RPT_AccountBalance"},
        "kingdee_list_forms": {"keyword": "purchase"},
    }

    for name, args in calls.items():
        result = await mock_kingdee_server.call_tool(name, args)
        assert result["isError"] is False, (name, result)
        assert result["as_of"] == PERIOD_END
        assert result["row_count"] >= 1, name


async def test_missing_row_fixture_is_not_found(mock_kingdee_server: MockKingdeeServer) -> None:
    result = await mock_kingdee_server.call_tool(
        "kingdee_query_bills", {"form_id": "SAL_SaleOrder"}
    )

    assert result["isError"] is True
    assert result["error"] == "not_found"


async def test_unknown_tool_is_rejected(mock_kingdee_server: MockKingdeeServer) -> None:
    result = await mock_kingdee_server.call_tool("kingdee_save_bill", {})

    assert result["isError"] is True
    assert result["error"] == "unknown_tool"


async def test_asgi_transport_round_trips_the_jsonrpc_surface(
    mock_kingdee_server: MockKingdeeServer,
) -> None:
    async with AsyncClient(
        transport=ASGITransport(app=mock_kingdee_server.asgi_app),
        base_url="http://mock",
    ) as client:
        init = await client.post(
            "/mcp",
            json={"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
        )
        listed = await client.post(
            "/mcp", json={"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}}
        )
        called = await client.post(
            "/mcp",
            json={
                "jsonrpc": "2.0",
                "id": 3,
                "method": "tools/call",
                "params": {
                    "name": "kingdee_query_report",
                    "arguments": {"form_id": "GL_RPT_AccountBalance", "data": {}},
                },
            },
        )

    assert init.status_code == 200
    assert init.json()["result"]["serverInfo"]["name"] == "mock-kingdee"
    assert [tool["name"] for tool in listed.json()["result"]["tools"]] == list(allowlisted_names())
    envelope = called.json()["result"]["structuredContent"]
    assert envelope["isError"] is False
    assert envelope["period"] == "2026-10"
