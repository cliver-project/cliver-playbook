"""Layered configuration: the Jinja2-rendered app.yaml tier under env/.env.

Every test constructs ``Settings()`` directly against a temporary YAML file
via the ``$CLIVER_CONFIG_FILE`` override — the process runtime (settings
binding, engine) established by the conftest is untouched. The real
project .env is neutralized with ``_env_file=None`` unless a test explicitly
opts in, so results never depend on stray local dotenv files.
"""

import pytest

from cliver_playbook.app.basic import config_yaml
from cliver_playbook.app.basic.config_yaml import ConfigError
from cliver_playbook.app.basic.settings import Settings


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
    # Hermetic by default: ignore any real project .env unless the test passes
    # its own _env_file.
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

    # The helper also falls back to the resolved .env snapshot: patch the
    # resolver the source calls and drop the process env value.
    dotenv = tmp_path / ".env"
    dotenv.write_text("TESTCFG_NAME=fromdotenv\nTESTCFG_SUFFIX=s1\n", encoding="utf-8")
    monkeypatch.setattr(config_yaml, "resolve_env_file", lambda: dotenv)
    monkeypatch.delenv("TESTCFG_NAME", raising=False)
    assert _settings().app_name == "fromdotenv-s1"


def test_env_file_and_app_yaml_discovered_by_walking_up(tmp_path, monkeypatch):
    """Default construction discovers the project root from the CWD.

    Nothing is patched here beyond moving into a nested directory: the .env
    and app.yaml layers resolve through the real walk-up logic, which is what
    an installed package relies on to find its consuming project's config.
    """
    root = tmp_path / "project"
    nested = root / "packages" / "app"
    nested.mkdir(parents=True)
    (root / "app.yaml").write_text("app_name: walk-up-app\n", encoding="utf-8")
    (root / ".env").write_text("CLIVER_LOG_LEVEL=DEBUG\n", encoding="utf-8")

    monkeypatch.delenv("CLIVER_APP_NAME", raising=False)
    monkeypatch.delenv("CLIVER_LOG_LEVEL", raising=False)
    monkeypatch.delenv(config_yaml.CONFIG_FILE_ENV_VAR, raising=False)
    monkeypatch.chdir(nested)

    s = Settings()
    assert s.app_name == "walk-up-app"  # app.yaml at the discovered root
    assert s.log_level == "DEBUG"  # .env at the discovered root


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
