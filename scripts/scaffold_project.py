#!/usr/bin/env python3
"""Plan an AI-native project from a scaffold manifest.

Phase 0 is deliberately dry-run only: the planner resolves and validates the
module set and prints what a future `--apply` will create. No files are
generated yet.

Usage:
    uv run --with pyyaml --with jsonschema python scripts/scaffold_project.py \
        --plan scaffold/examples/ai-web.yaml
    uv run --with pyyaml --with jsonschema python scripts/scaffold_project.py \
        --list-modules
    uv run --with pyyaml --with jsonschema python scripts/scaffold_project.py \
        --validate-catalog
    uv run --with pyyaml --with jsonschema python scripts/scaffold_project.py \
        --self-test

Exit status is 0 when the requested operation succeeds. Validation errors are
printed one per line to stderr and exit status is 1.
"""

from __future__ import annotations

import argparse
import contextlib
import copy
import hashlib
import io
import json
import plistlib
import re
import shutil
import subprocess
import sys
import tempfile
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml
from jinja2 import Environment, StrictUndefined, TemplateError
from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError

ROOT = Path(__file__).resolve().parent.parent
CATALOG_PATH = ROOT / "scaffold" / "catalog.yaml"
SCHEMA_PATH = ROOT / "scaffold" / "schema" / "project-manifest.schema.json"
EXAMPLES_DIR = ROOT / "scaffold" / "examples"
FRAGMENTS_DIR = ROOT / "scaffold" / "fragments"

MODULE_ID = re.compile(r"^[a-z0-9]+(?:\.[a-z0-9_-]+)+$")
MODULE_KINDS = {"ui", "api", "model", "pattern", "contracts", "infra"}
REQUIRED_PROFILES = {"ai-web", "ai-desktop", "ai-mobile", "ai-full", "ai-rust-bff"}
MOBILE_WARNING = "Two native mobile targets are enabled; expect two UI codebases."
RUST_BFF_WARNING = (
    "The Rust API is a BFF; agent runs delegate to the Python AgentCore service."
)
REFERENCE_WARNING = (
    "Reference slices are examples; replace them with the project's domain."
)
MOBILE_DEFAULT_FEATURES = ("auth", "profile", "crud")
MOBILE_DEFAULT_LAYOUTS = ("phone", "pad")

PROFILE_RULES: dict[str, dict[str, Any]] = {
    "ai-web": {
        "web": True,
        "desktop": "none",
        "mobile": "none",
        "api_runtime": "python",
        "api_deployments": {"remote"},
        "model_deployments": {"remote"},
    },
    "ai-desktop": {
        "web": True,
        "desktop": "tauri2",
        "mobile": "none",
        "api_runtime": "python",
        "api_deployments": {"local", "both"},
        "model_deployments": {"local", "both"},
    },
    "ai-mobile": {
        "web": False,
        "desktop": "none",
        "mobile": "one",
        "api_runtime": "python",
        "api_deployments": {"remote"},
        "model_deployments": {"remote"},
    },
    "ai-full": {
        "web": True,
        "desktop": "tauri2",
        "mobile": "at_least_one",
        "api_runtime": "python",
        "api_deployments": {"both"},
        "model_deployments": {"both"},
    },
    "ai-rust-bff": {
        "web": True,
        "desktop": "none",
        "mobile": "none",
        "api_runtime": "rust",
        "api_deployments": {"remote"},
        "model_deployments": {"remote"},
    },
}


class ScaffoldError(Exception):
    """Raised when a manifest cannot be planned."""

    def __init__(self, errors: list[str]) -> None:
        self.errors = errors
        super().__init__("; ".join(errors))


def _read_yaml(path: Path) -> Any:
    try:
        return yaml.safe_load(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise ScaffoldError([f"{path}: {exc}"]) from exc
    except yaml.YAMLError as exc:
        raise ScaffoldError([f"{path}: invalid YAML: {exc}"]) from exc


def load_catalog(path: Path | None = None) -> dict[str, Any]:
    """Load and return the module catalog."""
    catalog_path = path or CATALOG_PATH
    data = _read_yaml(catalog_path)
    if not isinstance(data, Mapping):
        raise ScaffoldError([f"{catalog_path}: catalog must be a mapping"])
    return dict(data)


def load_schema(path: Path | None = None) -> dict[str, Any]:
    """Load and validate the manifest JSON Schema."""
    schema_path = path or SCHEMA_PATH
    try:
        data = json.loads(schema_path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise ScaffoldError([f"{schema_path}: {exc}"]) from exc
    except json.JSONDecodeError as exc:
        raise ScaffoldError([f"{schema_path}: invalid JSON: {exc}"]) from exc
    try:
        Draft202012Validator.check_schema(data)
    except SchemaError as exc:
        raise ScaffoldError(
            [f"{schema_path}: invalid JSON Schema: {exc.message}"]
        ) from exc
    if not isinstance(data, Mapping):
        raise ScaffoldError([f"{schema_path}: schema must be an object"])
    return dict(data)


def load_manifest(path: Path) -> dict[str, Any]:
    """Load a YAML manifest."""
    data = _read_yaml(path)
    if not isinstance(data, Mapping):
        raise ScaffoldError([f"{path}: manifest must be a mapping"])
    return dict(data)


def _string_list(value: Any, where: str, errors: list[str]) -> list[str]:
    if not isinstance(value, list):
        errors.append(f"{where} must be a list")
        return []
    items: list[str] = []
    for index, item in enumerate(value):
        if not isinstance(item, str) or not item.strip():
            errors.append(f"{where}[{index}] must be a non-empty string")
        else:
            items.append(item)
    if len(set(items)) != len(items):
        errors.append(f"{where} contains duplicate entries")
    return items


def _module_closure(
    start: set[str] | list[str], requires: dict[str, list[str]]
) -> set[str]:
    seen: set[str] = set()
    stack = list(start)
    while stack:
        module = stack.pop()
        if module in seen or module not in requires:
            continue
        seen.add(module)
        stack.extend(requires[module])
    return seen


def validate_catalog(catalog: dict[str, Any]) -> list[str]:
    """Return every catalog consistency error."""
    errors: list[str] = []
    if not isinstance(catalog, Mapping):
        return ["catalog must be a mapping"]

    allowed_top = {"version", "modules", "profiles", "selectors"}
    for key in sorted(set(catalog) - allowed_top, key=str):
        errors.append(f"catalog: unknown key {key!r}")
    if catalog.get("version") != 1:
        errors.append("catalog.version must be 1")

    modules = catalog.get("modules")
    if not isinstance(modules, Mapping):
        return errors + ["catalog.modules must be a mapping"]

    module_ids: set[str] = set()
    for module in modules:
        if not isinstance(module, str):
            errors.append(f"catalog.modules: keys must be strings, got {module!r}")
        elif not MODULE_ID.fullmatch(module):
            errors.append(f"catalog.modules: invalid module id {module!r}")
        else:
            module_ids.add(module)

    allowed_module = {
        "kind",
        "description",
        "requires",
        "conflicts",
        "outputs",
        "make_targets",
        "ci",
        "contracts",
    }
    parsed: dict[str, dict[str, list[str]]] = {}
    for module in sorted(module_ids):
        entry = modules[module]
        where = f"modules.{module}"
        if not isinstance(entry, Mapping):
            errors.append(f"{where} must be a mapping")
            continue
        for key in sorted(set(entry) - allowed_module, key=str):
            errors.append(f"{where}: unknown key {key!r}")
        kind = entry.get("kind")
        if kind not in MODULE_KINDS:
            errors.append(
                f"{where}.kind must be one of {sorted(MODULE_KINDS)}, got {kind!r}"
            )
        description = entry.get("description")
        if not isinstance(description, str) or not description.strip():
            errors.append(f"{where}.description must be a non-empty string")
        requires = _string_list(entry.get("requires", []), f"{where}.requires", errors)
        conflicts = _string_list(
            entry.get("conflicts", []), f"{where}.conflicts", errors
        )
        outputs = _string_list(entry.get("outputs", []), f"{where}.outputs", errors)
        _string_list(entry.get("make_targets", []), f"{where}.make_targets", errors)
        if kind == "ui" and not outputs:
            errors.append(f"{where}: ui modules must declare outputs")
        if kind == "pattern" and outputs:
            errors.append(f"{where}: pattern modules must not declare outputs")
        _string_list(entry.get("ci", []), f"{where}.ci", errors)
        _string_list(entry.get("contracts", []), f"{where}.contracts", errors)
        parsed[module] = {"requires": requires, "conflicts": conflicts}

    for module in sorted(parsed):
        for target in parsed[module]["requires"]:
            if target == module:
                errors.append(f"modules.{module}.requires must not include itself")
            elif target not in module_ids:
                errors.append(f"modules.{module}.requires: unknown module {target!r}")
        for target in parsed[module]["conflicts"]:
            if target == module:
                errors.append(f"modules.{module}.conflicts must not include itself")
            elif target not in module_ids:
                errors.append(f"modules.{module}.conflicts: unknown module {target!r}")
        for target in sorted(
            set(parsed[module]["requires"]) & set(parsed[module]["conflicts"])
        ):
            errors.append(
                f"modules.{module}: {target!r} is both required and conflicting"
            )

    profiles = catalog.get("profiles")
    if not isinstance(profiles, Mapping):
        errors.append("catalog.profiles must be a mapping")
        profiles = {}
    profile_modules: dict[str, list[str]] = {}
    for profile in sorted(name for name in profiles if isinstance(name, str)):
        entry = profiles[profile]
        where = f"profiles.{profile}"
        if not isinstance(entry, Mapping):
            errors.append(f"{where} must be a mapping")
            continue
        for key in sorted(set(entry) - {"description", "modules"}, key=str):
            errors.append(f"{where}: unknown key {key!r}")
        description = entry.get("description")
        if not isinstance(description, str) or not description.strip():
            errors.append(f"{where}.description must be a non-empty string")
        selected = _string_list(entry.get("modules", []), f"{where}.modules", errors)
        for module in selected:
            if module not in module_ids:
                errors.append(f"{where}.modules: unknown module {module!r}")
        profile_modules[profile] = selected

    for profile in sorted(set(PROFILE_RULES) ^ set(profile_modules)):
        errors.append(f"profiles: PROFILE_RULES and catalog disagree on {profile!r}")

    selectors = catalog.get("selectors")
    if not isinstance(selectors, Mapping):
        errors.append("catalog.selectors must be a mapping")
        selectors = {}

    referenced: set[str] = set()
    selector_targets: set[str] = set()
    for selected in profile_modules.values():
        referenced.update(selected)
    for selector in sorted(name for name in selectors if isinstance(name, str)):
        if not MODULE_ID.fullmatch(selector):
            errors.append(f"selectors: invalid selector id {selector!r}")
        targets = _string_list(selectors[selector], f"selectors.{selector}", errors)
        for module in targets:
            if module not in module_ids:
                errors.append(f"selectors.{selector}: unknown module {module!r}")
        referenced.update(targets)
        selector_targets.update(targets)

    for module in sorted(module_ids):
        if module not in referenced:
            errors.append(
                f"modules.{module}: not referenced by any profile or selector"
            )

    for profile in sorted(REQUIRED_PROFILES):
        if profile not in profiles:
            errors.append(f"profiles.{profile}: required profile is missing")

    requires = {module: parsed.get(module, {}).get("requires", []) for module in parsed}
    conflicts = {
        module: parsed.get(module, {}).get("conflicts", []) for module in parsed
    }
    required_by_any = {target for targets in requires.values() for target in targets}
    for module in sorted(module_ids):
        if modules[module].get("kind") == "pattern" and (
            module not in selector_targets and module not in required_by_any
        ):
            errors.append(
                f"modules.{module}: pattern must be selected or required by a host module"
            )
    reported: set[str] = set()
    for profile in sorted(profile_modules):
        selected = _module_closure(profile_modules[profile], requires)
        for module in sorted(selected):
            for target in conflicts.get(module, []):
                if target in selected:
                    message = (
                        f"profiles.{profile}: module {module!r} conflicts with "
                        f"{target!r}"
                    )
                    if message not in reported:
                        errors.append(message)
                        reported.add(message)
    for module in sorted(parsed):
        selected = _module_closure([module], requires)
        for member in sorted(selected):
            for target in conflicts.get(member, []):
                if target in selected:
                    message = (
                        f"modules.{module}: closure conflicts between {member!r} "
                        f"and {target!r}"
                    )
                    if message not in reported:
                        errors.append(message)
                        reported.add(message)

    return sorted(set(errors))


def _deployments(value: str) -> set[str]:
    return {"remote", "local"} if value == "both" else {value}


def _mobile_targets(ui: Mapping[str, Any]) -> list[str]:
    return [
        value
        for value in (ui["mobile"]["ios"], ui["mobile"]["android"])
        if value != "none"
    ]


def _mobile_features(ui: Mapping[str, Any], mobile_targets: list[str]) -> list[str]:
    value = ui["mobile"].get("features")
    if value is None:
        return list(MOBILE_DEFAULT_FEATURES) if mobile_targets else []
    return list(value)


def _mobile_layouts(ui: Mapping[str, Any], mobile_targets: list[str]) -> list[str]:
    value = ui["mobile"].get("layouts")
    if value is None:
        return list(MOBILE_DEFAULT_LAYOUTS) if mobile_targets else []
    return list(value)


def _reference_slices(data: Mapping[str, Any]) -> list[str]:
    return list(data["scaffold"].get("reference_slices", []))


def validate_manifest_data(
    data: dict[str, Any], schema: dict[str, Any], catalog: dict[str, Any]
) -> list[str]:
    """Return every schema and profile-rule error for one manifest."""
    if not isinstance(data, Mapping):
        return ["manifest must be a mapping"]

    schema_errors: list[str] = []
    for error in Draft202012Validator(schema).iter_errors(data):
        path = ".".join(str(part) for part in error.absolute_path) or "manifest"
        schema_errors.append(f"{path}: {error.message}")
    if schema_errors:
        return sorted(schema_errors)

    errors: list[str] = []
    profile = data["scaffold"]["profile"]
    if profile not in catalog.get("profiles", {}):
        return [f"scaffold.profile: profile {profile!r} is not in the catalog"]
    rules = PROFILE_RULES.get(profile)
    if rules is None:
        return [f"scaffold.profile: no profile rules for {profile!r}"]

    ui = data["ui"]
    api = data["api"]
    model = data["model"]
    agent = data["agent"]
    release = data["release"]
    mobile_targets = _mobile_targets(ui)
    mobile_features = _mobile_features(ui, mobile_targets)
    mobile_layouts = _mobile_layouts(ui, mobile_targets)
    reference_slices = _reference_slices(data)

    if ui["web"] != rules["web"]:
        errors.append(
            f"ui.web must be {rules['web']} for profile {profile!r}, got {ui['web']}"
        )
    if ui["desktop"] != rules["desktop"]:
        errors.append(
            f"ui.desktop must be {rules['desktop']!r} for profile {profile!r}, "
            f"got {ui['desktop']!r}"
        )

    mobile_rule = rules["mobile"]
    if mobile_rule == "none" and mobile_targets:
        errors.append(f"ui.mobile must be disabled for profile {profile!r}")
    elif mobile_rule == "one" and len(mobile_targets) != 1:
        errors.append(
            f"ui.mobile must enable exactly one target for profile {profile!r}, "
            f"got {len(mobile_targets)}"
        )
    elif mobile_rule == "at_least_one" and not mobile_targets:
        errors.append(
            f"ui.mobile must enable at least one target for profile {profile!r}"
        )

    if not mobile_targets and (
        ui["mobile"].get("features") or ui["mobile"].get("layouts")
    ):
        errors.append(
            "ui.mobile.features and ui.mobile.layouts require a mobile target"
        )
    if mobile_targets and not mobile_layouts:
        errors.append("ui.mobile.layouts must include 'phone' or 'pad'")
    if (
        mobile_targets
        and ("auth" in mobile_features or "profile" in mobile_features)
        and "auth" not in api["features"]
    ):
        errors.append(
            "api.features must include 'auth' when mobile auth or profile is enabled"
        )
    if "products" in reference_slices and api["runtime"] == "rust":
        errors.append("reference slice 'products' requires api.runtime 'python'")

    if api["runtime"] != rules["api_runtime"]:
        errors.append(
            f"api.runtime must be {rules['api_runtime']!r} for profile {profile!r}, "
            f"got {api['runtime']!r}"
        )
    if api["deployment"] not in rules["api_deployments"]:
        errors.append(
            f"api.deployment must be one of {sorted(rules['api_deployments'])} "
            f"for profile {profile!r}, got {api['deployment']!r}"
        )
    if model["deployment"] not in rules["model_deployments"]:
        errors.append(
            f"model.deployment must be one of {sorted(rules['model_deployments'])} "
            f"for profile {profile!r}, got {model['deployment']!r}"
        )

    api_set = _deployments(api["deployment"])
    model_set = _deployments(model["deployment"])
    if ui["desktop"] == "tauri2" and not ui["web"]:
        errors.append("ui.web must be true when ui.desktop is 'tauri2'")
    if "local" in api_set and ui["desktop"] != "tauri2":
        errors.append("api.deployment includes 'local' but ui.desktop is not 'tauri2'")
    if "local" in model_set and ui["desktop"] != "tauri2":
        errors.append(
            "model.deployment includes 'local' but ui.desktop is not 'tauri2'"
        )
    if mobile_targets and "remote" not in api_set:
        errors.append("a mobile target requires api.deployment to include 'remote'")
    if mobile_targets and "remote" not in model_set:
        errors.append("a mobile target requires model.deployment to include 'remote'")
    if "remote" in api_set and "remote" not in model_set:
        errors.append(
            "model.deployment must include 'remote' when api.deployment includes "
            "'remote'"
        )

    if agent["runtime"] == "none":
        if agent["skills"] or agent["mcp"] or agent["system_one"]:
            errors.append(
                "agent.runtime 'none' cannot enable skills, mcp or system_one"
            )
        if "agent" in api["features"]:
            errors.append("api.features includes 'agent' but agent.runtime is 'none'")
    elif agent["runtime"] == "agentcore" and "agent" not in api["features"]:
        errors.append(
            "api.features must include 'agent' when agent.runtime is 'agentcore'"
        )
    if api["runtime"] == "rust" and agent["runtime"] != "agentcore":
        errors.append("agent.runtime must be 'agentcore' when api.runtime is 'rust'")

    if release["desktop"] and ui["desktop"] == "none":
        errors.append("release.desktop requires a desktop target")
    if release["mobile"] and not mobile_targets:
        errors.append("release.mobile requires a mobile target")

    return errors


def resolve_modules(data: dict[str, Any], catalog: dict[str, Any]) -> list[str]:
    """Resolve the manifest to a sorted module set, including requirements."""
    profile = data["scaffold"]["profile"]
    profiles = catalog.get("profiles", {})
    if profile not in profiles:
        raise ScaffoldError([f"scaffold.profile: unknown profile {profile!r}"])

    modules = catalog.get("modules", {})
    selectors = catalog.get("selectors", {})
    selected = set(profiles[profile].get("modules", []))
    selector_keys: list[str] = []

    ui = data["ui"]
    mobile_targets = _mobile_targets(ui)
    if ui["web"]:
        selector_keys.append("ui.web")
    if ui["desktop"] == "tauri2":
        selector_keys.append("ui.desktop.tauri")
    if ui["mobile"]["ios"] == "swiftui":
        selector_keys.append("ui.mobile.ios")
    if ui["mobile"]["android"] == "kotlin":
        selector_keys.append("ui.mobile.android")
    for feature in _mobile_features(ui, mobile_targets):
        selector_keys.append(f"mobile.feature.{feature}")
    for layout in _mobile_layouts(ui, mobile_targets):
        selector_keys.append(f"mobile.layout.{layout}")

    reference_slices = _reference_slices(data)
    if "products" in reference_slices:
        selector_keys.append("reference.products.api")
        if ui["web"]:
            selector_keys.append("reference.products.web")

    api = data["api"]
    selector_keys.append(f"api.runtime.{api['runtime']}")
    selector_keys.append(f"api.deployment.{api['deployment']}")
    for feature in api["features"]:
        selector_keys.append(f"feature.{feature}")

    model = data["model"]
    selector_keys.append(f"model.deployment.{model['deployment']}")
    for capability in model["capabilities"]:
        selector_keys.append(f"capability.{capability}")

    agent = data["agent"]
    selector_keys.append(f"agent.runtime.{agent['runtime']}")
    if agent["skills"]:
        selector_keys.append("agent.skills")
    if agent["mcp"]:
        selector_keys.append("agent.mcp")
    if agent["system_one"]:
        selector_keys.append("agent.system_one")

    ci_provider = data["ci"]["provider"]
    if ci_provider in {"github", "both"}:
        selector_keys.append("ci.github")
    if ci_provider in {"gitea", "both"}:
        selector_keys.append("ci.gitea")

    if data["release"]["desktop"]:
        selector_keys.append("release.desktop")
    if data["release"]["mobile"]:
        selector_keys.append("release.mobile")

    for selector in selector_keys:
        if selector not in selectors:
            raise ScaffoldError([f"catalog.selectors: unknown selector {selector!r}"])
        selected.update(selectors[selector])

    unknown = sorted(module for module in selected if module not in modules)
    if unknown:
        raise ScaffoldError(
            [f"module {module!r} is not defined in the catalog" for module in unknown]
        )

    changed = True
    while changed:
        changed = False
        for module in sorted(selected):
            for required in modules[module].get("requires", []):
                if required not in selected:
                    selected.add(required)
                    changed = True

    conflicts: list[str] = []
    for module in sorted(selected):
        for target in modules[module].get("conflicts", []):
            if target in selected:
                conflicts.append(f"module {module!r} conflicts with {target!r}")
    if conflicts:
        raise ScaffoldError(conflicts)

    return sorted(selected)


ROOT_MAKE_TARGETS = ("init", "check", "build", "package", "release", "dev")


def _manifest_warnings(data: dict[str, Any]) -> list[str]:
    warnings: list[str] = []
    ui = data["ui"]
    mobile_targets = _mobile_targets(ui)
    if len(mobile_targets) == 2:
        warnings.append(MOBILE_WARNING)
    if data["api"]["runtime"] == "rust":
        warnings.append(RUST_BFF_WARNING)
    if _reference_slices(data):
        warnings.append(REFERENCE_WARNING)
    return warnings


def plan_project(
    data: dict[str, Any], schema: dict[str, Any], catalog: dict[str, Any]
) -> dict[str, Any]:
    """Return the deterministic dry-run plan for one manifest."""
    errors = validate_manifest_data(data, schema, catalog)
    if errors:
        raise ScaffoldError(errors)

    modules = resolve_modules(data, catalog)
    module_entries = catalog["modules"]
    ui = data["ui"]
    mobile_targets = _mobile_targets(ui)

    outputs: set[str] = set()
    make_targets: set[str] = set(ROOT_MAKE_TARGETS)
    ci_files: set[str] = set()
    contracts: set[str] = set()
    for module in modules:
        entry = module_entries[module]
        outputs.update(entry.get("outputs", []))
        make_targets.update(entry.get("make_targets", []))
        ci_files.update(entry.get("ci", []))
        contracts.update(entry.get("contracts", []))
        if entry.get("kind") == "contracts":
            contracts.update(entry.get("outputs", []))

    providers: list[str] = []
    if "infra.ci.github" in modules:
        providers.append(".github/workflows")
    if "infra.ci.gitea" in modules:
        providers.append(".gitea/workflows")
    ci_workflows = sorted(
        f"{provider}/{name}" for provider in providers for name in ci_files
    )

    return {
        "project": data["project"],
        "profile": data["scaffold"]["profile"],
        "playbook": dict(data["playbook"]),
        "modules": modules,
        "outputs": sorted(outputs),
        "make_targets": sorted(make_targets),
        "ci_workflows": ci_workflows,
        "contracts": sorted(contracts),
        "mobile_features": _mobile_features(ui, mobile_targets),
        "mobile_layouts": _mobile_layouts(ui, mobile_targets),
        "reference_slices": _reference_slices(data),
        "commands": ["make init", "make contracts", "make check"],
        "warnings": _manifest_warnings(data),
    }


def _template_context(data: dict[str, Any], plan: dict[str, Any]) -> dict[str, Any]:
    return {
        "project": data["project"],
        "project_slug": data["project"],
        "project_title": data["project"].replace("-", " ").title(),
        "playbook": data["playbook"],
        "manifest": data,
        "modules": plan["modules"],
        "ui": data["ui"],
        "api": data["api"],
        "model": data["model"],
        "agent": data["agent"],
        "contracts": data["contracts"],
        "ci": data["ci"],
        "release": data["release"],
        "mobile_features": plan["mobile_features"],
        "mobile_layouts": plan["mobile_layouts"],
        "reference_slices": plan["reference_slices"],
        "warnings": plan["warnings"],
        "enabled": lambda module: module in plan["modules"],
    }


def _render_fragment(
    fragment: Path,
    destination: Path,
    context: dict[str, Any],
    written: dict[Path, bytes],
) -> None:
    files_root = fragment / "files"
    if not files_root.is_dir():
        return
    environment = Environment(
        undefined=StrictUndefined,
        keep_trailing_newline=True,
        trim_blocks=True,
        lstrip_blocks=True,
    )
    for source in sorted(path for path in files_root.rglob("*") if path.is_file()):
        relative = source.relative_to(files_root)
        if relative.is_absolute() or ".." in relative.parts:
            raise ScaffoldError([f"{source}: output path escapes the target"])
        try:
            if source.name.endswith(".j2"):
                output_relative = relative.with_name(relative.name[:-3])
                rendered = environment.from_string(
                    source.read_text(encoding="utf-8")
                ).render(**context)
                content = rendered.encode("utf-8")
            else:
                output_relative = relative
                content = source.read_bytes()
        except (OSError, TemplateError) as exc:
            raise ScaffoldError([f"{source}: {exc}"]) from exc

        # A conditional template that renders to nothing is skipped. This is
        # how CI workflows and feature files disappear for disabled modules.
        if not content.strip():
            continue

        output_path = destination / output_relative
        previous = written.get(output_path)
        if previous is not None and previous != content:
            raise ScaffoldError(
                [f"duplicate output path with different content: {output_relative}"]
            )
        if previous is None:
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_bytes(content)
            if source.stat().st_mode & 0o111:
                output_path.chmod(output_path.stat().st_mode | 0o111)
            written[output_path] = content


def _merge_openapi(base: dict[str, Any], extra: dict[str, Any], source: Path) -> None:
    for key, value in extra.items():
        if key not in base:
            base[key] = copy.deepcopy(value)
        elif isinstance(base[key], dict) and isinstance(value, dict):
            _merge_openapi(base[key], value, source)
        elif isinstance(base[key], list) and isinstance(value, list):
            base[key].extend(copy.deepcopy(value))
        else:
            raise ScaffoldError([f"{source}: OpenAPI conflict at {key!r}"])


def _compose_openapi(work: Path, data: dict[str, Any]) -> None:
    openapi_path = work / data["contracts"]["openapi"]
    base_path = work / "contracts" / "base" / "openapi.yaml"
    if not base_path.is_file():
        base_path = openapi_path
    modules_dir = work / "contracts" / "modules"
    if not base_path.is_file() or not modules_dir.is_dir():
        return
    try:
        base = yaml.safe_load(base_path.read_text(encoding="utf-8")) or {}
        if not isinstance(base, dict):
            raise ScaffoldError([f"{base_path}: OpenAPI document must be a mapping"])
        for path in sorted(modules_dir.glob("*.yaml")):
            extra = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
            if not isinstance(extra, dict):
                raise ScaffoldError([f"{path}: OpenAPI fragment must be a mapping"])
            _merge_openapi(base, extra, path)
    except (OSError, yaml.YAMLError) as exc:
        raise ScaffoldError([f"{base_path}: {exc}"]) from exc
    openapi_path.parent.mkdir(parents=True, exist_ok=True)
    openapi_path.write_text(yaml.safe_dump(base, sort_keys=False), encoding="utf-8")


def apply_project(
    data: dict[str, Any],
    schema: dict[str, Any],
    catalog: dict[str, Any],
    target: str | Path,
    *,
    fragments_root: str | Path = FRAGMENTS_DIR,
) -> dict[str, Any]:
    """Materialize the infrastructure skeleton for a validated manifest."""
    plan = plan_project(data, schema, catalog)
    target_path = Path(target).expanduser()
    fragments_path = Path(fragments_root)

    if target_path.exists():
        if not target_path.is_dir():
            raise ScaffoldError([f"{target_path}: target is not a directory"])
        if any(target_path.iterdir()):
            raise ScaffoldError([f"{target_path}: target directory is not empty"])
    if not fragments_path.is_dir():
        raise ScaffoldError([f"{fragments_path}: fragments directory is missing"])
    unimplemented = (
        [
            module
            for module in plan["modules"]
            if catalog["modules"][module].get("outputs")
            and not (fragments_path / module / "files").is_dir()
        ]
        if fragments_path.resolve() == FRAGMENTS_DIR.resolve()
        else []
    )
    if unimplemented:
        raise ScaffoldError(
            [
                f"module {module!r} declares outputs but has no fragment; "
                "this profile is not implemented yet"
                for module in unimplemented
            ]
        )

    target_path.parent.mkdir(parents=True, exist_ok=True)
    work = Path(
        tempfile.mkdtemp(
            prefix=f".{target_path.name}.scaffold-", dir=target_path.parent
        )
    )
    written: dict[Path, bytes] = {}
    try:
        context = _template_context(data, plan)
        for module in plan["modules"]:
            _render_fragment(fragments_path / module, work, context, written)

        (work / "project-manifest.yaml").write_text(
            yaml.safe_dump(data, sort_keys=False), encoding="utf-8"
        )
        state_dir = work / ".scaffold"
        state_dir.mkdir(parents=True, exist_ok=True)
        state = {
            "project": data["project"],
            "profile": data["scaffold"]["profile"],
            "playbook": data["playbook"],
            "modules": plan["modules"],
            "mobile_features": plan["mobile_features"],
            "mobile_layouts": plan["mobile_layouts"],
            "reference_slices": plan["reference_slices"],
            "generated_at": datetime.now(UTC).isoformat(),
            "generator": "scaffold_project.py",
            "manifest_sha256": hashlib.sha256(
                yaml.safe_dump(data, sort_keys=True).encode("utf-8")
            ).hexdigest(),
        }
        (state_dir / "state.json").write_text(
            json.dumps(state, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )

        lines = [
            f"# {data['project']}",
            "",
            f"Generated by `scaffold_project.py` from profile `{plan['profile']}`.",
            "",
            "## Modules",
            "",
            *[f"- `{module}`" for module in plan["modules"]],
            "",
            "## Next steps",
            "",
            "1. `make init`",
            "2. `make contracts`",
            "3. `make check`",
            "",
        ]
        if plan["warnings"]:
            lines.extend(
                [
                    "## Warnings",
                    "",
                    *[f"- {warning}" for warning in plan["warnings"]],
                    "",
                ]
            )
        (work / "SCAFFOLD.md").write_text("\n".join(lines), encoding="utf-8")

        _compose_openapi(work, data)

        if target_path.exists():
            target_path.rmdir()
        work.rename(target_path)
    except Exception:
        shutil.rmtree(work, ignore_errors=True)
        raise

    files = sorted(
        str(path.relative_to(target_path))
        for path in target_path.rglob("*")
        if path.is_file()
    )
    return {
        "project": data["project"],
        "profile": plan["profile"],
        "target": str(target_path),
        "modules": plan["modules"],
        "files": files,
        "warnings": plan["warnings"],
    }


def _self_test() -> int:
    catalog = load_catalog()
    schema = load_schema()

    assert catalog["version"] == 1
    catalog_errors = validate_catalog(catalog)
    assert catalog_errors == [], catalog_errors

    fragment_dirs = {path.name for path in FRAGMENTS_DIR.iterdir() if path.is_dir()}
    assert fragment_dirs <= set(catalog["modules"]), fragment_dirs - set(catalog["modules"])
    missing_fragments = {
        module
        for module, entry in catalog["modules"].items()
        if entry.get("outputs")
        and not (FRAGMENTS_DIR / module / "files").is_dir()
    }
    assert missing_fragments == {"api.rust", "api.agentcore"}, missing_fragments
    for module, entry in catalog["modules"].items():
        if entry.get("kind") == "ui":
            assert (FRAGMENTS_DIR / module / "files").is_dir(), module

    examples = sorted(EXAMPLES_DIR.glob("*.yaml"))
    assert examples, "no example manifests found"
    for path in examples:
        data = load_manifest(path)
        errors = validate_manifest_data(data, schema, catalog)
        assert errors == [], f"{path.name}: {errors}"

    web = load_manifest(EXAMPLES_DIR / "ai-web.yaml")
    web_plan = plan_project(web, schema, catalog)
    expected_web = {
        "ui.web",
        "api.python",
        "api.agent",
        "api.auth",
        "api.settings",
        "api.rag",
        "api.mcp",
        "api.products",
        "ui.agent.chat",
        "ui.settings",
        "ui.auth",
        "ui.web.products",
        "model.python",
        "model.cloud",
        "model.llm",
        "model.embedding",
        "model.rerank",
        "model.asr",
        "model.image",
        "model.tts",
        "model.video",
        "model.system_one",
        "contracts.openapi",
        "contracts.events",
        "infra.make",
        "infra.ci.github",
        "infra.docker",
    }
    assert expected_web <= set(web_plan["modules"]), expected_web - set(
        web_plan["modules"]
    )
    assert "infra.ci.gitea" not in web_plan["modules"]
    assert web_plan["commands"] == ["make init", "make contracts", "make check"]
    assert "apps/web" in web_plan["outputs"]
    assert "contracts/openapi.yaml" in web_plan["contracts"]
    assert ".github/workflows/web.yml" in web_plan["ci_workflows"]
    assert REFERENCE_WARNING in web_plan["warnings"], web_plan["warnings"]
    assert web_plan == plan_project(web, schema, catalog)
    json.dumps(web_plan, sort_keys=True)

    full = load_manifest(EXAMPLES_DIR / "ai-full.yaml")
    full_plan = plan_project(full, schema, catalog)
    for module in (
        "ui.desktop.tauri",
        "ui.mobile.ios",
        "ui.mobile.android",
        "ui.mobile.auth",
        "ui.mobile.profile",
        "ui.mobile.crud",
        "ui.mobile.responsive",
        "ui.web.products",
        "api.products",
        "infra.local-sidecars",
        "infra.release.desktop",
        "infra.release.mobile",
        "api.agent",
        "api.mcp",
        "model.system_one",
    ):
        assert module in full_plan["modules"], module
    for target in ("package-desktop", "package-mobile"):
        assert target in full_plan["make_targets"], target
    for workflow in (
        ".github/workflows/desktop.yml",
        ".gitea/workflows/desktop.yml",
        ".github/workflows/mobile.yml",
        ".gitea/workflows/mobile.yml",
    ):
        assert workflow in full_plan["ci_workflows"], workflow
    assert MOBILE_WARNING in full_plan["warnings"], full_plan["warnings"]
    assert REFERENCE_WARNING in full_plan["warnings"], full_plan["warnings"]

    rust = load_manifest(EXAMPLES_DIR / "ai-rust-bff.yaml")
    rust_plan = plan_project(rust, schema, catalog)
    for module in ("api.rust", "api.agentcore", "api.agent"):
        assert module in rust_plan["modules"], module
    assert "api.python" not in rust_plan["modules"]
    assert RUST_BFF_WARNING in rust_plan["warnings"], rust_plan["warnings"]
    assert ".gitea/workflows/api.yml" in rust_plan["ci_workflows"]
    assert ".github/workflows/api.yml" not in rust_plan["ci_workflows"]

    mobile = copy.deepcopy(web)
    mobile["project"] = "example-ai-mobile"
    mobile["scaffold"]["profile"] = "ai-mobile"
    mobile["ui"] = {
        "web": False,
        "desktop": "none",
        "mobile": {"ios": "swiftui", "android": "none"},
    }
    mobile["release"] = {"desktop": False, "mobile": False}
    assert validate_manifest_data(mobile, schema, catalog) == []
    mobile_plan = plan_project(mobile, schema, catalog)
    for module in (
        "ui.mobile.ios",
        "ui.mobile.auth",
        "ui.mobile.profile",
        "ui.mobile.crud",
        "ui.mobile.responsive",
        "api.products",
    ):
        assert module in mobile_plan["modules"], module
    assert "ui.mobile.android" not in mobile_plan["modules"]
    assert "ui.web.products" not in mobile_plan["modules"]
    assert "apps/ios" in mobile_plan["outputs"]
    assert "apps/web" not in mobile_plan["outputs"]

    def invalid(mutator: Any, fragment: str) -> None:
        data = copy.deepcopy(web)
        mutator(data)
        errors = validate_manifest_data(data, schema, catalog)
        assert any(fragment in error for error in errors), (fragment, errors)

    invalid(lambda d: d["scaffold"].update(profile="unknown"), "profile")
    invalid(lambda d: d["api"].update(runtime="rust"), "api.runtime")
    invalid(lambda d: d["ui"].update(desktop="tauri2"), "ui.desktop")
    invalid(lambda d: d["ui"].update(web=False), "ui.web")
    invalid(lambda d: d["model"].update(deployment="local"), "model.deployment")
    invalid(lambda d: d["release"].update(desktop=True), "release.desktop")
    invalid(lambda d: d["agent"].update(runtime="none"), "agent.runtime")
    invalid(lambda d: d["api"].update(features=["auth"]), "agent")

    bad_mobile = copy.deepcopy(mobile)
    bad_mobile["api"]["deployment"] = "local"
    errors = validate_manifest_data(bad_mobile, schema, catalog)
    assert any("local" in error for error in errors), errors

    desktop = copy.deepcopy(web)
    desktop["scaffold"]["profile"] = "ai-desktop"
    desktop["ui"]["desktop"] = "tauri2"
    desktop["api"]["deployment"] = "local"
    desktop["model"]["deployment"] = "local"
    assert validate_manifest_data(desktop, schema, catalog) == []
    desktop_plan = plan_project(desktop, schema, catalog)
    assert "infra.local-sidecars" in desktop_plan["modules"]
    assert "ui.desktop.tauri" in desktop_plan["modules"]

    remote_desktop = copy.deepcopy(desktop)
    remote_desktop["model"]["deployment"] = "remote"
    errors = validate_manifest_data(remote_desktop, schema, catalog)
    assert any("model.deployment" in error for error in errors), errors

    no_mobile = copy.deepcopy(full)
    no_mobile["ui"]["mobile"] = {"ios": "none", "android": "none"}
    errors = validate_manifest_data(no_mobile, schema, catalog)
    assert any("mobile" in error for error in errors), errors

    mobile_without_auth = copy.deepcopy(mobile)
    mobile_without_auth["api"]["features"] = ["agent"]
    errors = validate_manifest_data(mobile_without_auth, schema, catalog)
    assert any("auth" in error for error in errors), errors

    mobile_features_without_target = copy.deepcopy(web)
    mobile_features_without_target["ui"]["mobile"]["features"] = ["auth"]
    errors = validate_manifest_data(mobile_features_without_target, schema, catalog)
    assert any("mobile target" in error for error in errors), errors

    rust_products = copy.deepcopy(rust)
    rust_products["scaffold"]["reference_slices"] = ["products"]
    errors = validate_manifest_data(rust_products, schema, catalog)
    assert any("products" in error for error in errors), errors

    mcp_only = copy.deepcopy(web)
    mcp_only["api"]["features"] = ["auth", "settings", "agent"]
    mcp_only["agent"]["mcp"] = True
    mcp_plan = plan_project(mcp_only, schema, catalog)
    assert "api.mcp" in mcp_plan["modules"]

    broken = copy.deepcopy(catalog)
    broken["modules"]["ui.web"]["requires"] = ["missing.module"]
    assert any("missing.module" in e for e in validate_catalog(broken))

    broken = copy.deepcopy(catalog)
    broken["modules"]["ui.web"]["outputs"] = []
    assert any("ui modules must declare outputs" in e for e in validate_catalog(broken))

    broken = copy.deepcopy(catalog)
    broken["modules"]["ui.settings"]["outputs"] = ["apps/settings"]
    assert any("pattern modules must not" in e for e in validate_catalog(broken))

    broken = copy.deepcopy(catalog)
    broken["selectors"]["ui.web"] = ["missing.module"]
    assert any("missing.module" in e for e in validate_catalog(broken))

    broken = copy.deepcopy(catalog)
    broken["profiles"]["ai-web"]["modules"].append("api.rust")
    assert validate_catalog(broken), "accepted a conflicting profile"

    broken = copy.deepcopy(catalog)
    broken["profiles"]["ai-web"]["modules"].append("api.python")
    assert any("duplicate" in e for e in validate_catalog(broken)), (
        "accepted a duplicate module"
    )

    output = io.StringIO()
    with contextlib.redirect_stdout(output):
        assert main(["scaffold_project.py", "--list-modules"]) == 0
    listing = json.loads(output.getvalue())
    assert "ui.web" in listing["modules"]
    assert "ai-full" in listing["profiles"]

    output = io.StringIO()
    with contextlib.redirect_stdout(output):
        assert (
            main(["scaffold_project.py", "--plan", str(EXAMPLES_DIR / "ai-web.yaml")])
            == 0
        )
    assert json.loads(output.getvalue())["profile"] == "ai-web"

    output = io.StringIO()
    with contextlib.redirect_stdout(output):
        assert main(["scaffold_project.py", "--validate-catalog"]) == 0

    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        fragments = root / "fragments"
        (fragments / "infra.make" / "files").mkdir(parents=True)
        (fragments / "infra.make" / "files" / "Makefile.j2").write_text(
            "# {{ project }}\nenabled(ui.web)={{ enabled('ui.web') }}\n",
            encoding="utf-8",
        )
        (fragments / "infra.make" / "files" / "static.txt").write_text(
            "static\n", encoding="utf-8"
        )
        target = root / "project"
        summary = apply_project(web, schema, catalog, target, fragments_root=fragments)
        assert (target / "Makefile").read_text(encoding="utf-8") == (
            "# example-ai-web\nenabled(ui.web)=True\n"
        )
        assert (target / "static.txt").read_text(encoding="utf-8") == "static\n"
        assert (
            yaml.safe_load(
                (target / "project-manifest.yaml").read_text(encoding="utf-8")
            )["project"]
            == "example-ai-web"
        )
        state = json.loads(
            (target / ".scaffold" / "state.json").read_text(encoding="utf-8")
        )
        assert "ui.web" in state["modules"]
        assert len(state["manifest_sha256"]) == 64
        assert (target / "SCAFFOLD.md").is_file()
        assert summary["target"] == str(target)

        try:
            apply_project(web, schema, catalog, target, fragments_root=fragments)
        except ScaffoldError as exc:
            assert any("not empty" in error for error in exc.errors), exc.errors
        else:
            raise AssertionError("accepted a non-empty target")

        (fragments / "ui.web" / "files").mkdir(parents=True)
        (fragments / "ui.web" / "files" / "Makefile.j2").write_text(
            "duplicate\n", encoding="utf-8"
        )
        try:
            apply_project(
                web, schema, catalog, root / "conflict", fragments_root=fragments
            )
        except ScaffoldError as exc:
            assert any("duplicate" in error for error in exc.errors), exc.errors
        else:
            raise AssertionError("accepted a duplicate output path")

    with tempfile.TemporaryDirectory() as temporary:
        target = Path(temporary) / "real-web"
        apply_project(web, schema, catalog, target)
        assert (target / "Makefile").is_file()
        assert (target / "apps/web/src/main.tsx").is_file()
        assert (target / "apps/web/src/features/products/api.ts").is_file()
        assert (target / "apps/web/e2e/chat.spec.ts").is_file()
        assert (target / "apps/web/playwright.config.ts").is_file()
        assert (target / "apps/web/src/ui/index.ts").is_file()
        web_sources = [
            path
            for path in (target / "apps/web/src").rglob("*")
            if path.is_file()
            and path.suffix in {".ts", ".tsx"}
            and path.relative_to(target / "apps/web/src").parts[0] != "ui"
        ]
        assert web_sources
        for source in web_sources:
            assert "cliver-playbook-app-basic/components/ui" not in source.read_text(
                encoding="utf-8"
            ), f"{source}: import a UI seam, not a deep visual primitive"
        assert (target / "services/api/app/app.py").is_file()
        agent_events = target / "services/api/app/agents/events.py"
        if agent_events.is_file():
            assert (target / "services/api/app/agents/worker.py").is_file()
            migrations = {
                path.name
                for path in (target / "services/api/app/migrations/versions").iterdir()
            }
            assert "0003_agent_run_events.py" in migrations
        assert (target / "contracts/openapi.yaml").is_file()
        assert not list(target.rglob("*.j2")), "left template files in output"
        contract = yaml.safe_load(
            (target / "contracts/openapi.yaml").read_text(encoding="utf-8")
        )
        assert "/api/v1/products" in contract["paths"]
        check = subprocess.run(
            [sys.executable, str(target / "contracts" / "compose.py"), "--check"],
            check=False,
            capture_output=True,
            text=True,
        )
        assert check.returncode == 0, check.stderr

        auth_only = copy.deepcopy(mobile)
        auth_only["scaffold"]["reference_slices"] = []
        auth_only["ui"]["mobile"] = {
            "ios": "none",
            "android": "kotlin",
            "features": ["auth"],
            "layouts": ["phone"],
        }
        auth_target = Path(temporary) / "auth-only"
        apply_project(auth_only, schema, catalog, auth_target)
        settings = (auth_target / "apps/android/settings.gradle.kts").read_text(
            encoding="utf-8"
        )
        assert ":feature:auth" in settings
        assert ":feature:profile" not in settings
        assert ":feature:products" not in settings
        android_app = (auth_target / "apps/android/app/build.gradle.kts").read_text(
            encoding="utf-8"
        )
        assert 'applicationId = "com.example.example_ai_mobile"' in android_app
        android_core = (auth_target / "apps/android/core/build.gradle.kts").read_text(
            encoding="utf-8"
        )
        assert (
            "androidx.compose.material3:material3-adaptive-navigation-suite"
            in android_core
        )
        app_build = (auth_target / "apps/android/app/build.gradle.kts").read_text(
            encoding="utf-8"
        )
        assert 'project(":feature:auth")' in app_build
        assert 'project(":feature:profile")' not in app_build
        assert 'project(":feature:products")' not in app_build
        app_kt = (
            auth_target / "apps/android/app/src/main/java/com/example/android/App.kt"
        ).read_text(encoding="utf-8")
        assert "AuthScreen" in app_kt
        assert "ProfileScreen" not in app_kt
        assert "ProductListScreen" not in app_kt

        auth_ios = copy.deepcopy(mobile)
        auth_ios["scaffold"]["reference_slices"] = []
        auth_ios["ui"]["mobile"] = {
            "ios": "swiftui",
            "android": "none",
            "features": ["auth"],
            "layouts": ["phone"],
        }
        ios_target = Path(temporary) / "auth-ios"
        apply_project(auth_ios, schema, catalog, ios_target)
        assert (ios_target / "apps/ios/Packages/FeatureAuth/Package.swift").is_file()
        assert not (ios_target / "apps/ios/Packages/FeatureProfile").exists()
        assert not (ios_target / "apps/ios/Packages/FeatureProducts").exists()
        ios_project = yaml.safe_load(
            (ios_target / "apps/ios/project.yml").read_text(encoding="utf-8")
        )
        assert "Core" in ios_project["packages"]
        assert "FeatureAuth" in ios_project["packages"]
        assert "FeatureProfile" not in ios_project["packages"]
        assert "FeatureProducts" not in ios_project["packages"]
        root_view = (ios_target / "apps/ios/App/Sources/App/RootView.swift").read_text(
            encoding="utf-8"
        )
        assert "AuthView" in root_view
        assert "ProfileView" not in root_view
        assert "ProductsView" not in root_view
        plistlib.loads((ios_target / "apps/ios/App/Info.plist").read_bytes())

        profile_only = copy.deepcopy(mobile)
        profile_only["scaffold"]["reference_slices"] = []
        profile_only["ui"]["mobile"] = {
            "ios": "none",
            "android": "kotlin",
            "features": ["profile"],
            "layouts": ["pad"],
        }
        profile_target = Path(temporary) / "profile-only"
        apply_project(profile_only, schema, catalog, profile_target)
        profile_settings = (
            profile_target / "apps/android/settings.gradle.kts"
        ).read_text(encoding="utf-8")
        assert ":feature:auth" in profile_settings
        assert ":feature:profile" in profile_settings
        assert ":feature:products" not in profile_settings
        profile_build = (
            profile_target / "apps/android/app/build.gradle.kts"
        ).read_text(encoding="utf-8")
        assert 'project(":feature:auth")' in profile_build
        assert 'project(":feature:profile")' in profile_build
        assert 'project(":feature:products")' not in profile_build
        profile_app = (
            profile_target / "apps/android/app/src/main/java/com/example/android/App.kt"
        ).read_text(encoding="utf-8")
        assert "AuthScreen" in profile_app
        assert "ProfileScreen" in profile_app
        assert "ProductListScreen" not in profile_app

        crud_only = copy.deepcopy(mobile)
        crud_only["scaffold"]["reference_slices"] = []
        crud_only["api"]["features"] = ["agent"]
        crud_only["ui"]["mobile"] = {
            "ios": "none",
            "android": "kotlin",
            "features": ["crud"],
            "layouts": ["phone"],
        }
        crud_target = Path(temporary) / "crud-only"
        apply_project(crud_only, schema, catalog, crud_target)
        crud_settings = (crud_target / "apps/android/settings.gradle.kts").read_text(
            encoding="utf-8"
        )
        assert ":feature:products" in crud_settings
        assert ":feature:auth" not in crud_settings
        assert ":feature:profile" not in crud_settings
        crud_app = (
            crud_target / "apps/android/app/src/main/java/com/example/android/App.kt"
        ).read_text(encoding="utf-8")
        assert "ProductListScreen" in crud_app
        assert "AuthScreen" not in crud_app
        assert "ProfileScreen" not in crud_app

        no_features = copy.deepcopy(mobile)
        no_features["scaffold"]["reference_slices"] = []
        no_features["api"]["features"] = ["agent"]
        no_features["ui"]["mobile"] = {
            "ios": "none",
            "android": "kotlin",
            "features": [],
            "layouts": ["phone"],
        }
        none_target = Path(temporary) / "no-features"
        apply_project(no_features, schema, catalog, none_target)
        none_settings = (none_target / "apps/android/settings.gradle.kts").read_text(
            encoding="utf-8"
        )
        assert ":feature:auth" not in none_settings
        assert ":feature:profile" not in none_settings
        assert ":feature:products" not in none_settings
        none_app = (
            none_target / "apps/android/app/src/main/java/com/example/android/App.kt"
        ).read_text(encoding="utf-8")
        assert "AuthScreen" not in none_app
        assert "ProfileScreen" not in none_app
        assert "ProductListScreen" not in none_app

        desktop_target = Path(temporary) / "desktop"
        apply_project(desktop, schema, catalog, desktop_target)
        assert (desktop_target / "apps/desktop/src-tauri/tauri.conf.json").is_file()
        assert (desktop_target / "infra/sidecars/README.md").is_file()

        mobile_target = Path(temporary) / "mobile"
        apply_project(mobile, schema, catalog, mobile_target)
        assert (mobile_target / "apps/ios/project.yml").is_file()
        assert (mobile_target / "apps/ios/App/Sources/App/ChatView.swift").is_file()
        assert not (mobile_target / "apps/web").exists()

        try:
            apply_project(rust, schema, catalog, Path(temporary) / "rust-bff")
        except ScaffoldError as exc:
            assert any("api.rust" in error and "not implemented" in error for error in exc.errors), exc.errors
        else:
            raise AssertionError("applied the unimplemented Rust BFF profile")

        full_target = Path(temporary) / "full"
        apply_project(full, schema, catalog, full_target)
        for relative in (
            "apps/web/src/main.tsx",
            "apps/ios/project.yml",
            "apps/ios/Packages/FeatureAuth/Sources/FeatureAuth/AuthView.swift",
            "apps/android/settings.gradle.kts",
            "apps/android/gradlew",
            "apps/android/gradle/wrapper/gradle-wrapper.jar",
            "apps/desktop/src-tauri/tauri.conf.json",
            "apps/desktop/src-tauri/icons/icon.icns",
            "apps/desktop/src-tauri/icons/icon.ico",
            "services/api/app/app.py",
            "services/model/model_app/main.py",
        ):
            assert (full_target / relative).is_file(), relative
        gradlew = full_target / "apps/android/gradlew"
        assert gradlew.stat().st_mode & 0o111, "gradlew must be executable"
        wrapper = (
            full_target / "apps/android/gradle/wrapper/gradle-wrapper.properties"
        ).read_text(encoding="utf-8")
        assert "gradle-8.10.2-bin.zip" in wrapper, wrapper
        desktop_conf = json.loads(
            (full_target / "apps/desktop/src-tauri/tauri.conf.json").read_text(
                encoding="utf-8"
            )
        )
        assert desktop_conf["bundle"]["active"] is True
        makefile = (full_target / "Makefile").read_text(encoding="utf-8")
        assert "CODE_SIGNING_ALLOWED=NO" in makefile
        assert "package-desktop: build-web" in makefile
        assert "package: build" in makefile
        assert "test-ios" in makefile
        assert "test-android" in makefile
        assert "test-model" in makefile
        assert "contract-test" in makefile
        assert (full_target / "services/api/scripts/contract_test.py").is_file()
        assert (full_target / "apps/web/src/contracts/schema.d.ts").is_file()
        assert (full_target / "apps/web/e2e/real-api.spec.ts").is_file()
        assert "contracts:generate" in makefile
        assert "web-e2e-real" in makefile
        for line in makefile.splitlines():
            if line.startswith(("DEV_TARGETS :=", "CHECK_TARGETS :=", "BUILD_TARGETS :=")):
                assert line.count(":=") == 1, f"joined make assignment: {line}"
        migrations_dir = full_target / "services/api/app/migrations/versions"
        for migration in migrations_dir.glob("*.py"):
            migration_text = migration.read_text(encoding="utf-8")
            assert "\nCreate Date:" in migration_text, (
                f"{migration.name}: joined Revises/Create Date metadata"
            )
        api_ci = (
            full_target / ".github/workflows/api.yml"
        ).read_text(encoding="utf-8")
        assert "scripts/contract_test.py" in api_ci
        desktop_ci = (
            full_target / ".github/workflows/desktop.yml"
        ).read_text(encoding="utf-8")
        assert "pnpm tauri build --bundles app" in desktop_ci
        assert "pnpm tauri build --bundles deb" in desktop_ci
        mobile_ci = (
            full_target / ".github/workflows/mobile.yml"
        ).read_text(encoding="utf-8")
        assert "swift test" in mobile_ci
        assert "./gradlew assembleDebug testDebugUnitTest" in mobile_ci
        for workflow in (full_target / ".github/workflows").glob("*.yml"):
            yaml.safe_load(workflow.read_text(encoding="utf-8"))
        assert not list(full_target.rglob(".build")), "copied Swift build output"
        assert not list(full_target.rglob("*.j2"))

    with tempfile.TemporaryDirectory() as temporary:
        target = Path(temporary) / "cli-project"
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            assert (
                main(
                    [
                        "scaffold_project.py",
                        "--apply",
                        str(EXAMPLES_DIR / "ai-web.yaml"),
                        "--target",
                        str(target),
                    ]
                )
                == 0
            )
        assert (target / "project-manifest.yaml").is_file()
        assert (target / "SCAFFOLD.md").is_file()

    print("self-test: OK")
    return 0


def _list_payload(catalog: dict[str, Any]) -> dict[str, Any]:
    modules = catalog["modules"]
    profiles = catalog["profiles"]
    selectors = catalog["selectors"]
    return {
        "modules": {
            module: {
                "kind": modules[module]["kind"],
                "description": modules[module]["description"],
            }
            for module in sorted(modules)
        },
        "profiles": {
            profile: {
                "description": profiles[profile]["description"],
                "modules": sorted(profiles[profile]["modules"]),
            }
            for profile in sorted(profiles)
        },
        "selectors": {
            selector: sorted(selectors[selector]) for selector in sorted(selectors)
        },
    }


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument(
        "--plan", metavar="MANIFEST", help="Print the dry-run plan for a manifest."
    )
    action.add_argument(
        "--list-modules",
        action="store_true",
        help="Print the module, profile and selector catalog as JSON.",
    )
    action.add_argument(
        "--validate-catalog",
        action="store_true",
        help="Validate the catalog, schema and example manifests.",
    )
    action.add_argument(
        "--self-test",
        action="store_true",
        help="Run the built-in tests.",
    )
    action.add_argument(
        "--apply",
        metavar="MANIFEST",
        help="Create the infrastructure skeleton from a manifest.",
    )
    parser.add_argument(
        "--target",
        metavar="DIR",
        help="Target directory for --apply; defaults to ./<project>.",
    )
    args = parser.parse_args(argv[1:])
    if args.target and not args.apply:
        parser.error("--target requires --apply")

    if args.self_test:
        return _self_test()

    try:
        catalog = load_catalog()
        if args.list_modules:
            errors = validate_catalog(catalog)
            if errors:
                for error in errors:
                    print(error, file=sys.stderr)
                return 1
            print(json.dumps(_list_payload(catalog), indent=2, sort_keys=True))
            return 0

        schema = load_schema()
        if args.apply:
            data = load_manifest(Path(args.apply))
            target = (
                Path(args.target).expanduser()
                if args.target
                else Path.cwd() / data["project"]
            )
            summary = apply_project(data, schema, catalog, target)
            print(json.dumps(summary, indent=2, sort_keys=True))
            return 0

        if args.validate_catalog:
            errors = validate_catalog(catalog)
            example_profiles: set[str] = set()
            for path in sorted(EXAMPLES_DIR.glob("*.yaml")):
                data = load_manifest(path)
                profile = data.get("scaffold", {}).get("profile")
                if isinstance(profile, str):
                    example_profiles.add(profile)
                for error in validate_manifest_data(data, schema, catalog):
                    errors.append(f"{path.name}: {error}")
            for profile in sorted(REQUIRED_PROFILES - example_profiles):
                errors.append(f"examples: no manifest for profile {profile!r}")
            if errors:
                for error in errors:
                    print(error, file=sys.stderr)
                return 1
            print("catalog: OK")
            return 0

        if args.plan:
            data = load_manifest(Path(args.plan))
            plan = plan_project(data, schema, catalog)
            print(json.dumps(plan, indent=2, sort_keys=True))
            return 0
    except ScaffoldError as exc:
        for error in exc.errors:
            print(error, file=sys.stderr)
        return 1
    except (OSError, yaml.YAMLError, json.JSONDecodeError, SchemaError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    parser.error("choose an action")
    return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
