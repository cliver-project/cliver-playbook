"""Stage registries and the built-in offline implementations.

Importing this module registers every built-in exactly once. A project
that needs a different implementation registers it under a new name;
it never monkey-patches a built-in, because names are the config
surface and two deployments must be able to tell their stacks apart.
"""

from cliver_playbook.app.rag_governance.stages.approval import (
    ApprovalContext,
    AutoApprovalPolicy,
    HybridApprovalPolicy,
    ManualApprovalPolicy,
)
from cliver_playbook.app.rag_governance.stages.base import (
    ApprovalPolicy,
    CleanedText,
    Cleaner,
    Contextualizer,
    Evaluator,
    IntentClassifier,
    IntentMatch,
    Masker,
    MaskingReport,
    Source,
    SourceDocument,
    TypeClassifier,
)
from cliver_playbook.app.rag_governance.stages.classifier import (
    ByExtensionClassifier,
    ByMimeClassifier,
)
from cliver_playbook.app.rag_governance.stages.cleaner import PassthroughCleaner
from cliver_playbook.app.rag_governance.stages.contextualizer import SectionPathContextualizer
from cliver_playbook.app.rag_governance.stages.masker import MaskerOptions, RegexPiiMasker
from cliver_playbook.app.rag_governance.stages.registry import Registry
from cliver_playbook.app.rag_governance.stages.source import DirectorySource, UploadSource

cleaners: Registry[Cleaner] = Registry("cleaner")
maskers: Registry[Masker] = Registry("masker")
type_classifiers: Registry[TypeClassifier] = Registry("document type classifier")
contextualizers: Registry[Contextualizer] = Registry("contextualizer")
sources: Registry[Source] = Registry("source")
intent_classifiers: Registry[IntentClassifier] = Registry("intent classifier")
approval_policies: Registry[ApprovalPolicy] = Registry("approval policy")

cleaners.register(PassthroughCleaner.name, PassthroughCleaner)
maskers.register(RegexPiiMasker.name, RegexPiiMasker)
type_classifiers.register(ByMimeClassifier.name, ByMimeClassifier)
type_classifiers.register(ByExtensionClassifier.name, ByExtensionClassifier)
contextualizers.register(SectionPathContextualizer.name, SectionPathContextualizer)
sources.register(UploadSource.name, UploadSource)
sources.register(DirectorySource.name, DirectorySource)
approval_policies.register(ManualApprovalPolicy.name, ManualApprovalPolicy)
approval_policies.register(AutoApprovalPolicy.name, AutoApprovalPolicy)
approval_policies.register(HybridApprovalPolicy.name, HybridApprovalPolicy)

__all__ = [
    "ApprovalContext",
    "ApprovalPolicy",
    "AutoApprovalPolicy",
    "ByExtensionClassifier",
    "ByMimeClassifier",
    "CleanedText",
    "Cleaner",
    "Contextualizer",
    "DirectorySource",
    "Evaluator",
    "HybridApprovalPolicy",
    "IntentClassifier",
    "IntentMatch",
    "ManualApprovalPolicy",
    "Masker",
    "MaskerOptions",
    "MaskingReport",
    "PassthroughCleaner",
    "RegexPiiMasker",
    "Registry",
    "SectionPathContextualizer",
    "Source",
    "SourceDocument",
    "TypeClassifier",
    "UploadSource",
    "approval_policies",
    "cleaners",
    "contextualizers",
    "intent_classifiers",
    "maskers",
    "sources",
    "type_classifiers",
]
