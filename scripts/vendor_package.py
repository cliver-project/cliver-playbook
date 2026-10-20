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
import tempfile
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


def _provenance_section(package: str, source: Path, target: Path) -> str:
    source_path = source.relative_to(REPO_ROOT).as_posix()
    return (
        f"## cliver-playbook-app-{package}\n\n"
        f"- Source repository: {_repo_url()}\n"
        f"- Revision: {_revision()}\n"
        f"- Source path: {source_path}\n"
        f"- Target path: {target.as_posix()}\n"
        f"- Date: {date.today().isoformat()}\n"
        "- Local changes: none yet\n"
        "- Upgrade policy: no upstream sync; compare against later playbook "
        "tags manually.\n"
        f'- Import check: `python -c "import cliver_playbook.app.{package} as m; '
        f'print(m.__file__)"` must print a path under `vendor/`. Do not install '
        "the same distribution from PyPI.\n"
    )


def _append_provenance(vendor_root: Path, sections: list[str]) -> Path:
    path = vendor_root / "FORKED_FROM.md"
    body = "\n".join(section.rstrip() for section in sections) + "\n"
    if path.exists():
        existing = path.read_text(encoding="utf-8").rstrip()
        path.write_text(f"{existing}\n\n{body}", encoding="utf-8")
    else:
        path.write_text(f"# Forked from cliver-playbook\n\n{body}", encoding="utf-8")
    return path


def _self_test() -> int:
    with tempfile.TemporaryDirectory() as tmp:
        target = Path(tmp)
        args = ["vendor", "--target", tmp, "--apply"]
        assert main([*args, "--package", "basic", "--package", "user"]) == 0
        destination = target / "vendor" / "cliver_playbook"
        assert (destination / "app" / "basic").is_dir()
        assert (destination / "app" / "user").is_dir()
        provenance = (target / "vendor" / "FORKED_FROM.md").read_text(encoding="utf-8")
        assert "## cliver-playbook-app-basic" in provenance
        assert "## cliver-playbook-app-user" in provenance
        assert "cliver_playbook.app.basic" in provenance
        assert main([*args, "--package", "basic"]) == 1

        dry_target = target / "dry"
        assert main(["vendor", "--target", str(dry_target), "--package", "rag"]) == 0
        assert not (dry_target / "vendor").exists()

    print("self-test: OK")
    return 0


def main(argv: list[str]) -> int:
    if argv[1:] == ["--self-test"]:
        return _self_test()

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--package",
        required=True,
        action="append",
        choices=PACKAGES,
        help="package to vendor; repeat to copy several into one namespace",
    )
    parser.add_argument("--target", required=True, help="project directory")
    parser.add_argument(
        "--apply",
        action="store_true",
        help="copy the tree; without it the script only prints what it would do",
    )
    args = parser.parse_args(argv[1:])

    packages = list(dict.fromkeys(args.package))
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
    if destination.exists() and not destination.resolve().is_relative_to(target):
        print(
            "refusing to write through a namespace symlink outside the target",
            file=sys.stderr,
        )
        return 1

    sources: list[tuple[str, Path]] = []
    for package in packages:
        source = _source_tree(package)
        package_source = source / "app" / package
        if not package_source.is_dir():
            print(f"source tree not found: {package_source}", file=sys.stderr)
            return 1
        package_destination = destination / "app" / package
        if package_destination.exists():
            print(f"package already vendored: {package_destination}", file=sys.stderr)
            return 1
        sources.append((package, source))

    if not args.apply:
        for package, source in sources:
            print(f"Would copy {source} to {destination}")
            print(f"Vendored import path: cliver_playbook.app.{package}")
        print("Re-run with --apply to write the tree and FORKED_FROM.md.")
        return 0

    vendor_root.mkdir(parents=True, exist_ok=True)
    sections: list[str] = []
    for package, source in sources:
        package_destination = destination / "app" / package
        package_destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(
            source / "app" / package,
            package_destination,
            ignore=shutil.ignore_patterns(
                "__pycache__", "*.pyc", ".pytest_cache", ".ruff_cache"
            ),
        )
        sections.append(
            _provenance_section(package, source, Path("vendor/cliver_playbook"))
        )
        print(f"Vendored {source} to {destination}")
        print(f"Import path: cliver_playbook.app.{package}")
        print(
            f'- Import check: python -c "import cliver_playbook.app.{package} as m; '
            'print(m.__file__)" must print a path under vendor/.'
        )
        print(
            "  Do not also install that distribution from PyPI: the installed "
            "copy can shadow this tree."
        )

    provenance = _append_provenance(vendor_root, sections)
    print(
        f"Add the vendor root ({vendor_root}) to the project's import path "
        "in pyproject.toml."
    )
    print(f"Provenance: {provenance}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
