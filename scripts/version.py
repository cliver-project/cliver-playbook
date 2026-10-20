#!/usr/bin/env python3
"""Keep every cliver-playbook module on one version.

Usage:
    python3 scripts/version.py --check [--tag vX.Y.Z]
    python3 scripts/version.py --set X.Y.Z
    python3 scripts/version.py --self-test

Backend distributions, the frontend packages, and the workspace root share a
single version. A release tag must be ``v`` plus that version.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import tempfile
from pathlib import Path

BACKEND_PACKAGES = ("basic", "user", "rag", "mcp")
FRONTEND_PACKAGES = ("basic", "user", "rag", "mcp")

VERSION_PATTERN = re.compile(r"^\d+\.\d+\.\d+(?:(?:a|b|rc)\d+)?$")
PY_VERSION_LINE = re.compile(r'(?m)^version = "([^"]+)"$')
PY_VERSION_REPLACE = re.compile(r'(?m)^(version = ")[^"]+(")$')
PY_PIN = re.compile(r'"(cliver-playbook-app-(?:basic|user|rag|mcp))([^"]*)"')
PY_PIN_REPLACE = re.compile(r'("cliver-playbook-app-(?:basic|user|rag|mcp))==[^"]+"')
JSON_VERSION_REPLACE = re.compile(r'(?m)^(\s*"version":\s*")[^"]+(")')
JSON_DEP_REPLACE = re.compile(
    r'("cliver-playbook-app-(?:basic|user|rag|mcp)":\s*")(?!workspace:)[^"]+(")'
)


def _backend_manifests(root: Path) -> list[Path]:
    return [
        root / "packages" / "backend" / f"cliver-playbook-app-{name}" / "pyproject.toml"
        for name in BACKEND_PACKAGES
    ]


def _frontend_manifests(root: Path) -> list[Path]:
    paths = [root / "package.json"]
    for name in FRONTEND_PACKAGES:
        base = root / "packages" / "frontend" / f"cliver-playbook-app-{name}"
        paths.extend([base / "package.json", base / "dev" / "package.json"])
    return paths


def _manifest_paths(root: Path) -> list[Path]:
    return [*_backend_manifests(root), *_frontend_manifests(root)]


def collect_versions(root: Path) -> dict[str, str]:
    """Return manifest path -> declared version."""
    versions: dict[str, str] = {}
    for path in _manifest_paths(root):
        text = path.read_text(encoding="utf-8")
        if path.name == "pyproject.toml":
            match = PY_VERSION_LINE.search(text)
            version = match.group(1) if match else None
        else:
            version = json.loads(text).get("version")
        if not isinstance(version, str):
            raise TypeError(f"{path}: version must be a string")
        versions[path.relative_to(root).as_posix()] = version
    return versions


def _loaded_versions(root: Path) -> tuple[str | None, list[str]]:
    errors: list[str] = []
    try:
        versions = collect_versions(root)
    except (OSError, TypeError, ValueError, json.JSONDecodeError) as exc:
        return None, [str(exc)]
    unique = sorted(set(versions.values()))
    if len(unique) != 1:
        for path, version in sorted(versions.items()):
            errors.append(f"{path}: version {version!r}")
        errors.append(f"expected one shared version, found {unique}")
        return None, errors
    return unique[0], errors


def check_versions(root: Path, tag: str | None = None) -> list[str]:
    """Return human-readable inconsistencies; empty means every module agrees."""
    version, errors = _loaded_versions(root)
    if version is None:
        return errors

    if tag is not None and tag != f"v{version}":
        errors.append(f"tag {tag!r} does not match version {version!r}")

    for path in _backend_manifests(root):
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip().startswith('"'):
                continue
            for package, specifier in PY_PIN.findall(line):
                if specifier != f"=={version}":
                    errors.append(
                        f"{path.relative_to(root)}: {package} must be pinned "
                        f"to =={version}, found {specifier!r}"
                    )

    for path in _frontend_manifests(root):
        data = json.loads(path.read_text(encoding="utf-8"))
        for section in ("dependencies", "devDependencies"):
            for package, specifier in data.get(section, {}).items():
                if not package.startswith("cliver-playbook-app-"):
                    continue
                if isinstance(specifier, str) and specifier.startswith("workspace:"):
                    continue
                if specifier != version:
                    errors.append(
                        f"{path.relative_to(root)}: {package} must depend on "
                        f"{version!r}, found {specifier!r}"
                    )
    return errors


def set_version(root: Path, version: str) -> list[str]:
    """Rewrite every manifest to ``version``; return the changed paths."""
    if not VERSION_PATTERN.fullmatch(version):
        raise ValueError(f"invalid version {version!r}; expected X.Y.Z")

    changed: list[str] = []
    for path in _backend_manifests(root):
        text = path.read_text(encoding="utf-8")
        text, count = PY_VERSION_REPLACE.subn(rf"\g<1>{version}\g<2>", text, count=1)
        if count != 1:
            raise ValueError(f"{path}: no [project] version line found")
        text = PY_PIN_REPLACE.sub(rf"\g<1>=={version}", text)
        path.write_text(text, encoding="utf-8")
        changed.append(path.relative_to(root).as_posix())

    for path in _frontend_manifests(root):
        text = path.read_text(encoding="utf-8")
        text, count = JSON_VERSION_REPLACE.subn(rf"\g<1>{version}\g<2>", text, count=1)
        if count != 1:
            raise ValueError(f"{path}: no version field found")
        text = JSON_DEP_REPLACE.sub(rf"\g<1>{version}\g<2>", text)
        path.write_text(text, encoding="utf-8")
        changed.append(path.relative_to(root).as_posix())

    errors = check_versions(root)
    if errors:
        raise RuntimeError("version update left inconsistencies:\n" + "\n".join(errors))
    return changed


def _self_test() -> int:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        for name in BACKEND_PACKAGES:
            path = (
                root
                / "packages/backend"
                / f"cliver-playbook-app-{name}"
                / "pyproject.toml"
            )
            path.parent.mkdir(parents=True)
            path.write_text(
                '[project]\nname = "cliver-playbook-app-basic"\n'
                'version = "0.1.0"\n'
                "dependencies = [\n"
                '    "cliver-playbook-app-basic==0.1.0",\n'
                "]\n",
                encoding="utf-8",
            )
        root.joinpath("package.json").write_text(
            '{\n  "name": "root",\n  "version": "0.1.0"\n}\n', encoding="utf-8"
        )
        for name in FRONTEND_PACKAGES:
            base = root / "packages/frontend" / f"cliver-playbook-app-{name}"
            base.mkdir(parents=True)
            base.joinpath("package.json").write_text(
                json.dumps(
                    {
                        "name": f"cliver-playbook-app-{name}",
                        "version": "0.1.0",
                        "dependencies": {"cliver-playbook-app-basic": "0.1.0"},
                    },
                    indent=2,
                ),
                encoding="utf-8",
            )
            dev = base / "dev"
            dev.mkdir()
            dev.joinpath("package.json").write_text(
                json.dumps(
                    {
                        "name": f"cliver-playbook-app-{name}-dev",
                        "version": "0.1.0",
                        "dependencies": {"cliver-playbook-app-basic": "workspace:*"},
                    },
                    indent=2,
                ),
                encoding="utf-8",
            )

        assert not check_versions(root, "v0.1.0")
        set_version(root, "0.2.0")
        assert set(collect_versions(root).values()) == {"0.2.0"}
        assert not check_versions(root, "v0.2.0")
        assert check_versions(root, "v0.1.0")
        dev_manifest = (
            root / "packages/frontend/cliver-playbook-app-basic/dev/package.json"
        )
        assert (
            json.loads(dev_manifest.read_text())["dependencies"][
                "cliver-playbook-app-basic"
            ]
            == "workspace:*"
        )
    print("self-test: OK")
    return 0


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--root", type=Path, default=Path(__file__).resolve().parent.parent
    )
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--check", action="store_true")
    action.add_argument("--set", metavar="VERSION")
    action.add_argument("--self-test", action="store_true")
    parser.add_argument("--tag", help="release tag that must match the version")
    args = parser.parse_args(argv[1:])

    root = args.root.resolve()
    if args.self_test:
        return _self_test()

    if args.set:
        try:
            changed = set_version(root, args.set)
        except (OSError, TypeError, ValueError, RuntimeError) as exc:
            print(str(exc), file=sys.stderr)
            return 1
        for path in changed:
            print(f"updated {path}")
        print(
            f"Version set to {args.set}. Next: run `uv lock`, commit, then "
            f"push tag v{args.set}."
        )
        return 0

    errors = check_versions(root, args.tag)
    if errors:
        for error in errors:
            print(error, file=sys.stderr)
        return 1
    version, _ = _loaded_versions(root)
    print(f"version OK: {version}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
