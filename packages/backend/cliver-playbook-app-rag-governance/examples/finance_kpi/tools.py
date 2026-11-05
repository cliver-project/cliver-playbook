"""Finance composite tools built on the curated Kingdee read-only contract.

The composites are scenario code, not core governance. They run in the
same restricted-invoker path as any other tool: a composite declares the
vendor tool it needs, receives a child invoker that can call only that
dependency, and returns a normalized ``ToolResult``. The model never sees
the low-level rows and never computes a ratio.

Period semantics are explicit. ``period`` is either ``YYYY-MM`` or the
symbolic ``latest_closed``; the latter resolves against the injected
``ToolContext.as_of``, never the host clock. A period outside the
fixture set is an error, never a silent substitution.
"""

from __future__ import annotations

import calendar
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from pathlib import Path
from typing import Any

import yaml

from cliver_playbook.app.rag_governance.tools.base import (
    ToolContext,
    ToolResult,
    ToolSpec,
)
from cliver_playbook.app.rag_governance.tools.registry import ToolRegistry

CATALOG_PATH = Path(__file__).with_name("metric_catalog.yaml")

_PERIOD = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")
_ACCOUNT_RANGE = re.compile(r"^(\d+)-(\d+)$")
_RATIO_PLACES = Decimal("0.0001")
_REPORT_FIELD_KEYS = "account,metric,amount"
_AGING_BUCKETS: tuple[str, ...] = ("0-30", "31-60", "61-90", "90+")
_REQUIRED_METRICS: tuple[str, ...] = (
    "revenue",
    "budget_revenue",
    "cost_of_revenue",
    "net_profit",
    "receivables",
    "payables",
    "current_assets",
    "current_liabilities",
    "total_assets",
    "total_liabilities",
)

_PERIOD_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "period": {
            "type": "string",
            "default": "latest_closed",
            "pattern": r"^(latest_closed|\d{4}-(0[1-9]|1[0-2]))$",
            "description": (
                "Closed ERP period as YYYY-MM, or latest_closed to resolve "
                "against the request's injected as_of."
            ),
        }
    },
    "additionalProperties": False,
}


@dataclass(frozen=True)
class MetricRule:
    """One metric's display label and the accounts that feed it."""

    key: str
    label: str
    accounts: tuple[str, ...]


@dataclass(frozen=True)
class MetricCatalog:
    """The versioned account-range-to-metric mapping."""

    version: int
    currency: str
    warning_threshold: Decimal
    metrics: Mapping[str, MetricRule]


def latest_closed(as_of: datetime) -> str:
    """The latest month whose last calendar day is on or before ``as_of``.

    A period is treated as closed on its final calendar day, so the
    demo's pinned ``2026-10-31T23:59:59+08:00`` resolves to ``2026-10``
    while a question asked on 30 October still resolves to ``2026-09``.
    """
    if as_of.tzinfo is None:
        raise ValueError("as_of must be timezone-aware")
    year, month = as_of.year, as_of.month
    if as_of.day < calendar.monthrange(year, month)[1]:
        month -= 1
        if month == 0:
            year, month = year - 1, 12
    return f"{year:04d}-{month:02d}"


def load_catalog(path: Path | str | None = None) -> MetricCatalog:
    """Load and validate the scenario's metric catalog."""
    source = Path(path) if path is not None else CATALOG_PATH
    payload = yaml.safe_load(source.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise TypeError(f"metric catalog {source} must be a YAML object")

    metrics_payload = payload.get("metrics")
    if not isinstance(metrics_payload, dict) or not metrics_payload:
        raise ValueError(f"metric catalog {source} has no metrics")

    metrics: dict[str, MetricRule] = {}
    for key, raw in metrics_payload.items():
        if not isinstance(raw, dict):
            raise TypeError(f"metric {key!r} must be an object")
        accounts = raw.get("accounts")
        if (
            not isinstance(accounts, list)
            or not accounts
            or not all(isinstance(item, str) and item for item in accounts)
        ):
            raise ValueError(f"metric {key!r} must declare non-empty account ranges")
        metrics[str(key)] = MetricRule(
            key=str(key),
            label=str(raw.get("label") or key),
            accounts=tuple(accounts),
        )

    missing = sorted(set(_REQUIRED_METRICS) - set(metrics))
    if missing:
        raise ValueError(f"metric catalog is missing required metric(s): {', '.join(missing)}")

    threshold = _decimal(payload.get("warning_threshold"), "warning_threshold")
    if not Decimal(0) <= threshold <= Decimal(1):
        raise ValueError("warning_threshold must be between 0 and 1")
    version = payload.get("version", 1)
    if isinstance(version, bool) or not isinstance(version, int):
        raise TypeError("metric catalog version must be an integer")
    currency = str(payload.get("currency") or "CNY")
    return MetricCatalog(
        version=version,
        currency=currency,
        warning_threshold=threshold,
        metrics=metrics,
    )


def _decimal(value: Any, what: str) -> Decimal:
    if isinstance(value, bool) or value is None:
        raise ValueError(f"{what} must be a number")
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise ValueError(f"{what} is not a decimal: {value!r}") from exc
    if not parsed.is_finite():
        raise ValueError(f"{what} must be finite")
    return parsed


def _account_matches(account: str, pattern: str) -> bool:
    match = _ACCOUNT_RANGE.match(pattern)
    if match and account.isdigit():
        return int(match.group(1)) <= int(account) <= int(match.group(2))
    return account == pattern


def _rows_by_metric(
    rows: Sequence[Any],
    catalog: MetricCatalog,
) -> dict[str, list[Decimal]]:
    """Group report rows by metric, refusing any unmapped row."""
    grouped: dict[str, list[Decimal]] = {key: [] for key in catalog.metrics}
    for row in rows:
        if not isinstance(row, dict):
            raise TypeError("report row must be an object")
        metric = str(row.get("metric") or "")
        account = str(row.get("account") or "")
        rule = catalog.metrics.get(metric)
        if rule is None:
            raise ValueError(f"report metric {metric!r} is not in the catalog")
        if not any(_account_matches(account, pattern) for pattern in rule.accounts):
            raise ValueError(f"account {account!r} is not mapped to metric {metric!r}")
        grouped[metric].append(_decimal(row.get("amount"), f"amount for account {account!r}"))

    missing = [key for key in _REQUIRED_METRICS if not grouped.get(key)]
    if missing:
        raise ValueError("report has no rows for metric(s): " + ", ".join(missing))
    return grouped


def _totals(grouped: Mapping[str, list[Decimal]]) -> dict[str, Decimal]:
    return {key: sum(values, Decimal(0)) for key, values in grouped.items()}


def _ratio(numerator: Decimal, denominator: Decimal) -> Decimal:
    if denominator == 0:
        raise ValueError("cannot compute a ratio with a zero denominator")
    return (numerator / denominator).quantize(_RATIO_PLACES, rounding=ROUND_HALF_UP)


def _resolve_period(args: Mapping[str, Any], ctx: ToolContext) -> str:
    raw = args.get("period") or "latest_closed"
    if not isinstance(raw, str):
        raise TypeError("period must be a string")
    if raw == "latest_closed":
        return latest_closed(ctx.as_of)
    if not _PERIOD.match(raw):
        raise ValueError(f"period {raw!r} is not YYYY-MM or latest_closed")
    return raw


def _failure(
    tool: str,
    ctx: ToolContext,
    message: str,
    *,
    as_of: datetime | None = None,
) -> ToolResult:
    return ToolResult(
        tool=tool,
        data=None,
        as_of=as_of or ctx.as_of,
        row_count=0,
        error=message,
    )


async def _report(
    ctx: ToolContext,
    *,
    form_id: str,
    period: str,
) -> ToolResult:
    """Call the one declared vendor dependency through the restricted invoker."""
    if ctx.registry is None:
        return ToolResult(
            tool="kingdee_query_report",
            data=None,
            as_of=ctx.as_of,
            row_count=0,
            error="a composite requires a restricted tool invoker",
        )
    year, month = period.split("-")
    return await ctx.registry.invoke(
        "kingdee_query_report",
        {
            "form_id": form_id,
            "data": {
                "FieldKeys": _REPORT_FIELD_KEYS,
                "Model": {"FENDYEAR": int(year), "FENDPERIOD": int(month)},
                "StartRow": 0,
                "Limit": 1000,
            },
        },
        ctx,
    )


class FinanceKpiSnapshot:
    """One-screen operating metrics computed from account-balance rows."""

    spec = ToolSpec(
        name="finance_kpi_snapshot",
        description=(
            "Revenue, budget attainment, gross profit/margin, net profit, "
            "receivables, payables, working capital and debt ratio for one "
            "closed period, computed server-side from Kingdee report rows."
        ),
        input_schema=_PERIOD_SCHEMA,
        dependencies=("kingdee_query_report",),
        result_cap=20,
        max_staleness_seconds=86_400,
    )

    def __init__(self, catalog: MetricCatalog) -> None:
        self._catalog = catalog

    async def invoke(self, args: dict[str, Any], ctx: ToolContext) -> ToolResult:
        try:
            period = _resolve_period(args, ctx)
        except (TypeError, ValueError) as exc:
            return _failure(self.spec.name, ctx, f"invalid_period: {exc}")

        report = await _report(ctx, form_id="GL_RPT_AccountBalance", period=period)
        if report.error is not None:
            return _failure(
                self.spec.name,
                ctx,
                f"vendor report unavailable: {report.error}",
                as_of=report.as_of,
            )
        rows = report.data
        if not isinstance(rows, list):
            return _failure(self.spec.name, ctx, "vendor report returned no row list")
        try:
            data = self._payload(rows, period=period, as_of=report.as_of)
        except (TypeError, ValueError) as exc:
            return _failure(self.spec.name, ctx, f"mapping_error: {exc}")
        return ToolResult(
            tool=self.spec.name,
            data=data,
            as_of=report.as_of,
            row_count=len(rows),
        )

    def _payload(
        self,
        rows: Sequence[Any],
        *,
        period: str,
        as_of: datetime,
    ) -> dict[str, Any]:
        totals = _totals(_rows_by_metric(rows, self._catalog))
        revenue = totals["revenue"]
        cost_of_revenue = totals["cost_of_revenue"]
        gross_profit = revenue - cost_of_revenue
        current_assets = totals["current_assets"]
        current_liabilities = totals["current_liabilities"]
        total_assets = totals["total_assets"]
        total_liabilities = totals["total_liabilities"]

        return {
            "period": period,
            "as_of": as_of.isoformat(),
            "currency": self._catalog.currency,
            "revenue": revenue,
            "budget_revenue": totals["budget_revenue"],
            "budget_attainment": _ratio(revenue, totals["budget_revenue"]),
            "gross_profit": gross_profit,
            "gross_margin": _ratio(gross_profit, revenue),
            "net_profit": totals["net_profit"],
            "receivables": totals["receivables"],
            "payables": totals["payables"],
            "current_assets": current_assets,
            "current_liabilities": current_liabilities,
            "working_capital": current_assets - current_liabilities,
            "total_assets": total_assets,
            "total_liabilities": total_liabilities,
            "debt_ratio": _ratio(total_liabilities, total_assets),
        }


class FinanceReceivablesAging:
    """Receivables aging buckets and the 90+ warning."""

    spec = ToolSpec(
        name="finance_receivables_aging",
        description=(
            "Receivables aging buckets (0-30, 31-60, 61-90, 90+ days), the "
            "90+ share and whether it crosses the catalog's warning threshold."
        ),
        input_schema=_PERIOD_SCHEMA,
        dependencies=("kingdee_query_report",),
        result_cap=10,
        max_staleness_seconds=86_400,
    )

    def __init__(self, catalog: MetricCatalog) -> None:
        self._catalog = catalog

    async def invoke(self, args: dict[str, Any], ctx: ToolContext) -> ToolResult:
        try:
            period = _resolve_period(args, ctx)
        except (TypeError, ValueError) as exc:
            return _failure(self.spec.name, ctx, f"invalid_period: {exc}")

        report = await _report(ctx, form_id="GL_AgingSchedule", period=period)
        if report.error is not None:
            return _failure(
                self.spec.name,
                ctx,
                f"vendor report unavailable: {report.error}",
                as_of=report.as_of,
            )
        rows = report.data
        if not isinstance(rows, list):
            return _failure(self.spec.name, ctx, "vendor report returned no row list")
        try:
            data = self._payload(rows, period=period, as_of=report.as_of)
        except (TypeError, ValueError) as exc:
            return _failure(self.spec.name, ctx, f"mapping_error: {exc}")
        return ToolResult(
            tool=self.spec.name,
            data=data,
            as_of=report.as_of,
            row_count=len(rows),
        )

    def _payload(
        self,
        rows: Sequence[Any],
        *,
        period: str,
        as_of: datetime,
    ) -> dict[str, Any]:
        buckets = dict.fromkeys(_AGING_BUCKETS, Decimal(0))
        total = Decimal(0)
        for row in rows:
            if not isinstance(row, dict):
                raise TypeError("aging row must be an object")
            bucket = str(row.get("FAGINGBUCKET") or "")
            if bucket not in buckets:
                raise ValueError(f"unknown aging bucket {bucket!r}")
            amount = _decimal(row.get("FENDAMOUNTFOR"), f"aging amount for bucket {bucket!r}")
            buckets[bucket] += amount
            total += amount

        over_90d_ratio = _ratio(buckets["90+"], total) if total else Decimal(0)
        return {
            "period": period,
            "as_of": as_of.isoformat(),
            "currency": self._catalog.currency,
            "total": total,
            "buckets": buckets,
            "over_90d_ratio": over_90d_ratio,
            "warning_threshold": self._catalog.warning_threshold,
            "warning": over_90d_ratio >= self._catalog.warning_threshold,
        }


def register(registry: ToolRegistry, *, catalog: MetricCatalog | None = None) -> None:
    """Register the scenario composites; vendor tools must already be present."""
    resolved = catalog or load_catalog()
    registry.register(FinanceKpiSnapshot(resolved))
    registry.register(FinanceReceivablesAging(resolved))
