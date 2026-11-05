"""Tool contract, registry, restricted invocation and the HTTP adapter.

The tests pin the three defense layers separately: registration rejects
a write tool, the invoker refuses anything outside the declared
allowlist, and a composite cannot call another composite. Masking is
asserted to run once on the composite's normalized result, not on each
child.
"""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

import httpx
import pytest
from pydantic import BaseModel, ConfigDict

from cliver_playbook.app.rag_governance.tools import (
    HttpOpenApiTool,
    RestrictedToolInvoker,
    ToolCaps,
    ToolContext,
    ToolDeniedError,
    ToolRegistry,
    ToolResult,
    ToolSpec,
)

AS_OF = datetime(2026, 11, 1, tzinfo=ZoneInfo("Asia/Shanghai"))


class FakeTool:
    def __init__(
        self,
        name: str,
        *,
        read_only: bool = True,
        dependencies: tuple[str, ...] = (),
        data: object | None = None,
    ) -> None:
        self.spec = ToolSpec(
            name=name,
            description=f"fake {name}",
            read_only=read_only,
            dependencies=dependencies,
            result_cap=100,
        )
        self._data = data if data is not None else [{"name": name}]

    async def invoke(self, args: dict, ctx: ToolContext) -> ToolResult:
        rows = self._data if isinstance(self._data, list) else [self._data]
        return ToolResult(
            tool=self.spec.name,
            data=self._data,
            as_of=ctx.as_of,
            row_count=len(rows),
        )


class CompositeTool:
    spec = ToolSpec(
        name="composite",
        description="two vendors",
        dependencies=("vendor_a", "vendor_b"),
        result_cap=100,
    )

    async def invoke(self, args: dict, ctx: ToolContext) -> ToolResult:
        a = await ctx.registry.invoke("vendor_a", {}, ctx)
        b = await ctx.registry.invoke("vendor_b", {}, ctx)
        return ToolResult(
            tool=self.spec.name,
            data=[*a.data, *b.data],
            as_of=ctx.as_of,
            row_count=a.row_count + b.row_count,
        )


class FakeAudit:
    def __init__(self) -> None:
        self.rows: list[dict] = []

    async def __call__(self, row: dict) -> None:
        self.rows.append(row)


def make_ctx(**overrides) -> ToolContext:
    ctx = ToolContext(
        viewer=None,
        access=None,
        project_id="finance-kpi",
        as_of=AS_OF,
        masking=None,
        caps=ToolCaps(max_rows=1000),
        registry=None,
        call_id="call-1",
    )
    return ctx._replace(**overrides)


async def test_registry_rejects_write_tools() -> None:
    with pytest.raises(ValueError, match="write tool"):
        ToolRegistry().register(FakeTool("writer", read_only=False))


async def test_restricted_invoker_refuses_undeclared_dependency() -> None:
    registry = ToolRegistry()
    registry.register(FakeTool("vendor_a"))
    registry.register(FakeTool("vendor_b"))
    invoker = RestrictedToolInvoker(registry, allowed=frozenset({"vendor_a"}), audit=None)
    with pytest.raises(ToolDeniedError):
        await invoker.invoke("vendor_b", {}, make_ctx())


async def test_restricted_invoker_rechecks_read_only() -> None:
    registry = ToolRegistry(allow_write=True)
    registry.register(FakeTool("writer", read_only=False))
    invoker = RestrictedToolInvoker(registry, allowed=frozenset({"writer"}), audit=None)
    with pytest.raises(ToolDeniedError, match="not read-only"):
        await invoker.invoke("writer", {}, make_ctx())


async def test_composite_nested_call_is_audited_under_parent() -> None:
    audit = FakeAudit()
    registry = ToolRegistry()
    registry.register(CompositeTool())
    registry.register(FakeTool("vendor_a"))
    registry.register(FakeTool("vendor_b"))
    invoker = RestrictedToolInvoker(registry, allowed=frozenset({"composite"}), audit=audit)

    result = await invoker.invoke("composite", {}, make_ctx())

    assert result.row_count == 2
    assert [row["parent_call_id"] for row in audit.rows] == ["call-1", "call-1"]
    assert {row["tool"] for row in audit.rows} == {"vendor_a", "vendor_b"}
    assert all(row["call_id"] != "call-1" for row in audit.rows)


async def test_composite_cannot_recurse() -> None:
    registry = ToolRegistry()
    registry.register(CompositeTool())
    registry.register(FakeTool("vendor_a"))
    registry.register(FakeTool("vendor_b"))
    invoker = RestrictedToolInvoker(registry, allowed=frozenset({"composite"}), audit=None)
    with pytest.raises(ToolDeniedError, match="called from a tool"):
        await invoker.invoke("composite", {}, make_ctx(depth=1))


async def test_masking_runs_once_at_the_composite_boundary() -> None:
    seen: list[str] = []

    def masking(text: str) -> str:
        seen.append(text)
        return text.replace("13800138000", "[REDACTED]")

    registry = ToolRegistry()
    registry.register(CompositeTool())
    registry.register(FakeTool("vendor_a", data=[{"phone": "13800138000"}]))
    registry.register(FakeTool("vendor_b", data=[{"note": "safe"}]))

    result = await RestrictedToolInvoker(
        registry, allowed=frozenset({"composite"}), audit=None
    ).invoke("composite", {}, make_ctx(masking=masking))

    assert result.data == [{"phone": "[REDACTED]"}, {"note": "safe"}]
    # Two string leaves, each visited exactly once: child results were
    # not masked independently before the composite boundary.
    assert seen == ["13800138000", "safe"]


async def test_registry_validate_rejects_unregistered_dependency() -> None:
    registry = ToolRegistry()
    registry.register(CompositeTool())
    registry.register(FakeTool("vendor_a"))
    with pytest.raises(ValueError, match="unregistered"):
        registry.validate()

    registry.register(FakeTool("vendor_b"))
    registry.validate()


class KpiArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")
    period: str


async def test_http_tool_validates_args_and_caps_rows() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "GET"
        assert request.url.params["period"] == "2026-10"
        return httpx.Response(200, json={"rows": [{"n": i} for i in range(5)]})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    tool = HttpOpenApiTool(
        ToolSpec(name="kpi", description="KPI", result_cap=2),
        base_url="https://erp.test",
        path="/api/kpi",
        method="GET",
        args_model=KpiArgs,
        result_key="rows",
        client=client,
    )
    try:
        result = await tool.invoke({"period": "2026-10"}, make_ctx())
    finally:
        await client.aclose()

    assert result.row_count == 2
    assert result.truncated is True
    assert result.as_of == AS_OF


async def test_http_tool_returns_invalid_args_instead_of_calling_the_api() -> None:
    called = False

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal called
        called = True
        return httpx.Response(200, json=[])

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    tool = HttpOpenApiTool(
        ToolSpec(name="kpi", description="KPI"),
        base_url="https://erp.test",
        path="/api/kpi",
        args_model=KpiArgs,
        client=client,
    )
    try:
        result = await tool.invoke({"wrong": "shape"}, make_ctx())
    finally:
        await client.aclose()

    assert result.error is not None
    assert result.error.startswith("invalid_args")
    assert called is False


async def test_http_tool_reports_an_outage_as_an_error_result() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("boom", request=request)

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    tool = HttpOpenApiTool(
        ToolSpec(name="kpi", description="KPI"),
        base_url="https://erp.test",
        path="/api/kpi",
        client=client,
    )
    try:
        result = await tool.invoke({}, make_ctx())
    finally:
        await client.aclose()

    assert result.error is not None
    assert result.error.startswith("http_error")
    assert result.row_count == 0
