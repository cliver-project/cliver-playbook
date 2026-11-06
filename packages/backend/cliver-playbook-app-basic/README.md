# cliver-playbook-app-basic

Foundations package of the cliver-playbook library — everything a service
needs before business code: layered settings, the process runtime, and one
runnable API slice.

## What is inside

| Area | Path (under `src/cliver_playbook/app/basic/`) | Notes |
|---|---|---|
| Settings | `settings.py` | Layered: env > .env > runtime overrides > app.yaml (Jinja2) > defaults. Subclass `Settings` to extend (ADR-0016). |
| Runtime | `runtime.py` | `configure(settings)` binds settings + async engine once per process; nothing is built at import time. |
| Runtime settings | `runtime_settings.py` | Package-owned settings sections: field description, validation, live apply, `app_settings` persistence and the lifespan overlay (ADR-0021). |
| Routers | `api/routes.py` | `ROUTERS: list[APIRouter]` — a composed app includes them (ADR-0015). |
| Pagination | `schemas/pagination.py`, `api/pagination.py` | The shared `Page[T]` response envelope and the `page_params()` limit/offset dependency, with per-route bounds. |
| Demo slice | `api/items.py`, `services/`, `schemas/`, `models/entities.py` | Full CRUD example: the `items` table and `/api/v1/items`. Optional — delete together with its migration and tests. |
| Migrations | `alembic/` | Own chain, version table `alembic_version_basic`; creates `items` and `app_settings`. |
| Application | `app.py`, `__main__.py` | `create_app()` and `python -m cliver_playbook.app.basic`. |

## Pagination

Paginated endpoints return the shared `Page[T]` envelope and parse their
window with `page_params()`. The factory's bounds are per endpoint; an
out-of-range `limit` or `offset` is a 422, never a silently clamped request.

```python
from fastapi import Depends

from cliver_playbook.app.basic.api.pagination import PageParams, page_params
from cliver_playbook.app.basic.schemas.pagination import Page


@router.get("", response_model=Page[OrderRead])
async def list_orders(
    params: PageParams = Depends(page_params(default_limit=50, max_limit=200)),
    db: AsyncSession = Depends(get_db),
) -> Page[OrderRead]:
    rows, total = await service.list_orders(db, limit=params.limit, offset=params.offset)
    return Page[OrderRead](
        items=[OrderRead.model_validate(row) for row in rows],
        total=total,
        limit=params.limit,
        offset=params.offset,
    )
```

`total` counts the full filtered set, not the rows in `items`. The identity
package's audit listing and the MCP activity feed are the worked examples.

## Install

```bash
python -m pip install -e .                     # from this directory
# consuming project, same virtualenv (dependency first, then this):
python -m pip install -e ../cliver-playbook-app-basic
```

Editable installs of sibling packages coexist in one virtualenv: the
`cliver_playbook` and `cliver_playbook.app` namespace directories are
PEP 420 — deliberately no `__init__.py` — so every package's portion merges.

## Run standalone

```bash
docker compose up -d db        # or point CLIVER_DATABASE_URL at PostgreSQL
python -m cliver_playbook.app.basic --reload
# GET /api/v1/health, /api/v1/version, /api/v1/items
```

Configuration resolves relative to the current working directory: the nearest
ancestor containing `app.yaml` or `.env` is the application root (`CLIVER_CONFIG_FILE`
overrides). See `settings.py` and `config_yaml.py`.

## Migrate

```bash
python -c "from cliver_playbook.app.basic.alembic import run_migrations_online; run_migrations_online()"
# interactive, from this directory:
alembic upgrade head
```

## Test

```bash
python -m pytest        # needs PostgreSQL; creates and drops a temp database
```
