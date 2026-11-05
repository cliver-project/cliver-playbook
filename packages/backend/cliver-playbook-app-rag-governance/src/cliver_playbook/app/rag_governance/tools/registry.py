"""Tool registry and the restricted invoker composites call through.

The registry is the allowlist boundary at registration time: a write
tool cannot enter unless a test explicitly opts in. The invoker is the
boundary at call time: only names the composite declared are callable,
composite-to-composite recursion is refused, and every child call is
audited under the composite's call id.

Masking runs once, at the top-level (composite) boundary, on the
normalized result. Child results are raw: masking them individually
would double-mask values and make the report counts meaningless.

The invoker never reads the host clock. The result's ``as_of`` is the
injected reference time, and the audit row records it unchanged.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from datetime import UTC
from typing import Any
from uuid import uuid4

from cliver_playbook.app.rag_governance.tools.base import (
    AuditSink,
    Tool,
    ToolCaps,
    ToolContext,
    ToolDeniedError,
    ToolResult,
    ToolSpec,
)


class ToolRegistry:
    """Implementations keyed by ``spec.name``.

    ``allow_write`` exists only so a test can construct a write tool and
    prove the invoker rejects it. Production code never passes it.
    """

    def __init__(self, *, allow_write: bool = False) -> None:
        self._allow_write = allow_write
        self._tools: dict[str, Tool] = {}

    def register(self, tool: Tool) -> None:
        name = tool.spec.name
        if name in self._tools:
            raise ValueError(f"duplicate tool registration: {name!r}")
        if not tool.spec.read_only and not self._allow_write:
            raise ValueError(f"read-only governance refuses write tool: {name!r}")
        self._tools[name] = tool

    def get(self, name: str) -> Tool:
        try:
            return self._tools[name]
        except KeyError:
            known = ", ".join(sorted(self._tools)) or "(none)"
            raise KeyError(f"unknown tool: {name!r}; known: {known}") from None

    def names(self) -> list[str]:
        return sorted(self._tools)

    def specs(self) -> list[ToolSpec]:
        return [self._tools[name].spec for name in self.names()]

    def validate(self) -> None:
        """Check every declared dependency resolves to a read-only tool.

        Registration order must not matter (a composite may be declared
        before its vendor tools), so this runs after the project's tool
        profile is fully loaded. The invoker repeats the read-only check
        at call time.
        """
        for tool in self._tools.values():
            for dependency in tool.spec.dependencies:
                if dependency == tool.spec.name:
                    raise ValueError(f"tool {tool.spec.name!r} depends on itself")
                try:
                    child = self.get(dependency)
                except KeyError:
                    raise ValueError(
                        f"tool {tool.spec.name!r} depends on unregistered tool {dependency!r}"
                    ) from None
                if not child.spec.read_only:
                    raise ValueError(
                        f"tool {tool.spec.name!r} depends on non-read-only tool {dependency!r}"
                    )


def fingerprint_args(args: dict[str, Any]) -> str:
    """A stable short fingerprint for audit; the raw args are not logged."""
    payload = json.dumps(args, sort_keys=True, default=str, separators=(",", ":"))
    return hashlib.sha256(payload.encode()).hexdigest()[:16]


def _mask_tree(value: Any, masking: Any) -> Any:
    """Apply the masking callable to every string in a result tree.

    A masking policy can be a text function, so it must be applied to
    strings, not to the container. Lists and dicts are copied; scalar
    non-strings pass through unchanged.
    """
    if isinstance(value, str):
        return masking(value)
    if isinstance(value, list):
        return [_mask_tree(item, masking) for item in value]
    if isinstance(value, tuple):
        return tuple(_mask_tree(item, masking) for item in value)
    if isinstance(value, dict):
        return {key: _mask_tree(item, masking) for key, item in value.items()}
    return value


class RestrictedToolInvoker:
    """The only handle a tool gets for making nested tool calls.

    ``allowed`` is the set of names this invocation may call: the
    project's authorized tool set at the top level, or a composite's
    declared dependencies for a nested handle. ``_depth`` distinguishes
    the two. A nested handle audits every child call; the top-level
    handle leaves the top call's audit to the query facade, which knows
    the caller's intent and the rule version.
    """

    def __init__(
        self,
        registry: ToolRegistry,
        allowed: frozenset[str],
        audit: AuditSink | None,
        depth: int = 0,
    ) -> None:
        self._registry = registry
        self._allowed = allowed
        self._audit = audit
        self._depth = depth

    async def invoke(self, name: str, args: dict[str, Any], ctx: ToolContext) -> ToolResult:
        if name not in self._allowed:
            raise ToolDeniedError(f"tool {name!r} is not allowed for this call")

        try:
            tool = self._registry.get(name)
        except KeyError as exc:
            raise ToolDeniedError(str(exc)) from None
        spec = tool.spec

        if not spec.read_only:
            raise ToolDeniedError(f"tool {name!r} is not read-only")
        # A composite may call plain tools only. Refusing a composite at
        # any nested depth also makes unbounded recursion impossible.
        if spec.dependencies and ctx.depth > 0:
            raise ToolDeniedError(f"composite tool {name!r} cannot be called from a tool")

        child_registry = RestrictedToolInvoker(
            self._registry,
            allowed=frozenset(spec.dependencies),
            audit=self._audit,
            depth=self._depth + 1,
        )
        tool_ctx = ctx._replace(registry=child_registry, depth=ctx.depth + 1)

        call_id = ctx.call_id if self._depth == 0 else f"tool-{uuid4()}"
        parent_call_id = ctx.call_id if self._depth > 0 else ctx.parent_call_id

        try:
            result = await tool.invoke(args, tool_ctx)
        except Exception as exc:
            await self._record(
                name=name,
                call_id=call_id,
                parent_call_id=parent_call_id,
                ctx=ctx,
                args=args,
                row_count=0,
                error=str(exc),
            )
            raise

        result = self._cap(spec, ctx.caps, result)
        # Masking is applied once, at the top-level boundary, to the
        # normalized result of the whole call tree.
        if self._depth == 0 and ctx.masking is not None and result.error is None:
            result = replace(result, data=_mask_tree(result.data, ctx.masking))

        await self._record(
            name=name,
            call_id=call_id,
            parent_call_id=parent_call_id,
            ctx=ctx,
            args=args,
            row_count=result.row_count,
            error=result.error,
        )
        return result

    def _cap(self, spec: ToolSpec, caps: ToolCaps, result: ToolResult) -> ToolResult:
        cap = min(spec.result_cap, caps.max_rows)
        if isinstance(result.data, list) and len(result.data) > cap:
            return replace(
                result,
                data=result.data[:cap],
                row_count=cap,
                truncated=True,
            )
        return result

    async def _record(
        self,
        *,
        name: str,
        call_id: str,
        parent_call_id: str | None,
        ctx: ToolContext,
        args: dict[str, Any],
        row_count: int,
        error: str | None,
    ) -> None:
        # The top-level call is audited by the facade; only nested calls
        # are the invoker's responsibility, which also keeps the fake
        # audit in unit tests to exactly the child-call rows.
        if self._depth == 0 or self._audit is None:
            return
        await self._audit(
            {
                "tool": name,
                "call_id": call_id,
                "parent_call_id": parent_call_id,
                "project_id": ctx.project_id,
                "row_count": row_count,
                "as_of": ctx.as_of.astimezone(UTC).isoformat(),
                "args_fingerprint": fingerprint_args(args),
                "error": error,
            }
        )
