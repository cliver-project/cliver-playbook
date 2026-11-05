"""Deterministic period-keyed fixtures for the mock Kingdee MCP server.

The fixture directory is a snapshot of one ERP period, not a live
connection: ``<fixtures_dir>/<period>/period.json`` pins the period end
and therefore the ``as_of`` every tool reports. Nothing here reads the
host clock, so a query is reproducible on the next run and a snapshot
fallback can be labelled with the period it actually describes.

The curated tool names, argument schemas and result envelopes mirror
the pinned KingdeeMCP v0.2.0 read-only surface. Only names in
``ALLOWLISTED_TOOLS`` are ever offered; the mock has no write tool.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

CONTRACT_VERSION = "0.2.0"

# The curated, read-only subset the finance scenario needs. Order is
# part of the contract: tools/list is asserted against it.
ALLOWLISTED_TOOLS: tuple[str, ...] = (
    "kingdee_query_report",
    "kingdee_query_bills",
    "kingdee_query_receipts",
    "kingdee_query_partners",
    "kingdee_get_fields",
    "kingdee_list_forms",
)

# Any tool whose name starts with one of these prefixes mutates the ERP
# or uploads bytes. The outbound client refuses to start with one in its
# allowlist, regardless of what the server advertises.
WRITE_TOOL_PREFIXES: tuple[str, ...] = (
    "kingdee_save",
    "kingdee_submit",
    "kingdee_audit",
    "kingdee_unaudit",
    "kingdee_delete",
    "kingdee_push",
    "kingdee_close",
    "kingdee_workflow",
    "kingdee_create",
    "kingdee_upload",
)


def is_write_tool(name: str) -> bool:
    """A conservative name-based write check for the curated allowlist."""
    return name.startswith(WRITE_TOOL_PREFIXES)


TOOL_SPECS: tuple[dict[str, Any], ...] = (
    {
        "name": "kingdee_query_report",
        "description": (
            "Query a general-ledger or financial report through the Kingdee "
            "GetSysReportData endpoint (for example GL_RPT_AccountBalance or "
            "GL_AgingSchedule). The inner data object carries FieldKeys, Model "
            "filters, StartRow and Limit exactly as the upstream tool expects."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "form_id": {
                    "type": "string",
                    "description": "Report form id, e.g. GL_RPT_AccountBalance.",
                },
                "data": {
                    "type": "object",
                    "description": "Inner GetSysReportData model object.",
                    "additionalProperties": True,
                },
            },
            "required": ["form_id", "data"],
            "additionalProperties": False,
        },
    },
    {
        "name": "kingdee_query_bills",
        "description": "Query any Kingdee bill list (purchase orders, sale orders, stock bills).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "form_id": {"type": "string", "description": "Bill form id."},
                "filter_string": {"type": "string", "default": ""},
                "field_keys": {
                    "type": "string",
                    "default": "FID,FBillNo,FDate,FDocumentStatus",
                },
                "order_string": {"type": "string", "default": "FID DESC"},
                "start_row": {"type": "integer", "minimum": 0, "default": 0},
                "limit": {"type": "integer", "minimum": 1, "maximum": 100, "default": 20},
            },
            "required": ["form_id"],
            "additionalProperties": False,
        },
    },
    {
        "name": "kingdee_query_receipts",
        "description": "Query audited receivable receipts (AR_Receivable).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "filter_string": {"type": "string", "default": "FDocumentStatus='C'"},
                "field_keys": {"type": "string"},
                "start_row": {"type": "integer", "minimum": 0, "default": 0},
                "limit": {"type": "integer", "minimum": 1, "maximum": 100, "default": 20},
            },
            "additionalProperties": False,
        },
    },
    {
        "name": "kingdee_query_partners",
        "description": "Query customer or supplier master data.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "partner_type": {
                    "type": "string",
                    "enum": ["BD_Customer", "BD_Supplier"],
                },
                "filter_string": {"type": "string", "default": ""},
                "field_keys": {"type": "string"},
                "start_row": {"type": "integer", "minimum": 0, "default": 0},
                "limit": {"type": "integer", "minimum": 1, "maximum": 100, "default": 20},
            },
            "required": ["partner_type"],
            "additionalProperties": False,
        },
    },
    {
        "name": "kingdee_get_fields",
        "description": "List the fields of a Kingdee form.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "form_id": {"type": "string"},
                "entry_key": {"type": "string", "default": ""},
                "verbose": {"type": "boolean", "default": False},
            },
            "required": ["form_id"],
            "additionalProperties": False,
        },
    },
    {
        "name": "kingdee_list_forms",
        "description": "Search the available Kingdee form ids.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "keyword": {"type": "string", "default": ""},
            },
            "additionalProperties": False,
        },
    },
)


def allowlisted_names() -> tuple[str, ...]:
    """The curated tool names, in contract order."""
    return ALLOWLISTED_TOOLS


@dataclass(frozen=True)
class PeriodFixture:
    """One closed ERP period and its fixture directory."""

    period: str
    period_end: datetime
    directory: Path
    closed: bool = True
    currency: str = "CNY"


def available_periods(fixtures_dir: Path) -> list[str]:
    """Period directories that carry a ``period.json``, sorted."""
    if not fixtures_dir.is_dir():
        return []
    return sorted(
        child.name for child in fixtures_dir.iterdir() if (child / "period.json").is_file()
    )


def load_period(fixtures_dir: Path, period: str | None = None) -> PeriodFixture:
    """Load one period snapshot.

    ``period`` may be omitted only when the fixture root holds exactly
    one period. A missing period raises ``FileNotFoundError`` so callers
    can turn it into an explicit ``not_found`` envelope instead of
    silently substituting another period.
    """
    fixtures_dir = Path(fixtures_dir)
    if period is None:
        periods = available_periods(fixtures_dir)
        if len(periods) != 1:
            raise FileNotFoundError(
                f"expected exactly one period under {fixtures_dir}, found {periods!r}"
            )
        period = periods[0]
    directory = fixtures_dir / period
    path = directory / "period.json"
    if not path.is_file():
        raise FileNotFoundError(f"no fixture for period {period!r}")
    payload = json.loads(path.read_text(encoding="utf-8"))
    recorded = str(payload.get("period", period))
    if recorded != period:
        raise ValueError(f"period fixture {path} records {recorded!r}, expected {period!r}")
    period_end = datetime.fromisoformat(str(payload["period_end"]))
    if period_end.tzinfo is None:
        raise ValueError(f"period fixture {path} has a naive period_end")
    return PeriodFixture(
        period=period,
        period_end=period_end,
        directory=directory,
        closed=bool(payload.get("closed", True)),
        currency=str(payload.get("currency", "CNY")),
    )


def load_json(fixture: PeriodFixture, filename: str) -> Any:
    """Read a fixture file; a missing file is an explicit ``not_found``."""
    path = fixture.directory / filename
    if not path.is_file():
        raise FileNotFoundError(f"no fixture {path.name} for period {fixture.period!r}")
    return json.loads(path.read_text(encoding="utf-8"))


def load_rows(fixture: PeriodFixture, filename: str) -> list[dict[str, Any]]:
    """Read a list-of-rows fixture.

    A missing file is reported by the caller as ``not_found``; an empty
    list means the period genuinely has no rows (the upstream tool
    documents that zero rows is not an error).
    """
    payload = load_json(fixture, filename)
    if not isinstance(payload, list):
        raise TypeError(f"fixture {filename} must contain a JSON list of rows")
    return payload


# Report form id -> row fixture. A report outside this map is still
# served if a `report_<form_id>.json` file exists.
REPORT_FIXTURES: dict[str, str] = {
    "GL_RPT_AccountBalance": "gl_account_balance.json",
    "GL_AgingSchedule": "ar_aging_rows.json",
}


def report_filename(form_id: str) -> str:
    return REPORT_FIXTURES.get(form_id, f"report_{form_id}.json")


def bills_filename(form_id: str) -> str:
    return f"bills_{form_id}.json"


def fields_filename(form_id: str) -> str:
    return f"fields_{form_id}.json"
