"""Seed the finance-KPI demo scenario through the real HTTP API.

Run from the package directory against a running demo app
(``make gov-demo-up``) and its database::

    uv run python -m examples.finance_kpi.seed_demo \
        --app-url http://127.0.0.1:18000 \
        --database-url postgresql://cliver:cliver@127.0.0.1:15432/cliver_app \
        --admin-password "$(grep CLIVER_INITIAL_ADMIN_PASSWORD .env | cut -d= -f2)"

What it does, and just as importantly what it leaves for the demo:

- logs in (changing the seeded admin password once if the deployment forces
  it), creates the ``finance-kpi`` project, and imports + confirms golden set
  v1 from ``golden/v1.jsonl``;
- proposes the finance intent rules (activation is the demo's job: it must
  clear an evaluation first);
- creates the ``directory`` source over ``seed/`` and triggers one ingest,
  then waits until the batch is ``staged`` — approval is the demo's job too;
- writes the two rows the HTTP surface does not own: the ``admin`` role's
  clearance (golden cases run at clearance 4) and the project's tool bindings
  for the finance composites (the query facade authorizes tools against
  ``gov_tools`` rows, not the in-process registry alone).

Re-running is safe: the project is looked up by slug, sources and golden sets
by their existing versions, and the ingest enqueue is idempotent per batch.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any

import httpx
import psycopg

from examples.finance_kpi.rules import FINANCE_RULES

EXAMPLES = Path(__file__).resolve().parent
SEED_DIR = EXAMPLES / "seed"
GOLDEN_JSONL = EXAMPLES / "golden" / "v1.jsonl"

PROJECT_SLUG = "finance-kpi"
# The reference rules pin "sparse" for the SQLite acceptance suite; the live
# Postgres demo needs the dense-capable mode for Chinese (see _demo_rules).
DEMO_RETRIEVAL_MODE = "hybrid"
# Mirrors the acceptance test's config, with the real (cached-weights)
# embedder and hybrid retrieval: the demo should show the production path,
# not the test stub.
PROJECT_CONFIG: dict[str, Any] = {
    "scope_combination": "highest_priority",
    "retrieval": {
        "mode": "hybrid",
        "top_k": 20,
        "rerank_top_k": 10,
        "reranker": "noop",
    },
    "embedding": {"embedder": "bge-base-zh-v1.5"},
    # The scenario's filename-based taxonomy (examples/finance_kpi/stages.py):
    # rule scopes filter on doc_type, and the built-in by-extension classifier
    # would call every markdown file "markdown".
    "taxonomy": {"classifier": "finance-doc-type"},
    "freshness": {"max_staleness_seconds": 86_400},
    "thresholds": {
        "intent.pass_rate": 1.0,
        "retrieval.recall": 1.0,
        "tool-routing.routing_accuracy": 1.0,
        "groundedness.numeric_facts": 1.0,
    },
}
TOOL_BINDINGS = ("finance_kpi_snapshot", "finance_receivables_aging")
ADMIN_ROLE_CLEARANCE = 5


class SeedError(RuntimeError):
    """A seeding step failed with context the operator can act on."""


class Api:
    """The authenticated JSON client for the seeding steps."""

    def __init__(self, base_url: str) -> None:
        self._client = httpx.Client(base_url=base_url, timeout=30.0)
        self._token: str | None = None

    def login(self, username: str, password: str, new_password: str | None) -> None:
        response = self._client.post(
            "/api/v1/auth/login",
            json={"username": username, "password": password},
        )
        body: dict[str, Any] = response.json()
        if response.status_code != 200:
            raise SeedError(f"login failed ({response.status_code}): {body}")
        token = body.get("token")
        if body.get("must_change_password"):
            if not new_password:
                raise SeedError("the seeded admin must change password; pass --new-password")
            response = self._client.post(
                "/api/v1/auth/change-password",
                headers={"Authorization": f"Bearer {token}"},
                json={"old_password": password, "new_password": new_password},
            )
            if response.status_code != 200:
                raise SeedError(
                    f"password change failed ({response.status_code}): {response.json()}"
                )
            token = response.json()["token"]
        self._token = token

    def request(self, method: str, path: str, **kwargs: Any) -> Any:
        assert self._token is not None
        response = self._client.request(
            method,
            path,
            headers={"Authorization": f"Bearer {self._token}"},
            **kwargs,
        )
        if response.status_code >= 400:
            raise SeedError(f"{method} {path} failed ({response.status_code}): {response.text}")
        return response.json() if response.content else None

    def get(self, path: str) -> Any:
        return self.request("GET", path)

    def post(self, path: str, json_body: Any = None) -> Any:
        return self.request("POST", path, json=json_body)

    def close(self) -> None:
        self._client.close()


def _ensure_project(api: Api) -> dict[str, Any]:
    for project in api.get("/api/v1/rag-governance/projects")["items"]:
        if project["slug"] == PROJECT_SLUG:
            # Converge an existing project onto this seed's configuration, so
            # a re-run after a scenario change (a new classifier, embedder or
            # retrieval mode) takes effect instead of silently keeping the
            # old config.
            if project["config"] != PROJECT_CONFIG:
                return api.request(
                    "PUT",
                    f"/api/v1/rag-governance/projects/{project['id']}",
                    json={"config": PROJECT_CONFIG},
                )
            return project
    return api.post(
        "/api/v1/rag-governance/projects",
        {
            "slug": PROJECT_SLUG,
            "name": "Finance KPI",
            "description": "Monthly finance KPIs: live ERP metrics plus policy documents.",
            "approval_mode": "manual",
            "config": PROJECT_CONFIG,
        },
    )


def _ensure_golden(api: Api, project_id: str) -> dict[str, Any]:
    existing = api.get(f"/api/v1/rag-governance/projects/{project_id}/golden")["items"]
    if existing:
        newest = existing[0]
        if newest["status"] == "confirmed":
            return newest
        api.post(f"/api/v1/rag-governance/golden/{newest['id']}/confirm")
        return api.get(f"/api/v1/rag-governance/golden/{newest['id']}")
    created = api.post(
        f"/api/v1/rag-governance/projects/{project_id}/golden/import",
        {"jsonl": GOLDEN_JSONL.read_text(encoding="utf-8")},
    )
    return api.post(f"/api/v1/rag-governance/golden/{created['id']}/confirm")


def _demo_rules() -> list[dict[str, Any]]:
    """The reference rules, with retrieval switched to the production leg.

    ``examples/finance_kpi/rules.py`` pins ``mode="sparse"`` because the
    acceptance suite runs on SQLite's ASCII BM25 fallback. On Postgres the
    sparse leg is ``to_tsvector('english', …)`` — Chinese text never matches
    it — so the live demo asks for ``hybrid`` (dense vectors plus the
    lexical leg when it applies).
    """
    rules = [rule.model_dump() for rule in FINANCE_RULES]
    for rule in rules:
        retrieval = dict(rule.get("retrieval") or {})
        retrieval["mode"] = DEMO_RETRIEVAL_MODE
        rule["retrieval"] = retrieval
    return rules


def _ensure_rules(api: Api, project_id: str) -> None:
    versions = api.get(f"/api/v1/rag-governance/projects/{project_id}/rules/versions")
    current = sorted(
        (item for item in versions["items"] if item["status"] in ("proposed", "active")),
        key=lambda item: item["version"] or 0,
    )
    if current and all(
        (rule.get("retrieval") or {}).get("mode") == DEMO_RETRIEVAL_MODE
        for rule in current[-1]["rules"]
    ):
        return  # The live-mode set is already proposed or active.
    api.post(
        f"/api/v1/rag-governance/projects/{project_id}/rules/propose",
        {"rules": _demo_rules()},
    )


def _ensure_source(api: Api, project_id: str) -> dict[str, Any]:
    for source in api.get(f"/api/v1/rag-governance/projects/{project_id}/sources")["items"]:
        if source["kind"] == "directory":
            return source
    return api.post(
        f"/api/v1/rag-governance/projects/{project_id}/sources",
        {"kind": "directory", "config": {"path": str(SEED_DIR.resolve())}},
    )


def _ensure_ingest(api: Api, source: dict[str, Any]) -> dict[str, Any]:
    """Reuse an in-flight or published batch; only ingest when there is none.

    Re-running the seed must not stage the corpus a second time (each ingest
    is a fresh batch that would then need its own review).
    """
    for batch in api.get(f"/api/v1/rag-governance/projects/{source['project_id']}/batches")[
        "items"
    ]:
        if batch.get("source_id") == source["id"] and batch["status"] in (
            "staged",
            "review_pending",
            "published",
        ):
            return batch
    return _trigger_ingest(api, source)


def _trigger_ingest(api: Api, source: dict[str, Any]) -> dict[str, Any]:
    # The endpoint takes an (empty) IngestRequest body reserved for overrides;
    # no body at all is a 422.
    accepted = api.post(f"/api/v1/rag-governance/sources/{source['id']}/ingest", {})
    batch_id = accepted["batch_id"]
    # Embedding six markdown files takes seconds; the load of the BGE model on
    # first use takes longer. Poll until the batch leaves the queue/running
    # states — staged, or a terminal failure, ends the wait.
    for _ in range(240):
        batch = api.get(f"/api/v1/rag-governance/batches/{batch_id}")
        if batch["status"] not in ("queued", "running"):
            return batch
        time.sleep(1.0)
    raise SeedError(f"ingest batch {batch_id} did not finish staging in time")


def _write_db_rows(database_url: str, project_id: str) -> None:
    """The two rows no HTTP API owns: role clearance and tool bindings."""
    with psycopg.connect(database_url, autocommit=True) as conn:
        conn.execute(
            """
            INSERT INTO gov_principal_clearance (principal_type, principal_id, level)
            VALUES ('role', 'admin', %(level)s)
            ON CONFLICT (principal_type, principal_id) DO UPDATE SET level = EXCLUDED.level
            """,
            {"level": ADMIN_ROLE_CLEARANCE},
        )
        for name in TOOL_BINDINGS:
            conn.execute(
                """
                INSERT INTO gov_tools
                    (id, project_id, name, kind, config_json, schema_json, read_only,
                     min_clearance, scope_json, masking_json, result_cap_json, enabled)
                VALUES (gen_random_uuid()::text, %(project)s, %(name)s, 'composite', '{}', '{}',
                        true, 3, '{}', '{}', '{}', true)
                ON CONFLICT (project_id, name) DO NOTHING
                """,
                {"project": project_id, "name": name},
            )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--app-url", default="http://127.0.0.1:18000")
    parser.add_argument(
        "--database-url", default="postgresql://cliver:cliver@127.0.0.1:15432/cliver_app"
    )
    parser.add_argument("--admin-user", default="admin")
    parser.add_argument("--admin-password", required=True)
    parser.add_argument(
        "--new-password",
        default=None,
        help="set when the seeded admin still must change password",
    )
    args = parser.parse_args(argv)

    api = Api(args.app_url.rstrip("/"))
    try:
        api.login(args.admin_user, args.admin_password, args.new_password)
        project = _ensure_project(api)
        golden = _ensure_golden(api, project["id"])
        _ensure_rules(api, project["id"])
        source = _ensure_source(api, project["id"])
        batch = _ensure_ingest(api, source)
        _write_db_rows(args.database_url, project["id"])
    finally:
        api.close()

    if batch["status"] not in ("staged", "review_pending", "published"):
        raise SeedError(f"ingest ended in status {batch['status']!r}, not 'staged'/'published'")

    stats = batch.get("stats") or {}
    print(
        json.dumps(
            {
                "project_id": project["id"],
                "golden_set_id": golden["id"],
                "golden_version": golden["version"],
                "source_id": source["id"],
                "staged_batch_id": batch["id"],
                "staged_documents": stats.get("documents"),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    print(
        "\nDemo state is ready. In the UI: approve the staged batch → run the "
        "baseline evaluation → activate the rules → ask governed questions.",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
