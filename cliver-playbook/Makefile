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
web-ui-check: web-ui-init ## Type-check, lint and build every frontend package and shell
	@pnpm -r typecheck
	@pnpm -r lint
	@pnpm -r build

.PHONY: check
check: backend-lint backend-test web-ui-check ## Everything CI would run

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
