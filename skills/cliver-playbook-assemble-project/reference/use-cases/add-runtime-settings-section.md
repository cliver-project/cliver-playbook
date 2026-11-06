# Add an admin-editable settings section

## Use when

An operator must change project settings from **Admin → Settings** without a
restart: feature switches, limits, model selections. Bootstrap values and
credentials that should stay in the environment do not belong here.

Profile: `web`, `rag`, or `mcp`.

## Do

### 1. Register one section

```python
# app/settings_section.py
from typing import Any

from cliver_playbook.app.basic.runtime_settings import (
    SettingsField,
    SettingsSection,
    register_settings_section,
)


def _fields() -> tuple[SettingsField, ...]:
    return (
        SettingsField(
            name="feature_orders_enabled",
            label="Enable orders",
            type="boolean",
            description="Turns the orders surface on for this deployment.",
            env_var="CLIVER_FEATURE_ORDERS_ENABLED",
        ),
        SettingsField(
            name="orders_page_size",
            label="Orders page size",
            type="integer",
            minimum=10,
            maximum=200,
        ),
    )


def _read(settings: Any) -> dict[str, Any]:
    return {
        "feature_orders_enabled": settings.feature_orders_enabled,
        "orders_page_size": settings.orders_page_size,
    }


def _apply(settings: Any, values: dict[str, Any]) -> None:
    # Validate the complete merged state before mutating anything.
    merged = {**_read(settings), **values}
    settings.feature_orders_enabled = bool(merged["feature_orders_enabled"])
    settings.orders_page_size = int(merged["orders_page_size"])


register_settings_section(
    SettingsSection(
        key="orders",
        title="Orders",
        description="Project-owned feature switches.",
        fields=_fields,
        read=_read,
        apply=_apply,
    )
)
```

The section key is process-wide and must be unique. `read` returns raw values
(including secrets, for the configured/not-configured check); the HTTP layer
is what hides a `secret=True` value from responses.

### 2. Import it at startup

```python
# app/__init__.py
from app import permissions, settings_section  # noqa: F401 — register before serving
```

The import order matters only in that it must happen before requests; the
admin page discovers sections from the registry.

### 3. Add the fields to the Settings subclass

Runtime settings mutate the bound settings instance. The fields must exist on
`app/settings.py` (see `configure-backend-settings.md`). The section is the
UI and persistence layer, not a second configuration model.

### 4. Add translations (optional)

The page falls back to the English strings the backend returns, so the section
renders without frontend changes. To localize it, add this namespace to the
project bundle:

```json
{
  "settingsSections": {
    "orders": {
      "title": "Orders",
      "description": "Project-owned feature switches.",
      "fields": {
        "feature_orders_enabled": {
          "label": "Enable orders",
          "description": "Turns the orders surface on for this deployment."
        }
      }
    }
  }
}
```

## Verify

```sh
uv run uvicorn --factory app.app:create_app --port 8000
curl -fsS -H "Authorization: Bearer <admin-token>" \
  http://127.0.0.1:8000/api/v1/admin/settings
```

The section appears with its fields. Submit a `PUT` to
`/api/v1/admin/settings/orders`; the value persists in `app_settings`, applies
without a restart, and is restored by reset. Restart once and confirm the
persisted value still applies.

## Pitfalls

- `_apply` must validate all values before mutating; a half-applied section
  leaves the process in a state the UI cannot describe.
- A field managed by an environment variable is read-only in the UI. That is
  deliberate: the environment wins at restart, so editing it would lie.
- `secret=True` fields are write-only; never return the stored value from
  `_read` through a custom endpoint.
- Section keys are global across packages. Prefix a project section with the
  product or domain name if a collision is plausible.

## Source of truth

- `var/playbook/packages/backend/cliver-playbook-app-basic/src/cliver_playbook/app/basic/runtime_settings.py`
  — `SettingsField`, `SettingsSection`, `register_settings_section`,
  `settings_lifespan`.
- `var/playbook/packages/backend/cliver-playbook-app-user/src/cliver_playbook/app/user/api/admin_settings.py`
  — the generic describe/update/reset HTTP layer.
- `var/playbook/packages/backend/cliver-playbook-app-user/src/cliver_playbook/app/user/settings_section.py`
  — a package-owned worked example.
- Deep dive: `reference/decision-guide.md` section "Project runtime settings
  section".
