# Service scaffold Makefile — drives both workspaces with uv (backend) and pnpm (frontend).
# Targets follow the CraftForge convention: every target is self-documenting via `make help`.

.DEFAULT_GOAL := help

BACKEND_DIR := backend
FRONTEND_DIR := frontend
BACKEND_HOST ?= 127.0.0.1
BACKEND_PORT ?= 8000
WEB_UI_HOST ?= 127.0.0.1
WEB_UI_PORT ?= 5173

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
backend-init: ## Create backend/.venv with uv and install dependencies (dev group included)
	@cd $(BACKEND_DIR) && { test -d .venv || uv venv; } && uv sync

.PHONY: backend-migrate
backend-migrate: backend-init ## Apply the latest database migrations
	@cd $(BACKEND_DIR) && uv run alembic upgrade head

.PHONY: web-ui-init
web-ui-init: ## Install frontend dependencies
	@cd $(FRONTEND_DIR) && pnpm install

.PHONY: init
init: backend-init web-ui-init ## Install all dependencies (run `make db-up` first)

##@ Development servers

.PHONY: backend-start
backend-start: db-up backend-migrate ## Start the backend with auto-reload (http://127.0.0.1:8000)
	@cd $(BACKEND_DIR) && uv run uvicorn app.main:app --reload --host $(BACKEND_HOST) --port $(BACKEND_PORT)

.PHONY: web-ui-start
web-ui-start: web-ui-init ## Start the frontend dev server (http://127.0.0.1:5173)
	@cd $(FRONTEND_DIR) && pnpm run dev --host $(WEB_UI_HOST) --port $(WEB_UI_PORT)

##@ Quality

.PHONY: backend-test
backend-test: backend-init ## Run backend tests (requires the db container: make db-up)
	@cd $(BACKEND_DIR) && uv run pytest

.PHONY: backend-lint
backend-lint: backend-init ## Lint and check backend formatting
	@cd $(BACKEND_DIR) && uv run ruff check && uv run ruff format --check

.PHONY: web-ui-build
web-ui-build: web-ui-init ## Type-check and build the frontend production bundle
	@cd $(FRONTEND_DIR) && pnpm run build
