"""``python -m app.mcp`` entry: run the MCP server as a standalone process.

Used by the ``mcp-stdio`` and ``mcp-http`` Makefile targets. The parent
``main.py`` always runs the MCP subapp in-process (lifespan-composed);
this entry exists for the cases where you want a *separate* process
— typically a local CLI agent that pipes JSON-RPC over stdio, or a
sidecar deployment where the MCP server is on its own port and
process boundary from the Web.

Transports
----------

``--transport stdio`` is the standard MCP stdio transport: the server
reads JSON-RPC frames from stdin and writes them to stdout. The agent
spawns this process and uses the pipes directly. Auth in stdio mode
is taken from environment variables (``MCP_BEARER_TOKEN`` /
``MCP_AGENT_TYPE`` / ``MCP_AGENT_ID``) — the same values the HTTP
gate would read from headers, so the rest of the wiring is identical.

``--transport http`` runs the same ``streamable_http_app`` on its
own port (default :8000, override with ``--port``). Useful when the
Web backend and the MCP server run on different hosts / ports but
share a database — the same composition ai-gov's ``mcp_server``
process uses.

Both transports are filled in by M6 (the dispatch lives in
:mod:`app.mcp.transport`). For now (M0), this entry exists so that
``python -m app.mcp`` does not raise
``No module named app.mcp.__main__``; the M0 placeholder exits with a
clear message and the right exit code.
"""

from __future__ import annotations

import argparse
import sys


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m app.mcp",
        description=(
            "Run the MCP server as a standalone process. The parent "
            "uvicorn process also serves /mcp; use this entry only when "
            "you want a separate process (stdio, sidecar, etc.)."
        ),
    )
    parser.add_argument(
        "--transport",
        choices=("stdio", "http"),
        default="stdio",
        help="Wire transport: stdio (default) or http (separate port).",
    )
    parser.add_argument(
        "--host",
        default="127.0.0.1",
        help="HTTP host when --transport=http (default 127.0.0.1).",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=8000,
        help="HTTP port when --transport=http (default 8000).",
    )
    args = parser.parse_args(argv)

    # M0 placeholder: M6 fills this in with the actual serve_stdio() /
    # serve_http() dispatch. Until then, surface a clear message rather
    # than crashing later inside the SDK with a less obvious error.
    print(
        f"MCP standalone transport '{args.transport}' is not yet wired "
        "(Phase 3 step M6). For now use the in-process subapp at "
        "settings.mcp.mount_path (default /mcp) on the parent uvicorn.",
        file=sys.stderr,
    )
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
