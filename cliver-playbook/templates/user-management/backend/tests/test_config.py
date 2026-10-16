"""Layered configuration: the Jinja2-rendered app.yaml tier under env/.env.

Every test constructs ``Settings()`` directly against a temporary YAML file
via the ``$CLIVER_CONFIG_FILE`` override — the module-level ``settings``
singleton, the import-time-bound engine, and the conftest migrations are all
untouched. The real project-root .env is neutralized with ``_env_file=None``
unless a test explicitly opts in, so results never depend on stray local
dotenv files.
"""

import pytest

from app.core import config_yaml
from app.core.config import Settings
from app.core.config_yaml import ConfigError


@pytest.fixture
def yaml_file(tmp_path, monkeypatch):
    """Write a temp app.yaml and point $CLIVER_CONFIG_FILE at it."""

    def _write(content: str):
        path = tmp_path / "app.yaml"
        path.write_text(content, encoding="utf-8")
        monkeypatch.setenv(config_yaml.CONFIG_FILE_ENV_VAR, str(path))
        return path

    return _write


def _settings(**kwargs) -> Settings:
    # Hermetic by default: ignore any real project-root .env unless the test
    # passes its own _env_file.
    kwargs.setdefault("_env_file", None)
    return Settings(**kwargs)


def test_yaml_fills_values_but_env_wins(yaml_file, monkeypatch):
    # conftest exports CLIVER_DATABASE_URL (the temp test database): the YAML
    # layer must NOT be able to hijack it — env sits above yaml.
    yaml_file("app_name: yaml-app\ndatabase_url: postgresql://yaml-host/yamldb\n")
    monkeypatch.delenv("CLIVER_APP_NAME", raising=False)
    s = _settings()
    assert s.app_name == "yaml-app"  # yaml beats the field default
    assert "yaml-host" not in s.database_url  # env beats yaml


def test_layer_order_env_over_dotenv_over_yaml(yaml_file, tmp_path, monkeypatch):
    yaml_file("log_level: from-yaml\n")
    dotenv = tmp_path / ".env"
    dotenv.write_text("CLIVER_LOG_LEVEL=from-dotenv\n", encoding="utf-8")
    monkeypatch.delenv("CLIVER_LOG_LEVEL", raising=False)
    assert _settings(_env_file=dotenv).log_level == "from-dotenv"
    monkeypatch.setenv("CLIVER_LOG_LEVEL", "from-env")
    assert _settings(_env_file=dotenv).log_level == "from-env"


def test_jinja_env_helper_composes_from_env_and_dotenv(yaml_file, tmp_path, monkeypatch):
    yaml_file("app_name: {{ env('TESTCFG_NAME') }}-{{ env('TESTCFG_SUFFIX', 'default-suffix') }}\n")
    monkeypatch.setenv("TESTCFG_NAME", "live")
    monkeypatch.delenv("TESTCFG_SUFFIX", raising=False)
    assert _settings().app_name == "live-default-suffix"

    # The helper also falls back to the project-root .env snapshot: patch the
    # module-level path the source reads and drop the process env value.
    dotenv = tmp_path / ".env"
    dotenv.write_text("TESTCFG_NAME=fromdotenv\nTESTCFG_SUFFIX=s1\n", encoding="utf-8")
    monkeypatch.setattr(config_yaml, "_ENV_FILE", dotenv)
    monkeypatch.delenv("TESTCFG_NAME", raising=False)
    assert _settings().app_name == "fromdotenv-s1"


def test_jinja_required_variable_missing_raises(yaml_file):
    path = yaml_file("app_name: {{ env('TESTCFG_DEFINITELY_UNSET') }}\n")
    with pytest.raises(ConfigError) as excinfo:
        _settings()
    message = str(excinfo.value)
    assert "TESTCFG_DEFINITELY_UNSET" in message  # names the variable
    assert str(path) in message  # and the file that referenced it


def test_broken_yaml_raises_config_error_naming_file(yaml_file):
    path = yaml_file('app_name: "unclosed\nlog_level: DEBUG\n')
    with pytest.raises(ConfigError) as excinfo:
        _settings()
    assert str(path) in str(excinfo.value)


def test_explicit_config_file_must_exist(tmp_path, monkeypatch):
    monkeypatch.setenv(config_yaml.CONFIG_FILE_ENV_VAR, str(tmp_path / "missing.yaml"))
    with pytest.raises(ConfigError, match="does not exist"):
        _settings()
