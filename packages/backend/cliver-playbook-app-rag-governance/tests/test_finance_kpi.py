"""The finance composites reconcile to the raw Kingdee-shaped fixtures."""

from __future__ import annotations

import json
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from cliver_playbook.app.rag_governance.testing.mock_kingdee import (
    ALLOWLISTED_TOOLS,
    MockKingdeeServer,
)
from cliver_playbook.app.rag_governance.tools import (
    McpTool,
    McpToolClient,
    RestrictedToolInvoker,
    ToolCaps,
    ToolContext,
    ToolDeniedError,
    ToolRegistry,
)
from examples.finance_kpi.tools import latest_closed, load_catalog, register

EXAMPLES = Path(__file__).resolve().parents[1] / "examples" / "finance_kpi"
FIXTURES = EXAMPLES / "fixtures" / "kingdee" / "2026-10"
SHANGHAI = timezone(timedelta(hours=8))
# The question's reference instant. The period cutoff in the fixture is
# one second earlier, as the design's live-tool walkthrough specifies.
NOW = datetime(2026, 11, 1, tzinfo=SHANGHAI)
TOP_TOOLS = frozenset({"finance_kpi_snapshot", "finance_receivables_aging"})


def _expected(name: str) -> dict[str, Any]:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


async def _registry(
    server: MockKingdeeServer,
    catalog: Any = None,
) -> ToolRegistry:
    client = McpToolClient(server.in_process_transport())
    await client._validate_allowlist(ALLOWLISTED_TOOLS)
    registry = ToolRegistry()
    for descriptor in await client.list_tools():
        registry.register(McpTool.from_descriptor(client, descriptor))
    register(registry, catalog=catalog)
    registry.validate()
    return registry


def _ctx(registry: ToolRegistry, *, audit: Any = None) -> ToolContext:
    invoker = RestrictedToolInvoker(registry, TOP_TOOLS, audit=audit, depth=0)
    return ToolContext(
        viewer=None,
        access=None,
        project_id="finance-kpi-demo",
        as_of=NOW,
        masking=None,
        caps=ToolCaps(),
        registry=invoker,
        call_id="test-call",
    )


@pytest.fixture()
def mock_server() -> MockKingdeeServer:
    return MockKingdeeServer(EXAMPLES / "fixtures" / "kingdee", period="2026-10")


@pytest.fixture()
async def finance_registry(mock_server: MockKingdeeServer) -> ToolRegistry:
    return await _registry(mock_server)


@pytest.fixture()
def project_ctx(finance_registry: ToolRegistry) -> ToolContext:
    return _ctx(finance_registry)


async def test_composite_output_matches_fixture(project_ctx: ToolContext) -> None:
    result = await project_ctx.registry.invoke(
        "finance_kpi_snapshot", {"period": "2026-10"}, project_ctx
    )
    expected = _expected("finance_kpi_snapshot.expected.json")

    assert result.error is None
    assert result.data["period"] == "2026-10"
    assert result.data["as_of"] == expected["as_of"]
    assert result.data["currency"] == "CNY"
    for key, value in expected.items():
        if key in {"period", "as_of", "currency"}:
            assert result.data[key] == value
        else:
            assert result.data[key] == Decimal(value)
    assert result.as_of == datetime.fromisoformat(expected["as_of"])


async def test_low_level_rows_reconcile_to_composite(project_ctx: ToolContext) -> None:
    snapshot = await project_ctx.registry.invoke(
        "finance_kpi_snapshot", {"period": "2026-10"}, project_ctx
    )
    rows = json.loads((FIXTURES / "gl_account_balance.json").read_text(encoding="utf-8"))

    for metric in ("revenue", "budget_revenue", "net_profit"):
        low_level = sum(Decimal(row["amount"]) for row in rows if row["metric"] == metric)
        assert low_level == snapshot.data[metric], metric

    cost = sum(Decimal(row["amount"]) for row in rows if row["metric"] == "cost_of_revenue")
    assert snapshot.data["gross_profit"] == snapshot.data["revenue"] - cost


async def test_aging_output_matches_fixture(project_ctx: ToolContext) -> None:
    result = await project_ctx.registry.invoke(
        "finance_receivables_aging", {"period": "2026-10"}, project_ctx
    )
    expected = _expected("finance_receivables_aging.expected.json")
    rows = json.loads((FIXTURES / "ar_aging_rows.json").read_text(encoding="utf-8"))

    assert result.error is None
    assert result.data["total"] == Decimal(expected["total"])
    assert result.data["total"] == sum(Decimal(row["FENDAMOUNTFOR"]) for row in rows)
    for bucket, amount in expected["buckets"].items():
        assert result.data["buckets"][bucket] == Decimal(amount)
    assert result.data["over_90d_ratio"] == Decimal(expected["over_90d_ratio"])
    assert result.data["warning_threshold"] == Decimal(expected["warning_threshold"])
    assert result.data["warning"] is True


async def test_symbolic_period_resolves_against_injected_as_of(
    project_ctx: ToolContext,
) -> None:
    result = await project_ctx.registry.invoke(
        "finance_kpi_snapshot", {"period": "latest_closed"}, project_ctx
    )

    assert result.error is None
    assert result.data["period"] == "2026-10"


@pytest.mark.parametrize(
    ("moment", "expected"),
    [
        (datetime(2026, 11, 1, tzinfo=SHANGHAI), "2026-10"),
        (datetime(2026, 10, 31, 23, 59, 59, tzinfo=SHANGHAI), "2026-10"),
        (datetime(2026, 10, 30, 12, tzinfo=SHANGHAI), "2026-09"),
        (datetime(2026, 1, 15, tzinfo=SHANGHAI), "2025-12"),
    ],
)
def test_latest_closed_resolution(moment: datetime, expected: str) -> None:
    assert latest_closed(moment) == expected


def test_latest_closed_rejects_a_naive_reference_time() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        latest_closed(datetime(2026, 11, 1))


async def test_unknown_period_is_an_explicit_error(project_ctx: ToolContext) -> None:
    result = await project_ctx.registry.invoke(
        "finance_kpi_snapshot", {"period": "2025-01"}, project_ctx
    )

    assert result.data is None
    assert result.error is not None
    assert "not_found" in result.error


async def test_catalog_account_mismatch_is_an_explicit_error(
    mock_server: MockKingdeeServer,
) -> None:
    base = load_catalog()
    metrics = dict(base.metrics)
    metrics["revenue"] = replace(metrics["revenue"], accounts=("9999-9999",))
    catalog = replace(base, metrics=metrics)
    registry = await _registry(mock_server, catalog)
    ctx = _ctx(registry)

    result = await ctx.registry.invoke("finance_kpi_snapshot", {"period": "2026-10"}, ctx)

    assert result.data is None
    assert result.error is not None
    assert "mapping_error" in result.error
    assert "not mapped" in result.error


async def test_core_governance_registers_no_finance_tool() -> None:
    registry = ToolRegistry()
    assert not any(name.startswith("finance_") for name in registry.names())

    register(registry)

    assert {"finance_kpi_snapshot", "finance_receivables_aging"} <= set(registry.names())


async def test_composite_cannot_call_an_undeclared_vendor_tool(
    project_ctx: ToolContext,
) -> None:
    with pytest.raises(ToolDeniedError):
        await project_ctx.registry.invoke(
            "kingdee_query_partners", {"partner_type": "BD_Customer"}, project_ctx
        )


async def test_nested_vendor_call_is_audited_under_the_composite(
    finance_registry: ToolRegistry,
) -> None:
    rows: list[dict[str, Any]] = []

    async def sink(row: dict[str, Any]) -> None:
        rows.append(row)

    ctx = _ctx(finance_registry, audit=sink)
    result = await ctx.registry.invoke("finance_kpi_snapshot", {"period": "2026-10"}, ctx)

    assert result.error is None
    assert [row["tool"] for row in rows] == ["kingdee_query_report"]
    assert rows[0]["parent_call_id"] == ctx.call_id
    assert rows[0]["call_id"] != ctx.call_id
