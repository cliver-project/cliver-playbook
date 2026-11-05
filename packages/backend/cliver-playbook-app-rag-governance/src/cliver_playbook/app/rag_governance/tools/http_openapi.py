"""A read-only HTTP tool for an OpenAPI-shaped (or plain JSON) endpoint.

The tool is configured, not coded per vendor: the project's tool
profile supplies the base URL, path, method, result key and argument
model. The model supplies only typed arguments; it never supplies the
URL, a query string, or a SQL fragment. That is the line that keeps a
prompt-injection from turning into a vendor-query injection.

The ``httpx.AsyncClient`` is injectable so unit tests use
``httpx.MockTransport`` and the Kingdee contract tests can reuse one
client. A request failure is returned as a ``ToolResult`` with
``error`` set — the facade must narrate "live data unavailable"
rather than silently substituting stale data.
"""

from __future__ import annotations

from typing import Any, Literal

import httpx
from pydantic import BaseModel, ConfigDict, ValidationError

from cliver_playbook.app.rag_governance.tools.base import (
    ToolContext,
    ToolResult,
    ToolSpec,
)


class _OpenArgs(BaseModel):
    """The permissive default: any argument shape is passed through.

    Pydantic's ``BaseModel`` itself cannot be instantiated, so the
    default is a concrete subclass. Production tool profiles should
    always supply a strict model.
    """

    model_config = ConfigDict(extra="allow")


class HttpOpenApiTool:
    """Invoke one HTTP endpoint and normalize its JSON rows.

    Args:
        spec: Declarative tool metadata; its ``result_cap`` bounds rows.
        base_url: Scheme + host (+ optional prefix) of the vendor API.
        path: Endpoint path, joined to ``base_url``.
        method: ``GET`` sends validated args as query parameters;
            ``POST`` sends them as a JSON body.
        args_model: Pydantic model validating the model-supplied args.
            The base model accepts everything, so production profiles
            should supply a strict model.
        result_key: When the response is an object, the key holding the
            row list. Omit when the response is already a list.
        client: Optional shared ``httpx.AsyncClient`` (tests, pooling).
    """

    def __init__(
        self,
        spec: ToolSpec,
        *,
        base_url: str,
        path: str,
        method: Literal["GET", "POST"] = "GET",
        args_model: type[BaseModel] = _OpenArgs,
        result_key: str | None = None,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        if not spec.read_only:
            raise ValueError(f"HttpOpenApiTool refuses write tool {spec.name!r}")
        self.spec = spec
        self._base_url = base_url.rstrip("/")
        self._path = "/" + path.lstrip("/")
        self._method = method.upper()
        self._args_model = args_model
        self._result_key = result_key
        self._client = client

    @property
    def url(self) -> str:
        return f"{self._base_url}{self._path}"

    async def invoke(self, args: dict[str, Any], ctx: ToolContext) -> ToolResult:
        try:
            validated = self._args_model.model_validate(args)
        except ValidationError as exc:
            # Invalid typed arguments are a planner error, not an outage.
            # Returning an error result lets the agent correct itself.
            return ToolResult(
                tool=self.spec.name,
                data=None,
                as_of=ctx.as_of,
                row_count=0,
                error=f"invalid_args: {exc.error_count()} validation error(s)",
            )

        payload = validated.model_dump(exclude_none=True)
        try:
            response = await self._request(payload, ctx)
            response.raise_for_status()
        except httpx.HTTPError as exc:
            return ToolResult(
                tool=self.spec.name,
                data=None,
                as_of=ctx.as_of,
                row_count=0,
                error=f"http_error: {type(exc).__name__}",
            )

        try:
            body = response.json()
        except ValueError:
            return ToolResult(
                tool=self.spec.name,
                data=None,
                as_of=ctx.as_of,
                row_count=0,
                error="invalid_json",
            )

        rows = self._extract_rows(body)
        if not isinstance(rows, list):
            row_count = 0 if rows is None else 1
            return ToolResult(
                tool=self.spec.name,
                data=rows,
                as_of=ctx.as_of,
                row_count=row_count,
            )

        cap = min(self.spec.result_cap, ctx.caps.max_rows)
        truncated = len(rows) > cap
        data = rows[:cap]
        return ToolResult(
            tool=self.spec.name,
            data=data,
            as_of=ctx.as_of,
            row_count=len(data),
            truncated=truncated,
        )

    async def _request(self, payload: dict[str, Any], ctx: ToolContext) -> httpx.Response:
        if self._client is not None:
            return await self._client.request(
                self._method,
                self.url,
                params=payload if self._method == "GET" else None,
                json=payload if self._method == "POST" else None,
            )
        async with httpx.AsyncClient(timeout=ctx.caps.timeout_seconds) as client:
            return await client.request(
                self._method,
                self.url,
                params=payload if self._method == "GET" else None,
                json=payload if self._method == "POST" else None,
            )

    def _extract_rows(self, body: Any) -> Any:
        if self._result_key is None:
            return body
        if isinstance(body, dict):
            return body.get(self._result_key)
        return None
