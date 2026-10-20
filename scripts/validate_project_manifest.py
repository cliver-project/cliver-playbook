#!/usr/bin/env python3
"""Validate a project manifest describing how a project consumes the playbook.

Usage:
    uv run python scripts/validate_project_manifest.py <manifest.yaml>

Exit status is 0 when the manifest is valid. Otherwise every problem is
printed on its own line to stderr and the exit status is 1.
"""

from __future__ import annotations

import re
import sys
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import yaml

PACKAGE_NAMES = {
    "cliver-playbook-app-basic",
    "cliver-playbook-app-user",
    "cliver-playbook-app-rag",
    "cliver-playbook-app-mcp",
}
MODES = {"compose", "vendor", "generate"}
TOP_LEVEL_KEYS = {
    "project",
    "playbook",
    "mode",
    "packages",
    "vendored",
    "decisions",
}
PLAYBOOK_KEYS = {"source", "revision"}
PACKAGES_KEYS = {"backend", "frontend"}
VENDORED_ENTRY_KEYS = {"package", "source_path", "target_path", "revision"}
RELEASE_TAG = re.compile(r"(?:v)?\d+\.\d+\.\d+(?:[-+][0-9A-Za-z.-]+)?")
COMMIT_SHA = re.compile(r"[0-9a-f]{7,40}")

REQUIRED_KEYS = ("project", "playbook", "mode", "packages", "vendored")


def _report_unknown_keys(
    mapping: Mapping[str, Any], allowed: set[str], where: str, errors: list[str]
) -> None:
    for key in sorted((key for key in mapping if key not in allowed), key=str):
        if not isinstance(key, str):
            errors.append(f"{where}: keys must be strings, got {key!r}")
        else:
            errors.append(f"{where}: unknown key {key!r}")


def _require_non_empty_string(value: Any, where: str, errors: list[str]) -> bool:
    if not isinstance(value, str) or not value.strip():
        errors.append(f"{where} must be a non-empty string")
        return False
    return True


def _validate_revision(value: Any, where: str, errors: list[str]) -> None:
    """Require a release tag or commit, never a branch or a placeholder."""
    if not _require_non_empty_string(value, where, errors):
        return
    revision = value.strip()
    if RELEASE_TAG.fullmatch(revision) or COMMIT_SHA.fullmatch(revision):
        return
    errors.append(
        f"{where} must name a release tag (X.Y.Z) or a commit SHA, not {revision!r}"
    )


def _validate_package_list(value: Any, where: str, errors: list[str]) -> None:
    if not isinstance(value, list):
        errors.append(f"{where} must be a list of package names")
        return
    for index, name in enumerate(value):
        if not isinstance(name, str) or not name.strip():
            errors.append(f"{where}[{index}] must be a non-empty string")
        elif name not in PACKAGE_NAMES:
            errors.append(f"{where}[{index}]: unknown package {name!r}")


def _validate_vendored_entry(
    entry: Any, index: int, errors: list[str]
) -> dict[str, Any] | None:
    where = f"vendored[{index}]"
    if not isinstance(entry, Mapping):
        errors.append(f"{where} must be a mapping")
        return None
    _report_unknown_keys(entry, VENDORED_ENTRY_KEYS, where, errors)
    for key in sorted(VENDORED_ENTRY_KEYS):
        if key not in entry:
            errors.append(f"{where}: missing required key {key!r}")
            continue
        value = entry[key]
        if key == "package":
            if (
                _require_non_empty_string(value, f"{where}.package", errors)
                and value not in PACKAGE_NAMES
            ):
                errors.append(f"{where}.package: unknown package {value!r}")
        elif key == "revision":
            _validate_revision(value, f"{where}.revision", errors)
        else:
            _require_non_empty_string(value, f"{where}.{key}", errors)
    return dict(entry)


def validate_manifest(data: dict[str, Any]) -> list[str]:
    """Return human-readable errors; an empty list means the manifest is valid."""
    if not isinstance(data, Mapping):
        return ["manifest must be a mapping"]

    errors: list[str] = []
    _report_unknown_keys(data, TOP_LEVEL_KEYS, "manifest", errors)
    for key in REQUIRED_KEYS:
        if key not in data:
            errors.append(f"manifest: missing required key {key!r}")

    if "project" in data:
        _require_non_empty_string(data["project"], "project", errors)

    if "playbook" in data:
        playbook = data["playbook"]
        if not isinstance(playbook, Mapping):
            errors.append("playbook must be a mapping")
        else:
            _report_unknown_keys(playbook, PLAYBOOK_KEYS, "playbook", errors)
            revision = playbook.get("revision")
            if revision is None:
                errors.append("playbook: missing required key 'revision'")
            else:
                _validate_revision(revision, "playbook.revision", errors)
            if "source" in playbook:
                _require_non_empty_string(playbook["source"], "playbook.source", errors)

    mode = data.get("mode")
    if "mode" in data and mode not in MODES:
        errors.append(f"mode must be one of {sorted(MODES)}, got {mode!r}")

    if "packages" in data:
        packages = data["packages"]
        if not isinstance(packages, Mapping):
            errors.append("packages must be a mapping")
        else:
            _report_unknown_keys(packages, PACKAGES_KEYS, "packages", errors)
            for key in sorted(PACKAGES_KEYS & set(packages)):
                _validate_package_list(packages[key], f"packages.{key}", errors)

    vendored = data.get("vendored")
    if "vendored" in data and not isinstance(vendored, list):
        errors.append("vendored must be a list")
        vendored = None

    if isinstance(vendored, list):
        entries = []
        for index, entry in enumerate(vendored):
            parsed = _validate_vendored_entry(entry, index, errors)
            if parsed is not None:
                entries.append(parsed)

        if mode == "compose" and vendored:
            errors.append(
                "mode 'compose' requires an empty 'vendored' list; "
                "use mode 'vendor' to own a copy"
            )
        if mode == "vendor":
            if not vendored:
                errors.append("mode 'vendor' requires at least one vendored entry")
            else:
                packages_in_use = {
                    name
                    for key in ("backend", "frontend")
                    if isinstance(data.get("packages"), Mapping)
                    and isinstance(data["packages"].get(key), list)
                    for name in data["packages"][key]
                    if isinstance(name, str)
                }
                for entry in entries:
                    package = entry.get("package")
                    if (
                        isinstance(package, str)
                        and package in PACKAGE_NAMES
                        and package not in packages_in_use
                    ):
                        errors.append(
                            f"vendored package {package!r} is not listed in packages"
                        )

    if "decisions" in data:
        decisions = data["decisions"]
        if not isinstance(decisions, list):
            errors.append("decisions must be a list")
        else:
            for index, decision in enumerate(decisions):
                _require_non_empty_string(decision, f"decisions[{index}]", errors)

    return errors


def _self_test() -> int:
    base: dict[str, Any] = {
        "project": "example-app",
        "playbook": {
            "source": "https://github.com/cliver-project/cliver-playbook",
            "revision": "0.1.0",
        },
        "mode": "compose",
        "packages": {
            "backend": ["cliver-playbook-app-basic"],
            "frontend": ["cliver-playbook-app-basic"],
        },
        "vendored": [],
    }
    assert validate_manifest(base) == []

    for revision in ("main", "origin/main", "HEAD", "<tag-or-commit>", "feature/x"):
        manifest = {**base, "playbook": {**base["playbook"], "revision": revision}}
        assert validate_manifest(manifest), f"accepted floating revision {revision!r}"

    sha = "0123456789abcdef0123456789abcdef01234567"
    pinned = {**base, "playbook": {**base["playbook"], "revision": sha}}
    assert validate_manifest(pinned) == []

    legacy_tag = {**base, "playbook": {**base["playbook"], "revision": "v0.1.0"}}
    assert validate_manifest(legacy_tag) == []

    vendor_manifest = {
        **base,
        "mode": "vendor",
        "packages": {
            "backend": ["cliver-playbook-app-basic"],
            "frontend": [],
        },
        "vendored": [
            {
                "package": "cliver-playbook-app-basic",
                "source_path": "packages/backend/cliver-playbook-app-basic/src/cliver_playbook",
                "target_path": "vendor/cliver_playbook",
                "revision": "0.1.0",
            }
        ],
    }
    assert validate_manifest(vendor_manifest) == []

    unknown_package = {
        **vendor_manifest,
        "vendored": [{**vendor_manifest["vendored"][0], "package": "totally-unknown"}],
    }
    assert validate_manifest(unknown_package), "accepted an unknown vendored package"

    floating_vendored = {
        **vendor_manifest,
        "vendored": [{**vendor_manifest["vendored"][0], "revision": "main"}],
    }
    assert validate_manifest(floating_vendored), "accepted a floating vendored revision"

    mixed_keys = {**base, 1: "x", "z": "extra"}
    errors = validate_manifest(mixed_keys)
    assert any("keys must be strings" in error for error in errors)

    print("self-test: OK")
    return 0


def main(argv: list[str]) -> int:
    if argv[1:] == ["--self-test"]:
        return _self_test()

    if len(argv) != 2:
        print(
            "usage: validate_project_manifest.py <manifest.yaml> | --self-test",
            file=sys.stderr,
        )
        return 1

    path = Path(argv[1])
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        print(f"{path}: {exc}", file=sys.stderr)
        return 1

    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        print(f"{path}: invalid YAML: {exc}", file=sys.stderr)
        return 1

    errors = validate_manifest(data)
    for error in errors:
        print(error, file=sys.stderr)
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
