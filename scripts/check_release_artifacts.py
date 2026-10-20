#!/usr/bin/env python3
"""Check that the built release artifacts are complete and licensed.

Usage:
    uv run python scripts/check_release_artifacts.py [--dist dist] [--version X.Y.Z]

For every backend package the check requires exactly one wheel and one sdist,
each carrying the project's license text, and a wheel whose metadata names the
expected version and the Apache-2.0 license expression. PyPI keeps released
files forever, so this runs before publishing (and in the release workflow).
"""

from __future__ import annotations

import argparse
import sys
import tarfile
import tomllib
import zipfile
from pathlib import Path

PACKAGES = ("basic", "user", "rag", "mcp")
LICENSE_PREFIXES = ("LICENSE", "LICENCE", "COPYING", "NOTICE")
REPO_ROOT = Path(__file__).resolve().parent.parent


def _configured_version() -> str:
    manifest = (
        REPO_ROOT
        / "packages"
        / "backend"
        / "cliver-playbook-app-basic"
        / "pyproject.toml"
    )
    with manifest.open("rb") as handle:
        return tomllib.load(handle)["project"]["version"]


def _members(artifact: Path) -> list[str]:
    if artifact.suffix == ".whl":
        with zipfile.ZipFile(artifact) as archive:
            return archive.namelist()
    with tarfile.open(artifact) as archive:
        return archive.getnames()


def _wheel_metadata(artifact: Path) -> str:
    with zipfile.ZipFile(artifact) as archive:
        metadata = [
            name for name in archive.namelist() if name.endswith(".dist-info/METADATA")
        ]
        if len(metadata) != 1:
            return ""
        return archive.read(metadata[0]).decode("utf-8", errors="replace")


def check(dist: Path, version: str) -> list[str]:
    """Return one error per missing or incomplete artifact."""
    errors: list[str] = []
    for package in PACKAGES:
        stem = f"cliver_playbook_app_{package}-{version}"
        wheels = sorted(dist.glob(f"{stem}-*.whl"))
        sdists = sorted(dist.glob(f"{stem}.tar.gz"))
        if len(wheels) != 1:
            errors.append(
                f"{package}: expected one wheel {stem}-*.whl, found {len(wheels)}"
            )
        if len(sdists) != 1:
            errors.append(
                f"{package}: expected one sdist {stem}.tar.gz, found {len(sdists)}"
            )

        for artifact in [*wheels, *sdists]:
            names = _members(artifact)
            if not any(
                Path(name).name.upper().startswith(LICENSE_PREFIXES) for name in names
            ):
                errors.append(
                    f"{artifact.name}: no license text (LICENSE/COPYING/NOTICE)"
                )

        for wheel in wheels:
            metadata = _wheel_metadata(wheel)
            if f"\nVersion: {version}\n" not in f"\n{metadata}":
                errors.append(
                    f"{wheel.name}: metadata does not declare version {version}"
                )
            if "License-Expression: Apache-2.0" not in metadata:
                errors.append(f"{wheel.name}: metadata does not declare Apache-2.0")
    return errors


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dist", default="dist", help="directory containing the built files"
    )
    parser.add_argument("--version", default=None, help="expected shared version")
    args = parser.parse_args(argv[1:])

    dist = Path(args.dist)
    if not dist.is_dir():
        print(f"artifact directory not found: {dist}", file=sys.stderr)
        return 1
    version = args.version or _configured_version()
    errors = check(dist, version)
    for error in errors:
        print(error, file=sys.stderr)
    if not errors:
        print(f"release artifacts OK: 4 packages at {version}, license text present")
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
