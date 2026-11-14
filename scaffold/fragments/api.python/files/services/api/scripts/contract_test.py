#!/usr/bin/env python3
"""Run Schemathesis against a live generated API on a scratch database.

Usage:
    cd services/api && uv run python scripts/contract_test.py

The script creates a temporary database, applies every migration chain, starts
one uvicorn process, registers a user when auth is enabled, and runs the
composed OpenAPI contract. It fails on 5xx responses and schema-level server
errors; missing test data and 4xx responses are reported as warnings.
"""

from __future__ import annotations

import atexit
import logging
import os
import shutil
import socket
import subprocess
import sys
import time
import uuid
from pathlib import Path

import httpx
import psycopg

API_ROOT = Path(__file__).resolve().parents[1]
PROJECT_ROOT = API_ROOT.parents[1]
CONTRACT = PROJECT_ROOT / "contracts" / "openapi.yaml"
ADMIN_DSN = os.environ.get(
    "CLIVER_TEST_DATABASE_URL",
    "postgresql://cliver:cliver@127.0.0.1:5432/postgres",
)
TEST_DB = f"contract_{uuid.uuid4().hex[:10]}"
TEST_DSN = ADMIN_DSN.rsplit("/", 1)[0] + f"/{TEST_DB}"
logger = logging.getLogger(__name__)


def _admin_connection() -> psycopg.Connection:
    return psycopg.connect(ADMIN_DSN, autocommit=True)


def _create_database() -> None:
    with _admin_connection() as conn:
        conn.execute(f'DROP DATABASE IF EXISTS "{TEST_DB}" WITH (FORCE)')
        conn.execute(f'CREATE DATABASE "{TEST_DB}"')


def _drop_database() -> None:
    try:
        with _admin_connection() as conn:
            conn.execute(f'DROP DATABASE IF EXISTS "{TEST_DB}" WITH (FORCE)')
    except psycopg.Error as exc:
        logger.warning("could not drop scratch database %s: %s", TEST_DB, exc)


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _wait_healthy(base_url: str, process: subprocess.Popen) -> None:
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise SystemExit("API process exited before becoming healthy")
        try:
            response = httpx.get(f"{base_url}/api/v1/health", timeout=1)
            if response.status_code == 200:
                return
        except httpx.HTTPError:
            pass
        time.sleep(0.2)
    raise SystemExit("API did not become healthy within 30 seconds")


def _auth_headers(base_url: str) -> dict[str, str]:
    username = f"contract_{uuid.uuid4().hex[:10]}"
    with httpx.Client(base_url=base_url, timeout=10) as client:
        response = client.post(
            "/api/v1/auth/register",
            json={"username": username, "password": "secret123"},
        )
    if response.status_code == 201:
        body = response.json()
        # Reviewer endpoints need the seeded admin role; this is a scratch DB.
        with psycopg.connect(TEST_DSN, autocommit=True) as conn:
            conn.execute(
                """
                INSERT INTO user_roles (user_id, role_id)
                SELECT %s, id FROM roles WHERE code = 'admin'
                ON CONFLICT DO NOTHING
                """,
                (body["user"]["id"],),
            )
        return {"Authorization": f"Bearer {body['token']}"}
    if response.status_code in {404, 405}:
        return {}
    raise SystemExit(f"auth setup failed: {response.status_code} {response.text}")


def main() -> int:
    if not CONTRACT.is_file():
        raise SystemExit(f"{CONTRACT}: composed contract is missing; run `make contracts`")
    _create_database()
    atexit.register(_drop_database)
    os.environ["CLIVER_DATABASE_URL"] = TEST_DSN.replace(
        "postgresql://", "postgresql+asyncpg://", 1
    )

    # Imports must happen after CLIVER_DATABASE_URL points at the scratch DB.
    from app.migrations import run_migrations_online as run_project
    from app.settings import Settings
    from cliver_playbook.app.basic.alembic import (
        run_migrations_online as run_basic,
    )
    from cliver_playbook.app.rag.alembic import (
        run_migrations_online as run_rag,
    )
    from cliver_playbook.app.user.alembic import (
        run_migrations_online as run_user,
    )

    settings = Settings()
    run_basic(settings.sync_db_url)
    run_user(settings.sync_db_url)
    run_rag(settings.sync_db_url)
    run_project(settings.sync_db_url)

    port = _free_port()
    base_url = f"http://127.0.0.1:{port}"
    env = {
        **os.environ,
        "CLIVER_DATABASE_URL": os.environ["CLIVER_DATABASE_URL"],
    }
    process = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "uvicorn",
            "--factory",
            "app.app:create_app",
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
        ],
        cwd=API_ROOT,
        env=env,
    )
    try:
        _wait_healthy(base_url, process)
        headers = _auth_headers(base_url)
        executable = shutil.which("schemathesis")
        if executable is None:
            raise SystemExit("schemathesis is not installed; run `uv sync`")
        command = [
            executable,
            "run",
            str(CONTRACT),
            "-u",
            base_url,
            "--checks",
            "not_a_server_error",
            "--max-examples",
            "10",
            "--workers",
            "1",
        ]
        for name, value in headers.items():
            command.extend(["-H", f"{name}: {value}"])
        return subprocess.run(command, cwd=API_ROOT, check=False).returncode
    finally:
        process.terminate()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()


if __name__ == "__main__":
    raise SystemExit(main())
