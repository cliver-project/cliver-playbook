"""OIDC provider-registry configuration: validation + normalization.

Complements tests/test_config.py, which covers the scaffold-shared layering
mechanism and stays byte-identical across templates (drift discipline) —
hence these template-specific tests live in their own module.

Like test_config.py, every test constructs ``Settings()`` directly against a
temporary YAML file via ``$CLIVER_CONFIG_FILE``; the running app, the
``settings`` singleton, and the conftest migrations are untouched.
"""

import pytest
from pydantic import ValidationError

from app.core import config_yaml
from app.core.config import Settings


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
    # Hermetic by default: ignore any real project-root .env.
    kwargs.setdefault("_env_file", None)
    return Settings(**kwargs)


def test_enabled_provider_requires_credentials_and_endpoints(yaml_file):
    # Enabled but bare: missing client credentials.
    yaml_file("oidc:\n  providers:\n    acme:\n      enabled: true\n")
    with pytest.raises(ValidationError, match="client_id"):
        _settings()
    # Credentials present, but neither issuer nor explicit endpoints.
    yaml_file(
        "oidc:\n"
        "  providers:\n"
        "    acme:\n"
        "      enabled: true\n"
        "      client_id: x\n"
        "      client_secret: y\n"
    )
    with pytest.raises(ValidationError, match="issuer"):
        _settings()
    # The same provider disabled is perfectly valid (shipped-preset shape).
    yaml_file("oidc:\n  providers:\n    acme:\n      enabled: false\n")
    assert _settings().oidc.providers["acme"].enabled is False


def test_provider_keys_are_lowercased_and_merged(yaml_file, monkeypatch):
    # Env-sourced dict keys arrive lowercased; YAML preserves author casing.
    # Both must land on the SAME provider entry, not split into two.
    yaml_file("oidc:\n  providers:\n    Google:\n      label: Google\n")
    monkeypatch.setenv("CLIVER_OIDC__PROVIDERS__GOOGLE__CLIENT_ID", "gid")
    s = _settings()
    assert list(s.oidc.providers) == ["google"]
    assert s.oidc.providers["google"].label == "Google"  # yaml part survived
    assert s.oidc.providers["google"].client_id == "gid"  # env part merged in
    # Scalar conflict between layers: the higher-priority env value wins.
    monkeypatch.setenv("CLIVER_OIDC__PROVIDERS__GOOGLE__LABEL", "GoogleEnv")
    assert _settings().oidc.providers["google"].label == "GoogleEnv"


def test_reserved_and_invalid_provider_keys_rejected(yaml_file):
    yaml_file("oidc:\n  providers:\n    authorize:\n      label: x\n")
    with pytest.raises(ValidationError, match="reserved"):
        _settings()
    # Spaces (even after lowercasing) are not URL-segment safe.
    yaml_file("oidc:\n  providers:\n    Bad Key:\n      label: x\n")
    with pytest.raises(ValidationError, match="invalid"):
        _settings()


def test_scopes_accepts_yaml_list_or_string(yaml_file):
    yaml_file("oidc:\n  providers:\n    acme:\n      scopes: [read:user, user:email]\n")
    assert _settings().oidc.providers["acme"].scopes == "read:user user:email"
    yaml_file("oidc:\n  providers:\n    acme:\n      scopes: openid profile\n")
    assert _settings().oidc.providers["acme"].scopes == "openid profile"
