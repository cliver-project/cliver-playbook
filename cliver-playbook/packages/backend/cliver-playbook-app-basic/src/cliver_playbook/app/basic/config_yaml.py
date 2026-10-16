"""Layered configuration: the YAML + Jinja2 tier underneath env and .env.

Precedence (highest first), assembled by ``Settings.settings_customise_sources``
in settings.py:

    constructor kwargs  >  environment variables  >  .env  >  app.yaml  >  field defaults

This module owns the bottom-most tier — an optional ``app.yaml`` at the
application root, rendered as a Jinja2 template before YAML parsing — plus the
discovery of the application root and its .env. The checked-in file describes
*structure and non-secret defaults*; anything sensitive stays in the
environment/.env layer and never in the repository.

Application-root discovery: an installed package has no fixed relationship to
the project consuming it, so nothing here anchors to ``__file__`` (that would
point into site-packages). The root is the nearest ancestor of the current
working directory — the CWD itself included — that contains ``app.yaml`` or
``.env``; conventionally the two live side by side. Discovery happens per
Settings instantiation, so a process may be started from anywhere below the
project root. ``$CLIVER_CONFIG_FILE`` remains a hard override for unusual
layouts (see ``resolve_config_path``).

Why Jinja2 in front of YAML:

- values can be composed from environment variables at load time
  (``{{ env("SOME_HOST", "127.0.0.1") }}``) instead of forcing every
  combination into one flat variable;
- required inputs fail fast at startup with the variable named, instead of
  surfacing later as a confusing runtime error;
- the helper surface (``JINJA_GLOBALS``) is a deliberate extension point —
  a project can add its own pure functions without touching loading logic.

Keys inside the YAML are the *bare Settings field names* (``database_url``),
NOT the ``CLIVER_``-prefixed env names — the file feeds the Settings model
directly, mirroring the Spring Boot application.yaml convention.

The rendering environment is sandboxed (``SandboxedEnvironment``) with
``StrictUndefined`` (a typo'd template variable raises instead of silently
rendering empty). Literal Jinja syntax inside YAML values must be wrapped in
``{% raw %}...{% endraw %}``.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import yaml
from dotenv import dotenv_values
from jinja2 import StrictUndefined, TemplateError
from jinja2.sandbox import SandboxedEnvironment
from pydantic_settings import YamlConfigSettingsSource

DEFAULT_CONFIG_FILENAME = "app.yaml"
ENV_FILENAME = ".env"
CONFIG_FILE_ENV_VAR = "CLIVER_CONFIG_FILE"


class ConfigError(RuntimeError):
    """The configuration layer cannot produce a usable Settings object.

    Deliberately loud and specific: a broken app.yaml takes down uvicorn,
    alembic and pytest collection alike, so every message names the file and
    the underlying cause — a bare ValidationError deep inside startup tells
    an operator nothing about which layer failed.
    """


def resolve_project_root() -> Path | None:
    """Locate the application root by walking up from the current directory.

    The root is the nearest ancestor (CWD included) containing ``app.yaml``
    or ``.env``. Returns None when neither exists anywhere up the tree — the
    configuration then falls back to the environment layer and field
    defaults alone, a legitimate setup (e.g. a container configured purely
    through env vars).
    """
    cwd = Path.cwd()
    for directory in (cwd, *cwd.parents):
        if (directory / DEFAULT_CONFIG_FILENAME).is_file():
            return directory
        if (directory / ENV_FILENAME).is_file():
            return directory
    return None


def resolve_config_path() -> Path | None:
    """Locate the YAML config file, or None when there legitimately is none.

    1. ``$CLIVER_CONFIG_FILE`` — explicit override (tests, unusual layouts).
       Pointing it at a missing file is a hard error: an explicit override
       that silently does nothing is a misconfiguration, not a fallback.
    2. ``<application root>/app.yaml`` — the conventional checked-in
       location. Absent is fine: the YAML layer is optional and everything
       falls back to env/.env/field defaults.
    """
    override = os.environ.get(CONFIG_FILE_ENV_VAR, "").strip()
    if override:
        path = Path(override)
        if not path.is_file():
            raise ConfigError(
                f"{CONFIG_FILE_ENV_VAR} points at {path}, but that file does not exist."
            )
        return path
    root = resolve_project_root()
    if root is None:
        return None
    default = root / DEFAULT_CONFIG_FILENAME
    return default if default.is_file() else None


def resolve_env_file() -> Path | None:
    """Locate the .env file: ``<application root>/.env`` when it exists.

    Used by Settings (to point the dotenv layer at it) and by the Jinja
    env() helper (as its snapshot fallback) — one resolution rule, so both
    layers always read the same file.
    """
    root = resolve_project_root()
    if root is None:
        return None
    candidate = root / ENV_FILENAME
    return candidate if candidate.is_file() else None


def _make_env_helper(dotenv: Mapping[str, str | None], source_file: Path, env_file: Path | None):
    """Build the ``env(name, default=None)`` helper exposed to templates.

    Resolution order mirrors the layering above: process environment first,
    then the resolved .env snapshot, then the template-supplied default.
    Missing without a default raises ConfigError naming the variable — the
    fail-fast path for required inputs that have no sane universal default.
    """

    def env(name: str, default: Any = None) -> Any:
        value = os.environ.get(name)
        if value is None:
            value = dotenv.get(name)
        if value is None:
            if default is None:
                raise ConfigError(
                    f"{source_file}: env({name!r}) has no value - set {name} in the "
                    f"environment or in {env_file or 'the project .env'}, "
                    "or pass a default in the template."
                )
            return default
        return value

    return env


# Extension point: everything in this dict becomes a Jinja global available
# to app.yaml. Keep entries deterministic and side-effect free — rendering
# happens once per Settings instantiation, at startup.
JINJA_GLOBALS: dict[str, Any] = {}


class JinjaYamlSource(YamlConfigSettingsSource):
    """YAML settings source that renders the file as a Jinja2 template first.

    Overrides exactly one seam — ``_read_file(path) -> dict`` — which the
    parent calls for each existing configured file; everything else (file
    discovery, merging, feeding values into the pydantic core) remains stock
    pydantic-settings behavior. Missing files are skipped by the parent
    before ``_read_file`` is ever called, so ``yaml_file=None`` (or a path
    that does not exist at the default location) simply yields no values.

    ``_read_file`` is a private (underscore) API, which is why pyproject pins
    ``pydantic-settings>=2.16,<3`` and why tests/test_config.py exercises this
    class end to end: if an upgrade ever moves the seam, tests fail loudly
    here instead of the YAML layer silently deactivating.
    """

    def __init__(self, settings_cls: type, yaml_file: Path | None = None, **kwargs: Any) -> None:
        # Resolve the .env and snapshot its values once per instantiation so
        # the Jinja env() helper sees the same file the dotenv settings source
        # would (without depending on load order between sources). Both must
        # happen before super().__init__, which reads the YAML file during
        # construction. Empty snapshot when there is no .env — passing None to
        # python-dotenv would instead trigger its own search, a second and
        # subtly different discovery rule.
        self._env_file = resolve_env_file()
        self._dotenv_snapshot: Mapping[str, str | None] = (
            dotenv_values(self._env_file) if self._env_file is not None else {}
        )
        super().__init__(settings_cls, yaml_file=yaml_file, **kwargs)

    def _read_file(self, file_path: Path) -> dict[str, Any]:
        path = Path(file_path)
        try:
            text = path.read_text(encoding="utf-8")
        except OSError as exc:
            raise ConfigError(f"Cannot read config file {path}: {exc}") from exc

        environment = SandboxedEnvironment(undefined=StrictUndefined)
        environment.globals.update(JINJA_GLOBALS)
        environment.globals["env"] = _make_env_helper(self._dotenv_snapshot, path, self._env_file)

        try:
            rendered = environment.from_string(text).render()
        except TemplateError as exc:
            raise ConfigError(f"Jinja2 rendering of {path} failed: {exc}") from exc
        # A ConfigError raised by the env() helper is NOT a TemplateError and
        # propagates untouched — it already carries the file and variable.

        try:
            data = yaml.safe_load(rendered)
        except yaml.YAMLError as exc:
            raise ConfigError(f"YAML parse of {path} failed after Jinja2 rendering: {exc}") from exc

        if data is None:  # empty file, or comments only
            return {}
        if not isinstance(data, dict):
            raise ConfigError(
                f"{path}: top level must be a YAML mapping of Settings field names, "
                f"got {type(data).__name__}."
            )
        return data
