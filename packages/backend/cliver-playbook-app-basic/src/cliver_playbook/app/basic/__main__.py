"""Standalone entry point: ``python -m cliver_playbook.app.basic``.

Runs the package's self-application with uvicorn. The factory string (rather
than an app instance) keeps ``--reload`` working, which requires uvicorn to
re-import the application in a subprocess — import safety is what makes that
cheap.
"""

from __future__ import annotations

import argparse

import uvicorn

_FACTORY = "cliver_playbook.app.basic.app:create_app"


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the basic package's application.")
    parser.add_argument("--host", default="127.0.0.1", help="Bind address (default: 127.0.0.1).")
    parser.add_argument("--port", type=int, default=8000, help="Bind port (default: 8000).")
    parser.add_argument(
        "--reload",
        action="store_true",
        help="Restart on source changes (development only).",
    )
    args = parser.parse_args()

    uvicorn.run(_FACTORY, factory=True, host=args.host, port=args.port, reload=args.reload)


if __name__ == "__main__":
    main()
