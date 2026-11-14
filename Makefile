# cliver-playbook — running the library's own composed stack.
#
# This repository is a library, not an application: the targets below exist so
# the packages can be exercised end to end (the composed app, its database, its
# frontend) without copying anything into a project. A consuming project gets
# its own Makefile from the skill that assembles it; the commands are the same
# shape, with the packages installed instead of living in this workspace.
#
# Targets are self-documenting: `make help`.

.DEFAULT_GOAL := help

BACKEND_HOST ?= 127.0.0.1
BACKEND_PORT ?= 8000
MCP_HTTP_PORT ?= 8100
WEB_UI_HOST ?= 127.0.0.1
WEB_UI_PORT ?= 5173

# The full-stack frontend shell (basic + user + mcp), and the reference for a
# composed project.
WEB_UI_FILTER := cliver-playbook-dev-mcp

# Every backend package. Each has its own pyproject (and therefore its own
# pytest and ruff configuration), so the targets below run them one by one
# rather than from the root.
BACKEND_PACKAGES := $(sort $(wildcard packages/backend/cliver-playbook-app-*))

.PHONY: help
help: ## Display this help.
	@awk 'BEGIN {FS = ":.*##"; printf "\nUsage:\n  make \033[36m<target>\033[0m\n"} /^[a-zA-Z_0-9-]+:.*?##/ { printf "  \033[36m%-20s\033[0m %s\n", $$1, $$2 } /^##@/ { printf "\n\033[1m%s\033[0m\n", substr($$0, 5) } ' $(MAKEFILE_LIST)

##@ Setup

.PHONY: db-up
db-up: ## Start the PostgreSQL container (docker compose, detached)
	docker compose up -d db

.PHONY: db-down
db-down: ## Stop the PostgreSQL container
	docker compose down

.PHONY: backend-init
backend-init: ## Create the workspace venv and install every package in editable mode
	uv sync

.PHONY: db-init
db-init: backend-init db-up ## Apply every package's migration chain, dependencies first
	@uv run python -m cliver_playbook.app.mcp.migrate

.PHONY: web-ui-init
web-ui-init: ## Install the frontend workspace dependencies
	pnpm install

.PHONY: init
init: backend-init web-ui-init ## Install everything (run `make db-up` first)

##@ Development

.PHONY: backend-start
backend-start: db-init ## Start the composed app with auto-reload (http://127.0.0.1:8000)
	@uv run uvicorn --factory cliver_playbook.app.mcp.app:create_app \
		--reload --host $(BACKEND_HOST) --port $(BACKEND_PORT)

.PHONY: web-ui-start
web-ui-start: web-ui-init ## Start the composed frontend shell (http://127.0.0.1:5173)
	@pnpm --filter $(WEB_UI_FILTER) dev --host $(WEB_UI_HOST) --port $(WEB_UI_PORT)

##@ Quality

.PHONY: backend-test
backend-test: backend-init ## Run every package's tests (requires the db container: make db-up)
	@for pkg in $(BACKEND_PACKAGES); do \
		echo "=== $$pkg ==="; \
		(cd $$pkg && uv run pytest) || exit 1; \
	done

.PHONY: backend-lint
backend-lint: backend-init ## Check backend formatting and imports
	@for pkg in $(BACKEND_PACKAGES); do \
		echo "=== $$pkg ==="; \
		(cd $$pkg && uv run ruff check && uv run ruff format --check) || exit 1; \
	done

.PHONY: web-ui-check
web-ui-check: web-ui-init ## Type-check, test, lint and build every frontend package and shell
	@pnpm -r typecheck
	@pnpm -r lint
	@pnpm -r --if-present test
	@pnpm -r build

.PHONY: version-check
version-check: ## Verify every backend and frontend module shares one version
	python3 scripts/version.py --check

.PHONY: skill-check
skill-check: ## Validate the published agent skill (frontmatter, references, manifest example)
	uv run --with pyyaml python scripts/validate_skill.py --self-test
	uv run --with pyyaml python scripts/validate_skill.py --all

.PHONY: scaffold-check
scaffold-check: ## Validate the AI-native scaffold catalog, schema and planner
	uv run --with pyyaml --with jsonschema python scripts/scaffold_project.py --self-test
	uv run --with pyyaml --with jsonschema python scripts/scaffold_project.py --validate-catalog

.PHONY: scaffold-plan
scaffold-plan: ## Print the AI-native scaffold plan (MANIFEST=scaffold/examples/ai-web.yaml)
	@test -n "$(MANIFEST)" || { echo "usage: make scaffold-plan MANIFEST=scaffold/examples/ai-web.yaml" >&2; exit 2; }
	uv run --with pyyaml --with jsonschema python scripts/scaffold_project.py --plan "$(MANIFEST)"

.PHONY: version-set
version-set: ## Bump every module (usage: make version-set VERSION=0.2.0)
	@test -n "$(VERSION)" || { echo "usage: make version-set VERSION=x.y.z" >&2; exit 2; }
	python3 scripts/version.py --set $(VERSION)
	uv lock
	pnpm install --lockfile-only

.PHONY: release-check
release-check: ## Build every backend distribution and verify license + version metadata
	rm -rf dist
	uv build --all-packages --out-dir dist
	uv run python scripts/check_release_artifacts.py --dist dist

.PHONY: check
check: backend-lint backend-test web-ui-check version-check skill-check scaffold-check ## Everything CI would run

.PHONY: verify-reference
verify-reference: ## Migrate a scratch DB, boot the composed app, build the reference frontend
	./scripts/smoke_reference.sh

##@ Release

.PHONY: release
release: ## Cut a release (make release [VERSION=x.y.z]); quits if the version is not bumped
	python3 scripts/release.py $(if $(VERSION),--version $(VERSION),) $(if $(DRY_RUN),--dry-run,)

##@ RAG governance demo

# The governance demo (packages/backend/cliver-playbook-app-rag-governance,
# README "Local demo") runs on offset ports so it never fights the composed
# dev stack (5432/8000) or other services on this machine. The compose file
# owns the demo PostgreSQL; the mock Kingdee server and the standalone app
# run on the host like every other dev process here. The app is the finance
# scenario's factory (examples/finance_kpi/app.py), which additionally
# registers the scenario's tools; generation uses the local ollama endpoint
# by default — point the GOV_LLM_* variables elsewhere or start ollama first.
GOV_COMPOSE_FILE := docker-compose.gov-demo.yml
GOV_DB_PORT ?= 15432
GOV_APP_PORT ?= 18000
GOV_MOCK_PORT ?= 18080
GOV_WEB_PORT ?= 5174
GOV_DB_DSN_PSYCOPG := postgresql+psycopg://cliver:cliver@127.0.0.1:$(GOV_DB_PORT)/cliver_app
GOV_DB_DSN_ASYNCPG := postgresql+asyncpg://cliver:cliver@127.0.0.1:$(GOV_DB_PORT)/cliver_app
GOV_DB_DSN_PLAIN := postgresql://cliver:cliver@127.0.0.1:$(GOV_DB_PORT)/cliver_app
GOV_MOCK_FIXTURES := packages/backend/cliver-playbook-app-rag-governance/examples/finance_kpi/fixtures/kingdee
GOV_LLM_BASE_URL ?= http://127.0.0.1:11434/v1
GOV_LLM_MODEL ?= qwen3.6:latest
GOV_LLM_API_KEY ?= ollama
GOV_VAR_DIR := var/gov-demo
GOV_PKG_DIR := packages/backend/cliver-playbook-app-rag-governance

.PHONY: gov-demo-up
gov-demo-up: backend-init ## Start the governance demo: db (compose) + mock Kingdee + app
	@mkdir -p $(GOV_VAR_DIR)
	GOV_DB_PORT=$(GOV_DB_PORT) docker compose -f $(GOV_COMPOSE_FILE) up -d --wait db
	@echo "==> Applying every migration chain to the demo database (idempotent)"
	@CLIVER_DATABASE_URL=$(GOV_DB_DSN_ASYNCPG) \
		uv run python -m cliver_playbook.app.rag_governance.migrate \
			--database-url $(GOV_DB_DSN_PSYCOPG)
	@if nc -z 127.0.0.1 $(GOV_MOCK_PORT) 2>/dev/null; then \
		echo "==> Mock Kingdee already listening on $(GOV_MOCK_PORT)"; \
	else \
		echo "==> Starting the mock Kingdee MCP server on $(GOV_MOCK_PORT)"; \
		nohup uv run python -m cliver_playbook.app.rag_governance.testing.mock_kingdee.server \
			--fixtures $(GOV_MOCK_FIXTURES) --period 2026-10 --port $(GOV_MOCK_PORT) \
			>$(GOV_VAR_DIR)/mock.log 2>&1 & echo $$! > $(GOV_VAR_DIR)/mock.pid; \
	fi
	@echo "==> Governance app on http://127.0.0.1:$(GOV_APP_PORT) (docs: /docs)"
	@echo "==> Next: make gov-demo-seed ADMIN_PASSWORD=… then make gov-demo-web"
	@echo "==> Ctrl-C stops the app; make gov-demo-down stops the whole demo"
	@cd $(GOV_PKG_DIR) && CLIVER_DATABASE_URL=$(GOV_DB_DSN_ASYNCPG) \
		GOV_DEMO_MOCK_URL=http://127.0.0.1:$(GOV_MOCK_PORT)/mcp \
		CLIVER_RAG__LLM=cliver-core \
		CLIVER_RAG__CLIVER_LLM__BASE_URL=$(GOV_LLM_BASE_URL) \
		CLIVER_RAG__CLIVER_LLM__MODEL=$(GOV_LLM_MODEL) \
		CLIVER_RAG__CLIVER_LLM__API_KEY=$(GOV_LLM_API_KEY) \
		uv run python -m uvicorn --factory examples.finance_kpi.app:create_demo_app \
		--host 127.0.0.1 --port $(GOV_APP_PORT)

.PHONY: gov-demo-web
gov-demo-web: web-ui-init ## Start the governance demo web UI (http://127.0.0.1:5174)
	@pnpm --filter cliver-playbook-dev-gov dev --host 127.0.0.1 --port $(GOV_WEB_PORT)

.PHONY: gov-demo-seed
gov-demo-seed: ## Seed the finance scenario (ADMIN_PASSWORD=… [ADMIN_NEW_PASSWORD=…]); run after gov-demo-up
	@test -n "$(ADMIN_PASSWORD)" || { echo "usage: make gov-demo-seed ADMIN_PASSWORD=… [ADMIN_NEW_PASSWORD=…]" >&2; exit 2; }
	@cd $(GOV_PKG_DIR) && uv run python -m examples.finance_kpi.seed_demo \
		--app-url http://127.0.0.1:$(GOV_APP_PORT) \
		--database-url $(GOV_DB_DSN_PLAIN) \
		--admin-password "$(ADMIN_PASSWORD)" \
		$(if $(ADMIN_NEW_PASSWORD),--new-password "$(ADMIN_NEW_PASSWORD)",)

.PHONY: gov-demo-down
gov-demo-down: ## Stop the governance demo (db container + mock server; data volume kept)
	@if [ -f $(GOV_VAR_DIR)/mock.pid ] && kill -0 $$(cat $(GOV_VAR_DIR)/mock.pid) 2>/dev/null; then \
		echo "==> Stopping the mock Kingdee server"; \
		kill $$(cat $(GOV_VAR_DIR)/mock.pid) || true; \
	fi
	@rm -f $(GOV_VAR_DIR)/mock.pid
	GOV_DB_PORT=$(GOV_DB_PORT) docker compose -f $(GOV_COMPOSE_FILE) down
	@echo "==> Data volume kept; full reset: docker compose -f $(GOV_COMPOSE_FILE) down -v"

##@ MCP server

# The composed app already serves /mcp in-process. These targets start the MCP
# surface as a SEPARATE process on demand: stdio for a local CLI agent that
# pipes JSON-RPC over stdin, http for a sidecar listener on its own port.
# Both share this repository's database and app.yaml.
.PHONY: mcp-stdio
mcp-stdio: backend-init ## Run the MCP server over stdio (separate process, same DB)
	@uv run python -m cliver_playbook.app.mcp --transport stdio

.PHONY: mcp-http
mcp-http: backend-init ## Run the MCP-capable app over http on MCP_HTTP_PORT (default 8100)
	@uv run python -m cliver_playbook.app.mcp --transport http --host $(BACKEND_HOST) --port $(MCP_HTTP_PORT)
