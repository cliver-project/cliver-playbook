"""A credential-free mock of the curated KingdeeMCP read-only contract.

The mock exists so the finance scenario can be exercised end to end
without a real ERP. It has three surfaces over the same deterministic
core:

- ``call_tool`` / ``list_tools`` for unit tests (the in-process path);
- ``in_process_transport()``, the object ``McpToolClient`` accepts when
  no HTTP hop is wanted;
- ``asgi_app`` and ``serve()``, a minimal JSON-RPC 2.0 MCP endpoint for
  the demo (default port 18080, deliberately off the usual 8080).

The server is pinned to a fixture period. It never reads the host clock,
and a request that names a period with no fixture returns ``not_found``
rather than borrowing another period's numbers.
"""

from __future__ import annotations

import argparse
import json
import logging
from pathlib import Path
from typing import Any

from cliver_playbook.app.rag_governance.testing.mock_kingdee.fixtures import (
    ALLOWLISTED_TOOLS,
    CONTRACT_VERSION,
    TOOL_SPECS,
    PeriodFixture,
    bills_filename,
    fields_filename,
    load_json,
    load_period,
    load_rows,
    report_filename,
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


class _InvalidArguments(ValueError):
    """The caller omitted a required tool argument."""


def _require(args: dict[str, Any], *names: str) -> None:
    missing = [name for name in names if args.get(name) in (None, "")]
    if missing:
        raise _InvalidArguments(f"missing required argument(s): {', '.join(missing)}")


def _row_count(data: Any) -> int:
    if isinstance(data, list):
        return len(data)
    return 0 if data is None else 1


def _envelope(
    tool: str,
    *,
    fixture: PeriodFixture | None,
    period: str | None,
    data: Any = None,
    error: str | None = None,
    error_message: str | None = None,
) -> dict[str, Any]:
    return {
        "tool": tool,
        "period": fixture.period if fixture is not None else period,
        "as_of": fixture.period_end.isoformat() if fixture is not None else None,
        "isError": error is not None,
        "error": error,
        "error_message": error_message,
        "data": [] if error is not None else data,
        "row_count": 0 if error is not None else _row_count(data),
    }


class InProcessTransport:
    """The transport seam ``McpToolClient`` uses without an HTTP hop."""

    def __init__(self, server: MockKingdeeServer) -> None:
        self._server = server

    async def list_tools(self) -> list[dict[str, Any]]:
        return await self._server.list_tools()

    async def call_tool(self, name: str, args: dict[str, Any]) -> dict[str, Any]:
        return await self._server.call_tool(name, args)


class MockKingdeeServer:
    """Deterministic, period-keyed implementation of the curated contract."""

    def __init__(self, fixtures_dir: Path | str, *, period: str | None = None) -> None:
        self._fixtures_dir = Path(fixtures_dir)
        self._period = period
        # Fail at construction when a pinned period is invalid; a lazy
        # period is resolved on first use so a directory may hold more
        # than one period.
        if period is not None:
            load_period(self._fixtures_dir, period)

    async def list_tools(self) -> list[dict[str, Any]]:
        """The curated ``tools/list`` result, in contract order."""
        return [dict(spec) for spec in TOOL_SPECS]

    async def call_tool(self, name: str, args: dict[str, Any] | None = None) -> dict[str, Any]:
        """Call one read-only tool and return the normalized envelope.

        ``period`` is a mock-only selector accepted alongside the real
        arguments: the upstream tools do not take it, so a production
        binding omits it and the server uses its pinned period. It is
        how tests ask for a different snapshot without mutating the
        server.
        """
        payload = dict(args or {})
        requested_period = payload.pop("period", None)
        period = requested_period or self._period

        if name not in ALLOWLISTED_TOOLS:
            return _envelope(
                name,
                fixture=None,
                period=period,
                error="unknown_tool",
                error_message=f"{name!r} is not in the curated read-only contract",
            )

        try:
            fixture = load_period(self._fixtures_dir, period)
        except (FileNotFoundError, ValueError) as exc:
            return _envelope(
                name,
                fixture=None,
                period=period,
                error="not_found",
                error_message=str(exc),
            )

        try:
            data = self._dispatch(name, payload, fixture)
        except _InvalidArguments as exc:
            return _envelope(
                name,
                fixture=fixture,
                period=fixture.period,
                error="invalid_arguments",
                error_message=str(exc),
            )
        except FileNotFoundError as exc:
            return _envelope(
                name,
                fixture=fixture,
                period=fixture.period,
                error="not_found",
                error_message=str(exc),
            )
        except (TypeError, ValueError) as exc:
            return _envelope(
                name,
                fixture=fixture,
                period=fixture.period,
                error="invalid_fixture",
                error_message=str(exc),
            )
        return _envelope(name, fixture=fixture, period=fixture.period, data=data)

    def _dispatch(self, name: str, args: dict[str, Any], fixture: PeriodFixture) -> Any:
        if name == "kingdee_query_report":
            return self._query_report(args, fixture)
        if name == "kingdee_query_bills":
            return self._query_bills(args, fixture)
        if name == "kingdee_query_receipts":
            return self._page(
                load_rows(fixture, "receipts.json"),
                args.get("start_row", 0),
                args.get("limit", 20),
            )
        if name == "kingdee_query_partners":
            _require(args, "partner_type")
            partner_type = str(args["partner_type"])
            if partner_type not in {"BD_Customer", "BD_Supplier"}:
                raise _InvalidArguments(f"unsupported partner_type {partner_type!r}")
            return self._page(
                load_rows(fixture, f"partners_{partner_type}.json"),
                args.get("start_row", 0),
                args.get("limit", 20),
            )
        if name == "kingdee_get_fields":
            _require(args, "form_id")
            return load_json(fixture, fields_filename(str(args["form_id"])))
        if name == "kingdee_list_forms":
            keyword = str(args.get("keyword", "")).lower()
            forms = load_rows(fixture, "forms.json")
            if not keyword:
                return forms
            return [
                form for form in forms if keyword in json.dumps(form, ensure_ascii=False).lower()
            ]
        raise _InvalidArguments(f"no handler for {name!r}")

    def _query_report(self, args: dict[str, Any], fixture: PeriodFixture) -> list[dict[str, Any]]:
        _require(args, "form_id", "data")
        inner = args["data"]
        if not isinstance(inner, dict):
            raise _InvalidArguments("data must be an object")
        self._assert_report_period(inner, fixture)
        rows = load_rows(fixture, report_filename(str(args["form_id"])))
        return self._page(rows, inner.get("StartRow", 0), inner.get("Limit", len(rows)))

    def _query_bills(self, args: dict[str, Any], fixture: PeriodFixture) -> list[dict[str, Any]]:
        _require(args, "form_id")
        rows = load_rows(fixture, bills_filename(str(args["form_id"])))
        return self._page(rows, args.get("start_row", 0), args.get("limit", 20))

    @staticmethod
    def _assert_report_period(inner: dict[str, Any], fixture: PeriodFixture) -> None:
        """Refuse a report request for a period the fixture does not cover."""
        model = inner.get("Model")
        if not isinstance(model, dict):
            return
        year = model.get("FENDYEAR")
        month = model.get("FENDPERIOD")
        if year is not None and int(year) != fixture.period_end.year:
            raise FileNotFoundError(f"report requests year {year}; fixture is {fixture.period}")
        if month is not None and int(month) != fixture.period_end.month:
            raise FileNotFoundError(f"report requests period {month}; fixture is {fixture.period}")

    @staticmethod
    def _page(rows: list[dict[str, Any]], start_row: Any, limit: Any) -> list[dict[str, Any]]:
        try:
            start = max(int(start_row), 0)
            size = max(min(int(limit), 100), 1)
        except (TypeError, ValueError) as exc:
            raise _InvalidArguments("start_row and limit must be integers") from exc
        return rows[start : start + size]

    # ---- MCP JSON-RPC surface -------------------------------------

    def in_process_transport(self) -> InProcessTransport:
        return InProcessTransport(self)

    async def asgi_app(self, scope: dict[str, Any], receive: Any, send: Any) -> None:
        """A small JSON-RPC 2.0 endpoint: initialize, tools/list, tools/call."""
        if scope["type"] == "lifespan":
            while True:
                message = await receive()
                if message["type"] == "lifespan.startup":
                    await send({"type": "lifespan.startup.complete"})
                elif message["type"] == "lifespan.shutdown":
                    await send({"type": "lifespan.shutdown.complete"})
                    return
            return
        if scope["type"] != "http":
            return

        body = await self._read_body(receive)
        try:
            request = json.loads(body) if body else {}
        except ValueError:
            await self._send_json(send, 400, self._rpc_error(None, -32700, "parse error"))
            return

        method = request.get("method")
        request_id = request.get("id")

        if method == "initialize":
            result: Any = {
                "protocolVersion": "2024-11-05",
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "mock-kingdee", "version": CONTRACT_VERSION},
            }
        elif method == "ping":
            result = {}
        elif method == "tools/list":
            result = {"tools": await self.list_tools()}
        elif method == "tools/call":
            params = request.get("params") or {}
            envelope = await self.call_tool(params.get("name", ""), params.get("arguments") or {})
            result = {
                "content": [{"type": "text", "text": json.dumps(envelope, ensure_ascii=False)}],
                "structuredContent": envelope,
                # Match the upstream server: a business error is a
                # successful MCP call carrying an error payload.
                "isError": False,
            }
        elif method in {"notifications/initialized", "notifications/cancelled"}:
            await send({"type": "http.response.start", "status": 202, "headers": []})
            await send({"type": "http.response.body", "body": b""})
            return
        else:
            await self._send_json(
                send, 200, self._rpc_error(request_id, -32601, "method not found")
            )
            return

        await self._send_json(send, 200, {"jsonrpc": "2.0", "id": request_id, "result": result})

    @staticmethod
    async def _read_body(receive: Any) -> bytes:
        chunks: list[bytes] = []
        while True:
            message = await receive()
            if message["type"] != "http.request":
                break
            chunks.append(message.get("body", b""))
            if not message.get("more_body", False):
                break
        return b"".join(chunks)

    @staticmethod
    async def _send_json(send: Any, status: int, payload: dict[str, Any]) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        await send(
            {
                "type": "http.response.start",
                "status": status,
                "headers": [
                    (b"content-type", b"application/json"),
                    (b"content-length", str(len(body)).encode("ascii")),
                ],
            }
        )
        await send({"type": "http.response.body", "body": body})

    @staticmethod
    def _rpc_error(request_id: Any, code: int, message: str) -> dict[str, Any]:
        return {
            "jsonrpc": "2.0",
            "id": request_id,
            "error": {"code": code, "message": message},
        }

    def serve(self, *, host: str = "127.0.0.1", port: int = 18080) -> None:
        """Serve the mock over streamable HTTP (uvicorn, lazily imported)."""
        import uvicorn

        uvicorn.run(self.asgi_app, host=host, port=port, log_level="info")


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Mock Kingdee MCP read-only server")
    parser.add_argument("--fixtures", required=True, type=Path)
    parser.add_argument("--period", default=None)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument(
        "--port",
        default=18080,
        type=int,
        help="Default 18080 is already offset from the usual 8080.",
    )
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO)
    MockKingdeeServer(args.fixtures, period=args.period).serve(host=args.host, port=args.port)


if __name__ == "__main__":
    main()
