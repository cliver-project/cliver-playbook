"""``python -m cliver_playbook.app.mcp`` entry: run the MCP server as a standalone process.

Used by the ``mcp-stdio`` and ``mcp-http`` Makefile targets. The main
application always serves ``/mcp`` in-process; this entry exists for the
cases where you want a *separate* process — typically a local CLI agent that
pipes JSON-RPC over stdio, or a sidecar deployment on its own port.

Semantics of both transports, the stdio auth policy (fail fast on a
missing/invalid ``MCP_BEARER_TOKEN`` when auth is enabled) and the
stdout-purity rule live in :mod:`cliver_playbook.app.mcp.transport` — this module is
argv parsing and dispatch only.
"""

from __future__ import annotations

import argparse
import asyncio
import sys


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m cliver_playbook.app.mcp",
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
        default=8100,
        help="HTTP port when --transport=http (default 8100).",
    )
    args = parser.parse_args(argv)

    if args.transport == "stdio":
        from cliver_playbook.app.mcp.transport import run_stdio

        # SystemExit raised by the bootstrap (fail-fast auth policy)
        # propagates: its message hits stderr and the exit code is 1,
        # exactly what a spawning agent should see.
        asyncio.run(run_stdio())
        return 0

    from cliver_playbook.app.mcp.transport import run_http

    run_http(host=args.host, port=args.port)
    return 0


if __name__ == "__main__":
    sys.exit(main())
