"""OIDC provider-registry configuration: validation + normalization.

Complements the basic package's ``tests/test_config.py``, which covers the
layering mechanism itself (the same code, since ``Settings`` inherits it) —
these cover the OIDC registry model this package adds on top.

Like test_config.py, every test constructs ``Settings()`` directly against a
temporary YAML file via ``$CLIVER_CONFIG_FILE``; the running app, the
``settings`` singleton, and the conftest migrations are untouched.
"""

import pytest
from pydantic import ValidationError

from cliver_playbook.app.basic import config_yaml
from cliver_playbook.app.user.settings import Settings


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


def _enabled_provider(extra: str = "", *, oidc_extra: str = "") -> str:
    """YAML for one enabled ``acme`` provider with credentials.

    ``extra`` appends provider fields (indented six spaces); ``oidc_extra``
    appends fields directly under the ``oidc:`` block.
    """
    return (
        "oidc:\n"
        f"{oidc_extra}"
        "  providers:\n"
        "    acme:\n"
        "      enabled: true\n"
        "      client_id: x\n"
        "      client_secret: y\n"
        f"{extra}"
    )


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


def test_provider_brand_metadata_is_normalized(yaml_file):
    yaml_file(
        _enabled_provider(
            "      issuer: https://idp.example.com\n"
            "      icon: /icons/acme.svg\n"
            '      brand_color: "#123abc"\n'
            "      labels:\n"
            "        EN: Acme Corp\n"
            "        zh-CN: 艾克米\n"
        )
    )
    provider = _settings().oidc.providers["acme"]
    # Locale keys are folded to lowercase so env overrides and lookups agree.
    assert provider.labels == {"en": "Acme Corp", "zh-cn": "艾克米"}
    assert provider.icon == "/icons/acme.svg"
    assert provider.brand_color == "#123abc"


def test_provider_labels_reject_empty_locale_or_text(yaml_file):
    yaml_file(
        _enabled_provider(
            "      issuer: https://idp.example.com\n      labels:\n        '': Acme\n"
        )
    )
    with pytest.raises(ValidationError, match="non-empty"):
        _settings()
    yaml_file(
        _enabled_provider("      issuer: https://idp.example.com\n      labels:\n        en: ''\n")
    )
    with pytest.raises(ValidationError, match="non-empty"):
        _settings()


def test_provider_registry_copies_brand_metadata(yaml_file, monkeypatch):
    from cliver_playbook.app.user.auth import oidc

    yaml_file(
        _enabled_provider(
            "      issuer: https://idp.example.com\n"
            "      icon: /icons/acme.svg\n"
            '      brand_color: "#123abc"\n'
            "      labels:\n"
            "        en: Acme Corp\n"
            "        zh: 艾克米\n"
        )
    )
    settings = _settings()
    monkeypatch.setattr(oidc, "get_settings", lambda: settings)
    config = oidc.build_provider_registry()["acme"]
    assert config.labels == {"en": "Acme Corp", "zh": "艾克米"}
    assert config.icon == "/icons/acme.svg"
    assert config.brand_color == "#123abc"


def test_http_timeout_defaults_and_must_be_positive(yaml_file):
    """The default outbound client's timeout is settings-controlled."""
    yaml_file("oidc:\n  providers: {}\n")
    assert _settings().oidc.http_timeout_seconds == 10.0
    yaml_file("oidc:\n  http_timeout_seconds: 0\n  providers: {}\n")
    with pytest.raises(ValidationError, match="greater than 0"):
        _settings()


def test_adapter_provider_needs_credentials_but_no_endpoints(yaml_file):
    """An adapter owns the protocol: no issuer and no endpoint URLs required."""
    yaml_file(
        "oidc:\n"
        "  providers:\n"
        "    wechat:\n"
        "      enabled: true\n"
        "      adapter: wechat\n"
        "      client_id: appid\n"
        "      client_secret: secret\n"
    )
    settings = _settings()
    assert settings.oidc.providers["wechat"].adapter == "wechat"


def test_adapter_provider_still_requires_credentials(yaml_file):
    yaml_file("oidc:\n  providers:\n    wechat:\n      enabled: true\n      adapter: wechat\n")
    with pytest.raises(ValidationError, match="client_id"):
        _settings()


def test_provider_registry_copies_adapter(yaml_file, monkeypatch):
    from cliver_playbook.app.user.auth import oidc

    yaml_file(
        "oidc:\n"
        "  providers:\n"
        "    wechat:\n"
        "      enabled: true\n"
        "      adapter: wechat\n"
        "      client_id: appid\n"
        "      client_secret: secret\n"
    )
    settings = _settings()
    monkeypatch.setattr(oidc, "get_settings", lambda: settings)
    registry = oidc.build_provider_registry()
    assert registry["wechat"].adapter == "wechat"


def test_provider_registry_rejects_unknown_adapter(yaml_file, monkeypatch):
    from cliver_playbook.app.user.auth import oidc

    yaml_file(
        "oidc:\n"
        "  providers:\n"
        "    bad:\n"
        "      enabled: true\n"
        "      adapter: no-such-adapter\n"
        "      client_id: appid\n"
        "      client_secret: secret\n"
        "      issuer: https://idp.example.com\n"
    )
    settings = _settings()
    monkeypatch.setattr(oidc, "get_settings", lambda: settings)
    with pytest.raises(ValueError, match="unknown adapter"):
        oidc.build_provider_registry()


def test_token_endpoint_auth_defaults_and_public_client(yaml_file):
    yaml_file(_enabled_provider("      issuer: https://idp.example.com\n"))
    provider = _settings().oidc.providers["acme"]
    assert provider.token_endpoint_auth_method == "client_secret_post"
    assert provider.token_extra_params == {}

    # A public client authenticates with `none`: no secret is required.
    yaml_file(
        "oidc:\n"
        "  providers:\n"
        "    acme:\n"
        "      enabled: true\n"
        "      client_id: x\n"
        "      token_endpoint_auth_method: none\n"
        "      issuer: https://idp.example.com\n"
    )
    provider = _settings().oidc.providers["acme"]
    assert provider.token_endpoint_auth_method == "none"
    assert provider.client_secret == ""


def test_client_secret_required_unless_auth_method_is_none(yaml_file):
    yaml_file(
        "oidc:\n"
        "  providers:\n"
        "    acme:\n"
        "      enabled: true\n"
        "      client_id: x\n"
        "      token_endpoint_auth_method: client_secret_basic\n"
        "      issuer: https://idp.example.com\n"
    )
    with pytest.raises(ValidationError, match="client_secret"):
        _settings()


def test_token_endpoint_auth_method_is_validated(yaml_file):
    yaml_file(
        _enabled_provider(
            "      issuer: https://idp.example.com\n"
            "      token_endpoint_auth_method: private_key_jwt\n"
        )
    )
    with pytest.raises(ValidationError, match="token_endpoint_auth_method"):
        _settings()


def test_token_extra_params_cannot_override_protocol_fields(yaml_file):
    yaml_file(
        _enabled_provider(
            "      issuer: https://idp.example.com\n"
            "      token_extra_params:\n"
            "        grant_type: password\n"
        )
    )
    with pytest.raises(ValidationError, match="token_extra_params"):
        _settings()


def test_enabled_endpoint_urls_require_https(yaml_file):
    yaml_file(_enabled_provider("      issuer: http://idp.example.com\n"))
    with pytest.raises(ValidationError, match="must use https"):
        _settings()

    # Explicit-endpoint providers go through the same check.
    yaml_file(
        _enabled_provider(
            "      authorize_url: https://idp.example.com/authorize\n"
            "      token_url: http://idp.example.com/token\n"
            "      userinfo_url: https://idp.example.com/userinfo\n"
        )
    )
    with pytest.raises(ValidationError, match="must use https"):
        _settings()


def test_insecure_endpoints_require_explicit_opt_in(yaml_file):
    yaml_file(
        _enabled_provider(
            "      issuer: http://127.0.0.1:9000\n",
            oidc_extra="  allow_insecure_endpoints: true\n",
        )
    )
    assert _settings().oidc.providers["acme"].issuer == "http://127.0.0.1:9000"


def test_endpoint_urls_must_be_absolute_http(yaml_file):
    for issuer in ("idp.example.com", "ftp://idp.example.com"):
        yaml_file(_enabled_provider(f"      issuer: {issuer}\n"))
        with pytest.raises(ValidationError, match="absolute http"):
            _settings()


def test_disabled_provider_may_keep_http_preset(yaml_file):
    yaml_file(
        "oidc:\n"
        "  providers:\n"
        "    acme:\n"
        "      enabled: false\n"
        "      issuer: http://idp.example.com\n"
    )
    assert _settings().oidc.providers["acme"].enabled is False


def test_adapter_provider_ignores_unused_endpoint_urls(yaml_file):
    """The adapter owns the wire protocol; issuer/endpoint fields are unused."""
    yaml_file(
        "oidc:\n"
        "  providers:\n"
        "    wechat:\n"
        "      enabled: true\n"
        "      adapter: wechat\n"
        "      client_id: appid\n"
        "      client_secret: secret\n"
        "      issuer: http://unused.example.com\n"
    )
    assert _settings().oidc.providers["wechat"].adapter == "wechat"


def test_provider_registry_copies_token_request_settings(yaml_file, monkeypatch):
    from cliver_playbook.app.user.auth import oidc

    yaml_file(
        _enabled_provider(
            "      issuer: https://idp.example.com\n"
            "      token_endpoint_auth_method: client_secret_basic\n"
            "      token_extra_params:\n"
            "        audience: https://api.example.com\n"
        )
    )
    settings = _settings()
    monkeypatch.setattr(oidc, "get_settings", lambda: settings)
    config = oidc.build_provider_registry()["acme"]
    assert config.token_endpoint_auth_method == "client_secret_basic"
    assert config.token_extra_params == {"audience": "https://api.example.com"}
