#!/usr/bin/env python3
"""Validate the agent skills shipped in skills/.

Usage:
    uv run --with pyyaml python scripts/validate_skill.py --all
    uv run --with pyyaml python scripts/validate_skill.py skills/<name>
    uv run --with pyyaml python scripts/validate_skill.py --self-test

Each skill directory must contain a SKILL.md with Agent Skills frontmatter:
a lowercase hyphenated name that matches the directory, and a description of
at most 1024 characters. The body must not leak local absolute paths, every
reference/ or assets/ file it names must exist, and every manifest example in
assets/ must pass the project manifest validator.

Exit status is 0 when every skill is valid. Otherwise every problem is printed
on its own line to stderr and the exit status is 1.
"""

from __future__ import annotations

import re
import sys
import tempfile
from pathlib import Path
from typing import Any

import yaml

from validate_project_manifest import validate_manifest

NAME = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
FRONTMATTER = re.compile(r"^---\n(.*?)\n---\n", re.DOTALL)
SHIPPED_PATH = re.compile(
    r"(?<![\w/])((?:reference|assets)/[A-Za-z0-9][A-Za-z0-9._/-]*[A-Za-z0-9_/-])"
)
LOCAL_PATH = re.compile(r"(?:/Users/|/home/|/private/(?:tmp|var)/|[A-Za-z]:\\)")
FILE_SUFFIXES = {".md", ".yaml", ".yml", ".json", ".sh", ".py", ".ts", ".tsx", ".css"}


def _string_field(
    frontmatter: dict[str, Any],
    key: str,
    maximum: int | None,
    errors: list[str],
    *,
    required: bool = True,
) -> str | None:
    value = frontmatter.get(key)
    if value is None and not required:
        return None
    if not isinstance(value, str) or not value.strip():
        errors.append(f"frontmatter: {key} must be a non-empty string")
        return None
    if maximum is not None and len(value) > maximum:
        errors.append(f"frontmatter: {key} is longer than {maximum} characters")
        return None
    return value.strip()


def _validate_manifest_assets(skill_dir: Path, errors: list[str]) -> None:
    for path in sorted((skill_dir / "assets").glob("*manifest*.yaml")):
        try:
            data = yaml.safe_load(path.read_text(encoding="utf-8"))
        except (OSError, yaml.YAMLError) as exc:
            errors.append(f"{path.name}: cannot be read as YAML: {exc}")
            continue
        for error in validate_manifest(data):
            errors.append(f"{path.name}: {error}")


def validate_skill(skill_dir: Path) -> list[str]:
    """Return every problem with one skill directory."""
    errors: list[str] = []
    skill_file = skill_dir / "SKILL.md"
    if not skill_file.is_file():
        return [f"{skill_file}: missing"]

    try:
        text = skill_file.read_text(encoding="utf-8")
    except OSError as exc:
        return [f"{skill_file}: {exc}"]

    match = FRONTMATTER.match(text)
    if match is None:
        return ["frontmatter: SKILL.md must start with a YAML --- block"]

    try:
        frontmatter = yaml.safe_load(match.group(1))
    except yaml.YAMLError as exc:
        return [f"frontmatter: invalid YAML: {exc}"]
    if not isinstance(frontmatter, dict):
        return ["frontmatter: must be a mapping"]

    name = _string_field(frontmatter, "name", 64, errors)
    if name is not None:
        if not NAME.fullmatch(name):
            errors.append(
                "frontmatter: name must use lowercase letters, numbers, and "
                "single hyphens, and must not start or end with a hyphen"
            )
        if name != skill_dir.name:
            errors.append(
                f"frontmatter: name {name!r} does not match directory "
                f"{skill_dir.name!r}"
            )

    _string_field(frontmatter, "description", 1024, errors)
    _string_field(frontmatter, "license", None, errors, required=False)
    _string_field(frontmatter, "compatibility", 500, errors, required=False)

    body = text[match.end() :]
    if body.count("```") % 2:
        errors.append("body: unbalanced ``` fence")

    if LOCAL_PATH.search(body):
        errors.append("body: contains a local absolute path")

    for reference in sorted(set(SHIPPED_PATH.findall(body))):
        target = skill_dir / reference
        if target.suffix in FILE_SUFFIXES and not target.is_file():
            errors.append(f"body: references missing file {reference!r}")

    _validate_manifest_assets(skill_dir, errors)
    return errors


def skill_directories(root: Path) -> list[Path]:
    return sorted(path.parent for path in (root / "skills").glob("*/SKILL.md"))


def _write_skill(root: Path, name: str, body: str) -> Path:
    skill_dir = root / name
    (skill_dir / "reference").mkdir(parents=True)
    (skill_dir / "assets").mkdir()
    (skill_dir / "reference" / "notes.md").write_text("notes\n", encoding="utf-8")
    (skill_dir / "SKILL.md").write_text(
        f"---\nname: {name}\ndescription: Does a thing. Use when testing.\n"
        f"---\n\n# Test\n\n{body}\n",
        encoding="utf-8",
    )
    return skill_dir


def _self_test() -> int:
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)

        good = _write_skill(root, "good-skill", "See `reference/notes.md`.")
        assert validate_skill(good) == []

        bad_name = _write_skill(root, "bad-name", "ok")
        text = (bad_name / "SKILL.md").read_text(encoding="utf-8")
        (bad_name / "SKILL.md").write_text(
            text.replace("name: bad-name", "name: other-name"), encoding="utf-8"
        )
        assert validate_skill(bad_name), "accepted a name that does not match the directory"

        missing = _write_skill(root, "missing-ref", "See `reference/absent.md`.")
        assert validate_skill(missing), "accepted a missing reference"

        fence = _write_skill(root, "bad-fence", "```sh\necho hi\n")
        assert validate_skill(fence), "accepted an unbalanced fence"

        leak = _write_skill(root, "leak", "Run /home/someone/project/build.sh")
        assert validate_skill(leak), "accepted a local absolute path"

        manifest = _write_skill(root, "bad-manifest", "ok")
        (manifest / "assets" / "project-manifest.example.yaml").write_text(
            "project: example\n", encoding="utf-8"
        )
        assert validate_skill(manifest), "accepted an invalid manifest example"

    print("self-test: OK")
    return 0


def main(argv: list[str]) -> int:
    if argv[1:] == ["--self-test"]:
        return _self_test()

    if argv[1:] == ["--all"]:
        root = Path(__file__).resolve().parent.parent
        directories = skill_directories(root)
    elif len(argv) == 2:
        directories = [Path(argv[1])]
    else:
        print(
            "usage: validate_skill.py --all | <skill-dir> | --self-test",
            file=sys.stderr,
        )
        return 1

    if not directories:
        print("no skills found under skills/", file=sys.stderr)
        return 1

    failed = False
    for skill_dir in directories:
        errors = validate_skill(skill_dir)
        for error in errors:
            print(f"{skill_dir}: {error}", file=sys.stderr)
        failed = failed or bool(errors)
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
