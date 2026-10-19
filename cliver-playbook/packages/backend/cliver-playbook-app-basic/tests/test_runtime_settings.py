"""Structural rules of the module-owned runtime-settings framework.

These are pure unit tests: they pin the field/section invariants and the
audit redaction without touching a database or a bound runtime.
"""

from __future__ import annotations

import pytest

from cliver_playbook.app.basic.runtime_settings import (
    SettingsField,
    SettingsSection,
    redact_values,
)


def _field(**overrides) -> SettingsField:
    values = {"name": "model", "label": "Model"}
    values.update(overrides)
    return SettingsField(**values)


def _section(*fields: SettingsField) -> SettingsSection:
    return SettingsSection(
        key="demo",
        title="Demo",
        description="",
        fields=lambda: fields,
        read=lambda settings: {},
        apply=lambda settings, values: None,
    )


def test_grouped_fields_require_a_title() -> None:
    field = _field(group="cliver-core", group_title="cliver-core model access")
    assert field.group == "cliver-core"

    with pytest.raises(ValueError, match="group_title"):
        _field(group="cliver-core")
    with pytest.raises(ValueError, match="group_title requires a group"):
        _field(group_title="Orphan heading")
    with pytest.raises(ValueError, match="invalid group key"):
        _field(group="Not A Key", group_title="Bad")


def test_subgroups_nest_inside_a_group() -> None:
    field = _field(
        group="cliver-core",
        group_title="cliver-core model access",
        subgroup="llm",
        subgroup_title="LLM",
    )
    assert field.subgroup == "llm"

    with pytest.raises(ValueError, match="subgroup requires a group"):
        _field(subgroup="llm", subgroup_title="LLM")
    with pytest.raises(ValueError, match="subgroup_title"):
        _field(group="cliver-core", group_title="Group", subgroup="llm")
    with pytest.raises(ValueError, match="subgroup_title requires a subgroup"):
        _field(group="cliver-core", group_title="Group", subgroup_title="Orphan")
    with pytest.raises(ValueError, match="invalid subgroup key"):
        _field(
            group="cliver-core",
            group_title="Group",
            subgroup="Not A Key",
            subgroup_title="Bad",
        )


def test_a_secret_may_declare_its_environment_variable_or_not() -> None:
    # The environment variable is the opt-out from database storage, not a
    # requirement: a section may expose a purely settings-stored credential.
    assert _field(secret=True).env_var is None
    assert _field(secret=True, env_var="CLIVER_DEMO__MODEL").env_var


def test_section_rejects_duplicate_field_names() -> None:
    with pytest.raises(ValueError, match="duplicate field names"):
        _section(_field(), _field())


def test_redact_values_masks_only_secret_fields() -> None:
    section = _section(
        _field(name="api_key", label="API key", secret=True),
        _field(name="model", label="Model"),
    )

    assert redact_values(section, {"api_key": "sk-secret", "model": "m"}) == {
        "api_key": "<redacted>",
        "model": "m",
    }
    assert redact_values(section, {"api_key": ""}) == {"api_key": ""}
