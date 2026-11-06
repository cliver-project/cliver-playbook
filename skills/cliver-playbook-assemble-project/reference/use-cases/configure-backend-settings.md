# Add a project backend setting

## Use when

The project needs a configuration value (a feature switch, a page size, an
external endpoint, a credential) that is not already a playbook setting.

Use `reference/use-cases/add-runtime-settings-section.md` instead when an
administrator must change the value at runtime without a restart.

Profile: any.

## Do

### 1. Add the field to the project Settings subclass

```python
# app/settings.py
from cliver_playbook.app.mcp.settings import Settings as PlaybookSettings


class Settings(PlaybookSettings):
    """Project settings; every playbook block is inherited unchanged."""

    feature_orders_enabled: bool = True
    orders_page_size: int = 50
```

Import the **most-derived** selected package:
`basic` → `cliver_playbook.app.basic.settings`,
`web` → `.user.settings`, `rag` → `.rag.settings`, `mcp` → `.mcp.settings`.
There is one runtime binding; never define a second parallel `Settings` class.

### 2. Give the project its own lazy proxy

```python
# app/settings.py (after the class)
from cliver_playbook.app.basic.runtime import lazy_settings

settings = lazy_settings(Settings)
```

Read values through this proxy (or the package proxy, which resolves to the
same bound instance) so a runtime override is visible everywhere:

```python
from app.settings import settings

if settings.feature_orders_enabled:
    ...
```

Do not call `Settings()` on a request path: that constructs a second instance
and bypasses runtime overrides.

### 3. Set the value in the right layer

Precedence, highest first:

1. constructor kwargs (tests and embedding)
2. `CLIVER_*` environment variables
3. project `.env`
4. runtime overrides persisted by Admin → Settings
5. `app.yaml` (bare field names)
6. field defaults

```sh
CLIVER_FEATURE_ORDERS_ENABLED=false
CLIVER_ORDERS_PAGE_SIZE=100
```

```yaml
# app.yaml — checked in, never carries secrets
feature_orders_enabled: true
orders_page_size: 50
```

Secrets belong in the environment or `.env`, never in `app.yaml`.

### 4. Validate a non-trivial value

A plain type annotation is enough for primitives. For a constrained value, use
Pydantic's `Field`/validators, or a small enum; the settings model is the
schema, so a bad deployment fails at startup with the field name.

## Verify

```sh
CLIVER_FEATURE_ORDERS_ENABLED=false uv run python -c "
from app.settings import Settings
print(Settings().feature_orders_enabled)
"
uv run pytest
uv run uvicorn --factory app.app:create_app --port 8000
```

The value must resolve in the same process the app uses. A field defined only
in `app.yaml` with a typo is silently ignored (`extra="ignore"`); confirm the
spelling against `Settings`.

## Pitfalls

- Adding a field to a playbook package is not a project change. Subclass it.
- `app.yaml` keys are bare field names; the `CLIVER_` prefix belongs only to
  the environment and `.env` layers.
- Environment values beat persisted runtime settings at restart. If an
  operator must override a field, do not also pin it in `.env`.
- If the value must be editable in the admin UI, a Settings field alone is not
  enough; register a section (next recipe).

## Source of truth

- `var/playbook/packages/backend/cliver-playbook-app-basic/src/cliver_playbook/app/basic/settings.py`
  — `Settings`, `settings_customise_sources`.
- `var/playbook/packages/backend/cliver-playbook-app-basic/src/cliver_playbook/app/basic/runtime.py`
  — `lazy_settings`, `configured_settings`.
- `var/playbook/packages/backend/cliver-playbook-app-basic/src/cliver_playbook/app/basic/config_yaml.py`
  — YAML layering and Jinja helpers.
- Deep dive: `reference/backend-composition.md` section "Settings".
