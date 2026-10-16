"""Application settings for the ``mcp`` package — the agent-facing surface.

Extends ``user.Settings`` (identity, OIDC registry, OAuth 2.1 provider) with
the single ``mcp`` block: the auth gate flag, the concurrency cap and the
agent self-identification rules. The full layered resolution documented in
``basic.settings`` applies unchanged — ``mcp`` keys in ``app.yaml``, env
overrides spelled ``CLIVER_MCP__<FIELD>``, field defaults last — and a
composed application's ``create_app`` binds this most-derived instance to the
process runtime, which every package's ``settings`` proxy then serves
(ADR-0016).

There is deliberately NO ``mount_path`` / ``transport`` field: the protocol
endpoint lives at the fixed path ``/mcp`` (``api.streamable.MCP_PATH``). The
path is not a deployment knob because the OAuth 2.1 provider's protected-
resource metadata already publishes ``{base}/mcp`` as the resource identifier
— a configurable path would let the endpoint and the metadata it must satisfy
disagree (ADR-0017). Adjusting it is a source edit in a project that vendors
this package, not a config change.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from cliver_playbook.app.basic.runtime import lazy_settings
from cliver_playbook.app.user.settings import Settings as UserSettings


class McpSettings(BaseModel):
    """MCP server block (see ``app.yaml``'s ``mcp:`` section for the narrative)."""

    # Auth gate flag. Default OFF: local development / trusted networks.
    # ON = every request must carry a bearer token from the shared
    # auth_tokens table (same issuance/revocation path as the Web's).
    # OFF is not "everyone is an admin": calls run under an anonymous
    # viewer, so @public_tool tools answer and @require_perm tools are
    # denied — auth off never silently grants permissions.
    auth_enabled: bool = False

    # Process-wide cap on concurrently executing MCP tool calls (a
    # semaphore in mcp/toolkit.py). Queueing, not rejection; values
    # below 1 are clamped to 1 at use.
    max_concurrent_calls: int = 16

    # Agent self-identification: values outside the whitelist normalise to
    # "unknown" in audit rows. Empty list = accept any string (dev default).
    # "web-playground" is the Web UI's test console — it declares a distinct
    # type so its calls are never mistaken for an anonymous client that did
    # not identify itself.
    agent_type_whitelist: list[str] = Field(
        default_factory=lambda: [
            "claude-code",
            "workbuddy",
            "codex",
            "mcp-cli",
            "web-playground",
            "unknown",
        ]
    )

    # Agent ids are stored verbatim up to this length, truncated beyond.
    agent_id_max_length: int = 128

    # No OAuth block here on purpose: the MCP surface reuses the Web's
    # OAuth 2.1 provider (top-level `oauth21_*` settings), whose
    # protected-resource metadata already names `{base}/mcp` as the
    # resource. A second knob set would let the two copies disagree.


class Settings(UserSettings):
    """Identity settings plus the ``mcp`` block."""

    mcp: McpSettings = Field(default_factory=McpSettings)


# Process-aware lazy proxy (see basic.runtime.lazy_settings): resolves to the
# runtime-bound instance — this class, or any composed application's Settings —
# or to a lazily built Settings() of this class when unconfigured.
settings = lazy_settings(Settings)


def get_settings() -> Settings:
    """Return the process-wide Settings instance (see ``settings`` above)."""
    return settings.resolve()
