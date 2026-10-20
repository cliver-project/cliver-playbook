#!/usr/bin/env python3
"""Copy a cliver-playbook package into a project without renaming it.

Vendor mode is the opt-in fork described in REUSE.md: the target project owns
the copied tree, the ``cliver_playbook`` namespace is preserved, and
``vendor/FORKED_FROM.md`` records where the copy came from.
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from datetime import date
from pathlib import Path

PACKAGES = ("basic", "user", "rag", "mcp")
REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_REPO_URL = "https://github.com/cliver-project/cliver-playbook"


def _git_output(*args: str) -> str | None:
    try:
        result = subprocess.run(
            ["git", "-C", str(REPO_ROOT), *args],
            capture_output=True,
            text=True,
            check=True,
        )
    except (OSError, subprocess.CalledProcessError):
        return None
    return result.stdout.strip()


def _repo_url() -> str:
    url = _git_output("config", "--get", "remote.origin.url")
    if not url:
        return DEFAULT_REPO_URL
    if url.startswith("git@github.com:"):
        url = "https://github.com/" + url.removeprefix("git@github.com:")
    return url.removesuffix(".git")


def _revision() -> str:
    sha = _git_output("rev-parse", "HEAD")
    if not sha:
        return "unknown revision"
    tag = _git_output("describe", "--tags", "--exact-match", "HEAD")
    return f"{tag} (commit {sha})" if tag else f"commit {sha}"


def _source_tree(package: str) -> Path:
    return (
        REPO_ROOT
        / "packages"
        / "backend"
        / f"cliver-playbook-app-{package}"
        / "src"
        / "cliver_playbook"
    )


def _provenance(package: str, source: Path, target: Path) -> str:
    source_path = source.relative_to(REPO_ROOT).as_posix()
    return (
        "# Forked from cliver-playbook\n\n"
        f"- Source repository: {_repo_url()}\n"
        f"- Revision: {_revision()}\n"
        f"- Source path: {source_path}\n"
        f"- Target path: {target.as_posix()}\n"
        f"- Date: {date.today().isoformat()}\n"
        "- Local changes: none yet\n"
        "- Upgrade policy: no upstream sync; compare against later playbook "
        "tags manually.\n"
    )


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--package", required=True, choices=PACKAGES)
    parser.add_argument("--target", required=True, help="project directory")
    parser.add_argument(
        "--apply",
        action="store_true",
        help="copy the tree; without it the script only prints what it would do",
    )
    args = parser.parse_args(argv[1:])

    source = _source_tree(args.package)
    if not source.is_dir():
        print(f"source tree not found: {source}", file=sys.stderr)
        return 1

    target = Path(args.target).resolve()
    vendor_root = target / "vendor"
    destination = vendor_root / "cliver_playbook"
    if not destination.is_relative_to(target):
        print("refusing to write outside the target project", file=sys.stderr)
        return 1
    if vendor_root.exists() and not vendor_root.resolve().is_relative_to(target):
        print(
            "refusing to write through a vendor symlink outside the target",
            file=sys.stderr,
        )
        return 1
    if destination.exists():
        print(f"destination already exists: {destination}", file=sys.stderr)
        return 1

    import_path = f"cliver_playbook.app.{args.package}"
    if not args.apply:
        print(f"Would copy {source} to {destination}")
        print(f"Vendored import path: {import_path}")
        print("Re-run with --apply to write the tree and FORKED_FROM.md.")
        return 0

    vendor_root.mkdir(parents=True, exist_ok=True)
    shutil.copytree(
        source,
        destination,
        ignore=shutil.ignore_patterns(
            "__pycache__", "*.pyc", ".pytest_cache", ".ruff_cache"
        ),
    )
    (vendor_root / "FORKED_FROM.md").write_text(
        _provenance(args.package, source, Path("vendor/cliver_playbook")),
        encoding="utf-8",
    )

    print(f"Vendored {source} to {destination}")
    print(f"Import path: {import_path}")
    print(
        f"Add the vendor root ({vendor_root}) to the project's import path "
        "in pyproject.toml."
    )
    print(f"Provenance: {vendor_root / 'FORKED_FROM.md'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
