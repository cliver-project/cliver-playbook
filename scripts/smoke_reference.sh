#!/usr/bin/env bash
# Reference composition smoke test.
#
# Mirrors what a consuming project does after assembling from the playbook:
# migrate a throwaway database, boot the composed backend against it, hit the
# health endpoint, and build the full-stack reference frontend. Everything
# scratch is removed on exit, whether the run succeeded or failed.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

DB_NAME="cliver_reference_smoke_$$"
SCRATCH_DSN="postgresql://cliver:cliver@127.0.0.1:5432/${DB_NAME}"
HEALTH_URL="http://127.0.0.1:8111/api/v1/health"
BACKEND_PID=""
BACKEND_LOG="$(mktemp "${TMPDIR:-/tmp}/cliver-reference-smoke.XXXXXX.log")"

cleanup() {
    status=$?
    if [[ -n "$BACKEND_PID" ]] && kill -0 "$BACKEND_PID" 2>/dev/null; then
        kill "$BACKEND_PID" 2>/dev/null || true
        wait "$BACKEND_PID" 2>/dev/null || true
    fi
    docker compose exec -T db psql -U cliver -d postgres \
        -c "DROP DATABASE IF EXISTS \"${DB_NAME}\"" >/dev/null 2>&1 || true
    rm -f "$BACKEND_LOG"
    exit "$status"
}
trap cleanup EXIT

echo "==> Starting the database container"
make db-up
docker compose up -d --wait db >/dev/null

echo "==> Creating scratch database ${DB_NAME}"
docker compose exec -T db psql -U cliver -d postgres -v ON_ERROR_STOP=1 \
    -c "CREATE DATABASE \"${DB_NAME}\"" >/dev/null

echo "==> Applying every migration chain to the scratch database"
uv run python -m cliver_playbook.app.mcp.migrate --database-url "$SCRATCH_DSN"

echo "==> Booting the composed app on 127.0.0.1:8111"
CLIVER_DATABASE_URL="$SCRATCH_DSN" uv run uvicorn --factory \
    cliver_playbook.app.mcp.app:create_app \
    --host 127.0.0.1 --port 8111 >"$BACKEND_LOG" 2>&1 &
BACKEND_PID=$!

echo "==> Waiting for ${HEALTH_URL}"
ready=0
for _ in $(seq 1 30); do
    if curl -fsS "$HEALTH_URL" >/dev/null 2>&1; then
        ready=1
        break
    fi
    if ! kill -0 "$BACKEND_PID" 2>/dev/null; then
        echo "backend exited before becoming healthy" >&2
        break
    fi
    sleep 1
done
if [[ "$ready" -ne 1 ]]; then
    echo "health check did not pass; backend log:" >&2
    cat "$BACKEND_LOG" >&2
    exit 1
fi
echo "health: $(curl -fsS "$HEALTH_URL")"

echo "==> Building the full-stack reference frontend"
pnpm --filter cliver-playbook-dev-mcp build

echo "==> Reference smoke test passed"
