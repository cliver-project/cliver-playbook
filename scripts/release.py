#!/usr/bin/env python3
"""Cut and push one release of the whole library.

Usage:
    python3 scripts/release.py [--version X.Y.Z] [--dry-run] [--no-push] [--skip-checks]

The version must already be bumped past the latest release tag. Without
``--version`` the script verifies the bump in the manifests; with ``--version``
it aligns every module and every inter-module dependency pin first. It then
runs the release checks, commits the bump if needed, creates the annotated tag,
and pushes the branch and tag (the tag triggers the PyPI workflow).
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import version as version_tool

ROOT = Path(__file__).resolve().parent.parent
# The release tag is the version itself. A leading "v" on an old tag is still
# parsed so the latest release can be found across the convention change.
LEGACY_TAG_PREFIX = "v"
VERSION_PATTERN = re.compile(r"(?:(\d+)\.(\d+)\.(\d+))(?:(a|b|rc)(\d+))?")
PRE_RELEASE_RANK = {"a": 0, "b": 1, "rc": 2, None: 3}
RELEASE_CHECKS = ("check", "verify-reference", "release-check")
LOCKFILES = ("uv.lock", "pnpm-lock.yaml")


def _parse_version(text: str) -> tuple[int, int, int, int, int]:
    """Parse X.Y.Z[abcN]; a release sorts after its pre-releases."""
    value = text.removeprefix(LEGACY_TAG_PREFIX)
    match = VERSION_PATTERN.fullmatch(value)
    if not match:
        raise ValueError(f"invalid version {text!r}; expected X.Y.Z")
    major, minor, patch, label, pre = match.groups()
    return (
        int(major),
        int(minor),
        int(patch),
        PRE_RELEASE_RANK[label],
        int(pre) if pre is not None else 0,
    )


def _latest_release(tags: list[str]) -> str | None:
    """The highest valid release version among ``v*`` tags."""
    versions: list[tuple[tuple[int, int, int, int, int], str]] = []
    for tag in tags:
        try:
            parsed = _parse_version(tag)
        except ValueError:
            continue
        versions.append((parsed, tag.removeprefix(LEGACY_TAG_PREFIX)))
    return max(versions)[1] if versions else None


def _decide_version(
    current: str, latest: str | None, requested: str | None
) -> tuple[str | None, str | None]:
    """Return (release version, error); the error asks for a version bump."""
    try:
        current_parsed = _parse_version(current)
    except ValueError as exc:
        return None, str(exc)

    if requested is not None:
        try:
            requested_parsed = _parse_version(requested)
        except ValueError as exc:
            return None, str(exc)
        if requested_parsed == current_parsed:
            if latest is None or current_parsed > _parse_version(latest):
                return requested, None
            return None, (
                f"version {current} is not bumped past tag {latest}; "
                "bump the version first"
            )
        if latest is not None and requested_parsed <= _parse_version(latest):
            return None, (
                f"version {requested} must be greater than the latest release "
                f"tag {latest}; bump the version first"
            )
        if requested_parsed < current_parsed:
            return None, (
                f"version {requested} is lower than the current version {current}"
            )
        return requested, None

    if latest is None:
        return current, None
    latest_parsed = _parse_version(latest)
    if current_parsed < latest_parsed:
        return None, (
            f"current version {current} is older than the latest release "
            f"tag {latest}; bump the version forward"
        )
    if current_parsed == latest_parsed:
        return None, (
            f"version {current} is not bumped past tag {latest}; "
            f"run `make version-set VERSION=X.Y.Z` first"
        )
    return current, None


def _retry_status(
    current: str,
    latest: str | None,
    requested: str | None,
    tag_commit: str | None,
    head: str,
    clean: bool,
    published: bool,
) -> tuple[bool, str | None]:
    """Return (is_retry, refusal) for a tag already at the current version.

    Re-running after a failed push is allowed when the tag is on HEAD, the
    tree is clean, and the tag was never published. A published tag, a tag on
    another commit, or a dirty tree means the version was not bumped. A
    request for a different version is not a retry and is left to the version
    decision.
    """
    if latest != current or (requested is not None and requested != current):
        return False, None
    if tag_commit != head:
        return (
            False,
            f"tag {current} already exists on another commit; choose a new version",
        )
    if not clean:
        return False, (
            f"tag {current} is on HEAD but the tree has pending changes; "
            "commit or stash them first"
        )
    if published:
        return False, (
            f"version {current} is already released as tag {current}; bump the "
            "version first (`make version-set VERSION=X.Y.Z`)"
        )
    return True, None


def _managed_path(path: str) -> bool:
    """True for files a version bump may touch."""
    normalized = path.strip().strip('"')
    if normalized in LOCKFILES:
        return True
    return normalized in {
        manifest.relative_to(ROOT).as_posix()
        for manifest in version_tool._manifest_paths(ROOT)
    }


def _git(*args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", str(ROOT), *args],
        text=True,
        capture_output=True,
        check=check,
    )


def _git_output(*args: str) -> str:
    return _git(*args).stdout.strip()


def _tag_commit(tag: str) -> str | None:
    result = _git(
        "rev-parse", "-q", "--verify", f"refs/tags/{tag}^{{commit}}", check=False
    )
    return result.stdout.strip() if result.returncode == 0 else None


def _tag_published(tag: str) -> bool:
    """True when origin already carries the tag; an unreachable origin is not a retry blocker."""
    result = _git("ls-remote", "--tags", "origin", f"refs/tags/{tag}", check=False)
    return result.returncode == 0 and bool(result.stdout.strip())


def _changed_paths() -> list[str]:
    output = _git("status", "--porcelain", "--untracked-files=all").stdout
    paths: list[str] = []
    for line in output.splitlines():
        path = line[3:]
        if " -> " in path:
            path = path.split(" -> ", 1)[1]
        paths.append(path.strip().strip('"'))
    return paths


def _run(command: list[str]) -> int:
    print(f"==> {' '.join(command)}")
    return subprocess.run(command, check=False, cwd=ROOT).returncode


def _release(args: argparse.Namespace) -> int:
    # Every module and every inter-module pin must already agree. The release
    # target never guesses a version: alignment is checked before anything runs.
    alignment = version_tool.check_versions(ROOT)
    if alignment:
        print("versions are not aligned across the modules:", file=sys.stderr)
        for error in alignment:
            print(f"  {error}", file=sys.stderr)
        print("Run `make version-set VERSION=X.Y.Z` first.", file=sys.stderr)
        return 1

    versions = set(version_tool.collect_versions(ROOT).values())
    current = versions.pop()
    latest = _latest_release(_git_output("tag", "--list").splitlines())

    # A tag at the current version is a retry only when it points at HEAD and
    # the tree is clean (for example, the push failed after tagging). Any other
    # tag at the current version means the version was never bumped.
    published = (
        latest == current
        and (args.version is None or args.version == current)
        and _tag_published(current)
    )
    retry, refusal = _retry_status(
        current,
        latest,
        args.version,
        _tag_commit(current),
        _git_output("rev-parse", "HEAD"),
        not _changed_paths(),
        published,
    )
    if refusal:
        print(refusal, file=sys.stderr)
        return 1

    target, error = _decide_version(current, latest, args.version)
    if retry:
        target, error = current, None
    if error or target is None:
        print(error or "could not determine the release version", file=sys.stderr)
        print("Bump the version first, then run `make release` again:", file=sys.stderr)
        print("  make version-set VERSION=X.Y.Z", file=sys.stderr)
        print("  git add -A && git commit -m 'release: X.Y.Z'", file=sys.stderr)
        print(
            "Or let the release target align everything: `make release VERSION=X.Y.Z`.",
            file=sys.stderr,
        )
        return 1

    tag = target
    existing_tag = _git("rev-parse", "-q", "--verify", f"refs/tags/{tag}", check=False)
    if existing_tag.returncode == 0:
        tagged_commit = _git_output("rev-parse", f"refs/tags/{tag}^{{commit}}")
        if tagged_commit != _git_output("rev-parse", "HEAD"):
            print(
                f"tag {tag} already exists on another commit; choose a new version",
                file=sys.stderr,
            )
            return 1

    if args.dry_run:
        print(f"Release {tag}")
        if args.version is not None:
            print(f"  align every module and inter-module pin to {target}")
            print("  run `uv lock` and `pnpm install --lockfile-only`")
        if not args.skip_checks:
            for target_name in RELEASE_CHECKS:
                print(f"  make {target_name}")
        print("  commit the version bump (if any)")
        print(f"  create annotated tag {tag}")
        if not args.no_push:
            print("  push HEAD and the tag to origin")
        print("dry run: nothing changed")
        return 0

    # Refuse unrelated working-tree changes before the long checks and before
    # any file is rewritten: a release commit contains the version bump only.
    unmanaged = [path for path in _changed_paths() if not _managed_path(path)]
    if unmanaged:
        print("working tree has changes outside the version bump:", file=sys.stderr)
        for path in unmanaged:
            print(f"  {path}", file=sys.stderr)
        print("Commit or stash them before releasing.", file=sys.stderr)
        return 1

    if args.version is not None:
        try:
            changed = version_tool.set_version(ROOT, target)
        except (OSError, TypeError, ValueError, RuntimeError) as exc:
            print(str(exc), file=sys.stderr)
            return 1
        for path in changed:
            print(f"aligned {path}")
        for command in (["uv", "lock"], ["pnpm", "install", "--lockfile-only"]):
            if _run(command) != 0:
                print(f"command failed: {' '.join(command)}", file=sys.stderr)
                return 1

    if not args.skip_checks:
        for target_name in RELEASE_CHECKS:
            if _run(["make", target_name]) != 0:
                print(f"release check failed: make {target_name}", file=sys.stderr)
                return 1

    alignment = version_tool.check_versions(ROOT, tag)
    if alignment:
        print("release version does not match every module:", file=sys.stderr)
        for error in alignment:
            print(f"  {error}", file=sys.stderr)
        return 1

    if _changed_paths():
        _git("add", "-A")
        _git(
            "commit",
            "-m",
            f"release: {tag}\n\nCo-Authored-By: Claude Code <noreply@anthropic.com>",
        )
        print(f"committed the version bump for {tag}")

    existing_tag = _git("rev-parse", "-q", "--verify", f"refs/tags/{tag}", check=False)
    if existing_tag.returncode == 0:
        print(f"tag {tag} already exists on HEAD")
    else:
        _git("tag", "-a", tag, "-m", f"cliver-playbook {tag}")
        print(f"created tag {tag}")

    if args.no_push:
        print(
            f"--no-push: publish later with `git push origin HEAD` and `git push origin {tag}`"
        )
        return 0

    if _git("remote", "get-url", "origin", check=False).returncode != 0:
        print("no 'origin' remote: the tag is local only", file=sys.stderr)
        return 1
    for ref in ("HEAD", tag):
        if _run(["git", "push", "origin", ref]) != 0:
            print(f"push failed for {ref}: the tag is local only", file=sys.stderr)
            return 1
    print(f"pushed {tag}; the Release workflow publishes every module")
    return 0


def _self_test() -> int:
    assert _parse_version("0.1.0") < _parse_version("0.2.0")
    assert _parse_version("0.9.0") < _parse_version("0.10.0")
    assert (
        _parse_version("0.2.0a1")
        < _parse_version("0.2.0b1")
        < _parse_version("0.2.0rc1")
        < _parse_version("0.2.0")
    )
    assert _parse_version("v0.2.0") == _parse_version("0.2.0")
    try:
        _parse_version("main")
    except ValueError:
        pass
    else:
        raise AssertionError("accepted a non-version")

    assert _latest_release(["0.1.0", "0.10.0", "v0.9.0", "junk"]) == "0.10.0"
    assert _latest_release([]) is None

    assert _decide_version("0.1.0", None, None) == ("0.1.0", None)
    assert _decide_version("0.2.0", "0.1.0", None) == ("0.2.0", None)
    version, error = _decide_version("0.1.0", "0.1.0", None)
    assert version is None and "not bumped" in (error or "")
    version, error = _decide_version("0.1.0", "0.1.0", "0.1.0")
    assert version is None and "not bumped" in (error or "")
    assert _decide_version("0.1.0", "0.1.0", "0.2.0") == ("0.2.0", None)
    assert _decide_version("0.1.0", None, "0.1.0") == ("0.1.0", None)
    assert _decide_version("0.3.0", "0.2.0", "0.3.0") == ("0.3.0", None)
    version, error = _decide_version("0.1.0", "0.2.0", None)
    assert version is None and "older" in (error or "")

    assert _retry_status("0.1.0", None, None, None, "abc", True, False) == (False, None)
    assert _retry_status("0.1.0", "0.1.0", None, "abc", "abc", True, False) == (
        True,
        None,
    )
    assert _retry_status("0.1.0", "0.1.0", "0.1.0", "abc", "abc", True, False) == (
        True,
        None,
    )
    retry, refusal = _retry_status("0.1.0", "0.1.0", None, "old", "abc", True, False)
    assert not retry and "another commit" in (refusal or "")
    retry, refusal = _retry_status("0.1.0", "0.1.0", None, "abc", "abc", False, False)
    assert not retry and "pending changes" in (refusal or "")
    retry, refusal = _retry_status("0.1.0", "0.1.0", None, "abc", "abc", True, True)
    assert not retry and "already released" in (refusal or "")
    assert _retry_status("0.1.0", "0.1.0", "0.2.0", "old", "abc", False, False) == (
        False,
        None,
    )

    assert _managed_path("uv.lock")
    assert _managed_path("packages/backend/cliver-playbook-app-basic/pyproject.toml")
    assert not _managed_path("README.md")

    print("self-test: OK")
    return 0


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--version", help="new shared version; aligns every module")
    parser.add_argument("--dry-run", action="store_true", help="print steps only")
    parser.add_argument("--no-push", action="store_true", help="tag locally only")
    parser.add_argument("--skip-checks", action="store_true", help="skip make checks")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args(argv[1:])

    if args.self_test:
        return _self_test()
    return _release(args)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
