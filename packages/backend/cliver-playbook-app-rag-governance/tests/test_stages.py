"""Stage registries, offline stages and approval policies.

The masking tests pin the two failure modes that matter most: a
sensitive value surviving into stored text, and an 18-digit resident ID
being counted as a bank card after it was already masked.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from pydantic import BaseModel

from cliver_playbook.app.rag_governance.stages import (
    ApprovalContext,
    AutoApprovalPolicy,
    ByExtensionClassifier,
    ByMimeClassifier,
    HybridApprovalPolicy,
    ManualApprovalPolicy,
    MaskerOptions,
    RegexPiiMasker,
    Registry,
    SectionPathContextualizer,
    SourceDocument,
    approval_policies,
    cleaners,
    contextualizers,
    maskers,
    type_classifiers,
)
from cliver_playbook.app.rag_governance.stages.contextualizer import ContextualizerOptions


def test_registry_rejects_duplicate_names() -> None:
    reg: Registry[object] = Registry("cleaner")
    reg.register("x", lambda: object())
    with pytest.raises(ValueError):
        reg.register("x", lambda: object())


def test_registry_get_names_an_unknown_stage() -> None:
    reg: Registry[object] = Registry("cleaner")
    with pytest.raises(KeyError, match="unknown cleaner"):
        reg.get("missing")


def test_regex_masker_masks_phone_email_and_id() -> None:
    report = RegexPiiMasker().mask(
        "call 13800138000 or mail a@b.com, id 110101199001011234",
        options=MaskerOptions(),
    )
    assert "13800138000" not in report.text
    assert "a@b.com" not in report.text
    assert "110101199001011234" not in report.text
    assert report.counts["phone"] == 1
    assert report.counts["email"] == 1
    assert report.counts["cn_id"] == 1
    # The ID pass runs before the card pass; the card pass must not
    # double-count the digits the ID pass already replaced.
    assert report.counts["bank_card"] == 0


def test_regex_masker_masks_a_bank_card() -> None:
    report = RegexPiiMasker().mask("card 6222 0212 3456 7890", options=MaskerOptions())
    assert "6222" not in report.text
    assert report.counts["bank_card"] == 1


def test_regex_masker_honors_the_selected_patterns() -> None:
    report = RegexPiiMasker().mask(
        "call 13800138000 or mail a@b.com",
        options=MaskerOptions(patterns=["phone"]),
    )
    assert report.counts == {"phone": 1}
    assert "a@b.com" in report.text


def test_section_path_contextualizer_prefixes_the_path() -> None:
    text = SectionPathContextualizer().contextualize(
        document=SourceDocument(
            source_uri="fin.md",
            title="Finance",
            mime_type="text/markdown",
            content=b"# Scope\nbody",
        ),
        chunk="body",
        options=ContextualizerOptions(section_path="H2#Scope"),
    )
    assert text.startswith("H2#Scope")
    assert text.endswith("body")


def test_section_path_contextualizer_without_a_path_is_unchanged() -> None:
    text = SectionPathContextualizer().contextualize(
        document=SourceDocument("fin.md", "Finance", "text/markdown", b"body"),
        chunk="body",
    )
    assert text == "body"


def test_offline_classifiers_use_mime_and_filename() -> None:
    markdown = SourceDocument("notes.md", "Notes", "text/markdown", b"# A")
    unknown = SourceDocument("blob.bin", "Blob", "application/octet-stream", b"\x00")
    assert ByMimeClassifier().classify(markdown) == "markdown"
    assert ByMimeClassifier().classify(unknown) == "unknown"
    assert ByExtensionClassifier().classify(markdown) == "markdown"
    assert ByExtensionClassifier().classify(unknown) == "unknown"


def test_builtin_registries_are_populated_and_offer_options_models() -> None:
    assert cleaners.names() == ["passthrough"]
    assert maskers.names() == ["regex-pii"]
    assert type_classifiers.names() == ["by-extension", "by-mime"]
    assert contextualizers.names() == ["section-path"]
    assert approval_policies.names() == ["auto", "hybrid", "manual"]

    for registry in (cleaners, maskers, type_classifiers, contextualizers):
        for name in registry.names():
            stage = registry.get(name)
            assert stage.name == name
            assert stage.version
            assert issubclass(stage.options_model, BaseModel)


def test_manual_policy_requires_a_decision_only_while_in_review() -> None:
    policy = ManualApprovalPolicy()
    project = SimpleNamespace()
    assert policy.requires_approval(project, SimpleNamespace(status="staged"))
    assert policy.requires_approval(project, SimpleNamespace(status="review_pending"))
    assert not policy.requires_approval(project, SimpleNamespace(status="published"))


def test_auto_policy_follows_the_hard_gates() -> None:
    policy = AutoApprovalPolicy()
    project, batch = SimpleNamespace(), SimpleNamespace(status="staged")
    assert not policy.requires_approval(
        project, batch, context=ApprovalContext(hard_gates_passed=True)
    )
    assert policy.requires_approval(
        project, batch, context=ApprovalContext(hard_gates_passed=False)
    )


def test_hybrid_policy_reviews_first_loads_and_changes_only() -> None:
    policy = HybridApprovalPolicy()
    project, batch = SimpleNamespace(), SimpleNamespace(status="staged")
    assert policy.requires_approval(project, batch, context=ApprovalContext(is_first_batch=True))
    assert policy.requires_approval(project, batch, context=ApprovalContext(rules_changed=True))
    assert policy.requires_approval(project, batch, context=ApprovalContext(soft_regression=True))
    assert not policy.requires_approval(project, batch, context=ApprovalContext())
