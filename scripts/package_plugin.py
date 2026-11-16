#!/usr/bin/env python3
"""Build agent-platform plugin bundles from one portable source.

A plugin lives in ``plugins/<name>/``: one ``plugin.json`` (the single source
of truth), one standard Agent Skill under ``skill/``, and an optional
``connector/icon.svg``. The skill follows the open Agent Skills format
(agentskills.io), so its ``SKILL.md`` is portable as-is; the platforms differ
only in manifests and MCP transport spellings. This script renders each
target and packages it as a ZIP:

    claude-code   .claude-plugin/plugin.json + skills/ + .mcp.json
    codex         .codex-plugin/plugin.json  + skills/ + mcp.json
    workbuddy     connector-meta.json + mcp.json + icon + skills/<name>/SKILL.md
                  (WorkBuddy's extra frontmatter fields are injected here)

Usage:
    python scripts/package_plugin.py --check [--all | --app NAME]
    python scripts/package_plugin.py --package [--all | --app NAME] \
        [--out dist/plugins] [--mcp-url https://…]
    python scripts/package_plugin.py --self-test

``--check`` validates the source and every rendered target in memory without
writing anything; ``--package`` does the same, then writes the target trees
and one ZIP per target. Exit status is 1 on any validation error, with one
message per line on stderr.
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
import tempfile
import zipfile
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[1]
PLUGINS_DIR = ROOT / "plugins"
DEFAULT_OUT = ROOT / "dist" / "plugins"

KEBAB = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
VERSION = re.compile(r"^\d+\.\d+\.\d+(?:[-+][0-9A-Za-z.-]+)?$")
FRONTMATTER = re.compile(r"^---\n(.*?)\n---\n", re.DOTALL)
TARGETS = ("claude-code", "codex", "workbuddy")
# Secrets must never ship in a packaged plugin. These are the shapes a
# careless example would most plausibly leak; a real credential scanner
# belongs in CI as a separate gate.
SECRET_PATTERNS = (
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    re.compile(r"(?<![A-Za-z0-9])sk-[A-Za-z0-9]{16,}"),
    re.compile(r"(?<![A-Za-z0-9])AKIA[0-9A-Z]{16}(?![A-Za-z0-9])"),
    re.compile(r"(?<![A-Za-z0-9])ghp_[A-Za-z0-9]{20,}"),
    re.compile(r"(?i)bearer\s+[A-Za-z0-9._-]{24,}"),
)
WORKBUDDY_REQUIRED = (
    "name",
    "display_name",
    "display_name_en",
    "description",
    "description_zh",
    "description_en",
    "version",
    "author",
)


class PluginError(Exception):
    """The plugin source cannot be packaged as requested."""


# ---------------------------------------------------------------------------
# Small helpers (also exercised by --self-test)
# ---------------------------------------------------------------------------


def split_frontmatter(text: str) -> tuple[dict[str, Any], str]:
    """Return (frontmatter mapping, body) for a SKILL.md document."""
    match = FRONTMATTER.match(text)
    if match is None:
        raise PluginError("SKILL.md must start with YAML frontmatter")
    try:
        data = yaml.safe_load(match.group(1)) or {}
    except yaml.YAMLError as exc:
        raise PluginError(f"SKILL.md frontmatter is not YAML: {exc}") from None
    if not isinstance(data, dict):
        raise PluginError("SKILL.md frontmatter must be a mapping")
    return data, text[match.end() :]


def merge_frontmatter(frontmatter: dict[str, Any], extra: dict[str, Any], body: str) -> str:
    """Render frontmatter + ``extra`` (extra wins) and the body."""
    merged = {**frontmatter, **extra}
    header = yaml.safe_dump(merged, sort_keys=False, allow_unicode=True).rstrip()
    return f"---\n{header}\n---\n{body}"


def transport_config(target: str, server_key: str, url: str) -> dict[str, Any]:
    """The MCP declaration, spelled the way each platform expects it."""
    if target == "claude-code":
        entry: dict[str, Any] = {"type": "http", "url": url}
    elif target == "codex":
        entry = {"url": url}
    elif target == "workbuddy":
        entry = {"type": "streamableHttp", "url": url}
    else:  # pragma: no cover - guarded by the target list
        raise PluginError(f"unknown target {target!r}")
    return {"mcpServers": {server_key: entry}}


def secret_hits(path: str, text: str) -> list[str]:
    findings: list[str] = []
    for pattern in SECRET_PATTERNS:
        for match in pattern.finditer(text):
            findings.append(f"{path}: possible secret ({match.group(0)[:24]}…)")
    return findings


def is_kebab(value: Any) -> bool:
    return isinstance(value, str) and bool(KEBAB.fullmatch(value))


def semver(value: Any) -> bool:
    return isinstance(value, str) and bool(VERSION.fullmatch(value))


# ---------------------------------------------------------------------------
# Source loading and validation
# ---------------------------------------------------------------------------


class Plugin:
    """One plugin source tree, loaded and validated."""

    def __init__(self, directory: Path, *, mcp_url: str | None = None) -> None:
        self.directory = directory
        self.errors: list[str] = []
        manifest_path = directory / "plugin.json"
        try:
            self.manifest: dict[str, Any] = json.loads(manifest_path.read_text("utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise PluginError(f"{manifest_path}: cannot be read: {exc}") from None
        self._validate_manifest()
        self.skill_dir = self._find_skill_dir()
        self.skill_name = self.skill_dir.name
        self.skill_text = (self.skill_dir / "SKILL.md").read_text("utf-8")
        self.skill_frontmatter, self.skill_body = split_frontmatter(self.skill_text)
        self._validate_skill()
        mcp = self.manifest.get("mcp") or {}
        self.mcp_server_key = str(mcp.get("server_key") or self.name)
        url = mcp_url or str(mcp.get("default_url") or "")
        self.mcp_url = url
        self._validate_mcp(url)
        self._scan_secrets()

    # -- manifest ---------------------------------------------------------

    @property
    def name(self) -> str:
        return str(self.manifest.get("name", ""))

    def _validate_manifest(self) -> None:
        manifest = self.manifest
        if not is_kebab(manifest.get("name")):
            self.errors.append("plugin.json: name must be kebab-case")
        if not is_kebab(manifest.get("source")):
            self.errors.append("plugin.json: source must be kebab-case (connector id)")
        if not semver(manifest.get("version")):
            self.errors.append("plugin.json: version must be semver (X.Y.Z)")
        if not isinstance(manifest.get("author"), str) or not manifest["author"].strip():
            self.errors.append("plugin.json: author must be a non-empty string")
        for field in ("display_name", "description", "examples"):
            value = manifest.get(field)
            if not isinstance(value, dict) or not all(
                isinstance(value.get(locale), (str, list)) and value.get(locale)
                for locale in ("en", "zh")
            ):
                self.errors.append(f"plugin.json: {field} must carry non-empty en and zh")
        targets = manifest.get("targets")
        if not isinstance(targets, list) or not targets or set(targets) - set(TARGETS):
            self.errors.append(f"plugin.json: targets must be a subset of {list(TARGETS)}")
        mcp = manifest.get("mcp")
        if not isinstance(mcp, dict) or not isinstance(mcp.get("server_key"), str):
            self.errors.append("plugin.json: mcp.server_key is required")
        if not isinstance(mcp, dict) or not isinstance(mcp.get("default_url"), str):
            self.errors.append("plugin.json: mcp.default_url is required")

    # -- skill ------------------------------------------------------------

    def _find_skill_dir(self) -> Path:
        skills = sorted(
            path.parent for path in (self.directory / "skill").glob("*/SKILL.md")
        )
        if len(skills) != 1:
            raise PluginError(
                f"{self.directory}: skill/ must contain exactly one <name>/SKILL.md"
            )
        return skills[0]

    def _validate_skill(self) -> None:
        frontmatter = self.skill_frontmatter
        name = frontmatter.get("name")
        description = frontmatter.get("description")
        if not is_kebab(name) or len(str(name)) > 64:
            self.errors.append("SKILL.md: name must be kebab-case, at most 64 characters")
        elif name != self.skill_name:
            self.errors.append(
                f"SKILL.md: name {name!r} must match its directory {self.skill_name!r}"
            )
        if not isinstance(description, str) or not description.strip():
            self.errors.append("SKILL.md: description is required")
        elif len(description) > 1024:
            self.errors.append("SKILL.md: description must be at most 1024 characters")

    def _validate_mcp(self, url: str) -> None:
        if not url:
            self.errors.append("plugin.json: an MCP url is required (default_url or --mcp-url)")
            return
        if not url.startswith("https://"):
            self.errors.append(
                f"mcp url must be HTTPS (got {url!r}); WorkBuddy rejects plain HTTP"
            )

    def _scan_secrets(self) -> None:
        for path in sorted(self.directory.rglob("*")):
            if not path.is_file() or path.suffix in {".pyc"}:
                continue
            label = path.relative_to(self.directory).as_posix()
            try:
                self.errors.extend(secret_hits(label, path.read_text("utf-8")))
            except UnicodeDecodeError:
                continue  # binary asset (icon) — nothing textual to leak

    # -- rendering --------------------------------------------------------

    def skill_files(self) -> list[tuple[Path, str]]:
        """Every file of the skill, as (path relative to the skill root, text)."""
        files: list[tuple[Path, str]] = []
        for path in sorted(self.skill_dir.rglob("*")):
            if path.is_file() and path.suffix != ".pyc":
                files.append((path.relative_to(self.skill_dir), path.read_text("utf-8")))
        return files

    def render(self, target: str) -> dict[Path, str]:
        """The files of one target, keyed by path relative to the bundle root."""
        manifest = self.manifest
        name = self.name
        description = manifest["description"]["en"]
        display = manifest["display_name"]
        author = manifest["author"]
        files: dict[Path, str] = {}
        for relative, text in self.skill_files():
            files[Path("skills") / self.skill_name / relative] = text
        mcp = transport_config(target, self.mcp_server_key, self.mcp_url)
        if target == "claude-code":
            files[Path(".claude-plugin/plugin.json")] = _json(
                {
                    "name": name,
                    "version": manifest["version"],
                    "description": description,
                    "author": {"name": author},
                    **({"license": manifest["license"]} if manifest.get("license") else {}),
                }
            )
            files[Path(".mcp.json")] = _json(mcp)
        elif target == "codex":
            files[Path(".codex-plugin/plugin.json")] = _json(
                {
                    "name": name,
                    "version": manifest["version"],
                    "description": description,
                    "author": author,
                }
            )
            files[Path("mcp.json")] = _json(mcp)
        else:  # workbuddy
            files[Path("connector-meta.json")] = _json(
                {
                    "name": display["en"],
                    "name_zh": display["zh"],
                    "name_en": display["en"],
                    "description": description,
                    "description_zh": manifest["description"]["zh"],
                    "description_en": description,
                    "source": manifest["source"],
                    "type": "mcp",
                    "version": manifest["version"],
                    "examples_zh": manifest["examples"]["zh"],
                    "examples_en": manifest["examples"]["en"],
                }
            )
            files[Path("mcp.json")] = _json(mcp)
            icon = self.directory / "connector" / "icon.svg"
            if icon.is_file():
                files[Path("icon.svg")] = icon.read_text("utf-8")
            # WorkBuddy requires more frontmatter than the open spec; the
            # injected copy lives here, the source skill stays portable.
            workbuddy_skill = merge_frontmatter(
                self.skill_frontmatter,
                {
                    "display_name": display["zh"],
                    "display_name_en": display["en"],
                    "description_zh": manifest["description"]["zh"],
                    "description_en": description,
                    "version": manifest["version"],
                    "author": author,
                    "examples_zh": manifest["examples"]["zh"],
                    "examples_en": manifest["examples"]["en"],
                },
                self.skill_body,
            )
            files[Path("skills") / self.skill_name / "SKILL.md"] = workbuddy_skill
            merged, _body = split_frontmatter(workbuddy_skill)
            missing = [field for field in WORKBUDDY_REQUIRED if not merged.get(field)]
            if missing:
                self.errors.append(f"workbuddy: SKILL.md missing fields {missing}")
        return files


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2) + "\n"


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------


def discover(app: str | None) -> list[Path]:
    if app:
        directory = PLUGINS_DIR / app
        if not (directory / "plugin.json").is_file():
            raise PluginError(f"no plugin named {app!r} under {PLUGINS_DIR}")
        return [directory]
    return sorted(path.parent for path in PLUGINS_DIR.glob("*/plugin.json"))


def package_plugin(directory: Path, out: Path, *, mcp_url: str | None, write: bool) -> list[str]:
    plugin = Plugin(directory, mcp_url=mcp_url)
    if plugin.errors:
        return [f"{directory.name}: {error}" for error in plugin.errors]
    errors: list[str] = []
    targets = plugin.manifest["targets"]
    for target in targets:
        rendered = plugin.render(target)
        if plugin.errors:
            errors.extend(f"{directory.name}: {error}" for error in plugin.errors)
        bundle_name = plugin.name if target != "workbuddy" else plugin.manifest["source"]
        if not write:
            continue
        target_root = out / target
        bundle = target_root / bundle_name
        if bundle.exists():
            shutil.rmtree(bundle)
        for relative, text in rendered.items():
            destination = bundle / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_text(text, encoding="utf-8")
        archive = out / f"{plugin.name}-{target}-{plugin.manifest['version']}.zip"
        with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as zip_file:
            for path in sorted(bundle.rglob("*")):
                if path.is_file():
                    zip_file.write(path, path.relative_to(target_root).as_posix())
        print(f"built {archive.relative_to(ROOT)}")
    if not plugin.errors:
        print(f"ok    {directory.name} ({', '.join(targets)})")
    return errors


def self_test() -> int:
    assert is_kebab("governed-kb") and not is_kebab("Governed_KB")
    assert semver("0.1.0") and semver("1.2.3-rc.1") and not semver("1.0")
    assert transport_config("claude-code", "kb", "https://x.example/mcp") == {
        "mcpServers": {"kb": {"type": "http", "url": "https://x.example/mcp"}}
    }
    assert transport_config("codex", "kb", "https://x.example/mcp") == {
        "mcpServers": {"kb": {"url": "https://x.example/mcp"}}
    }
    assert transport_config("workbuddy", "kb", "https://x.example/mcp") == {
        "mcpServers": {"kb": {"type": "streamableHttp", "url": "https://x.example/mcp"}}
    }
    merged, body = split_frontmatter(
        merge_frontmatter({"name": "s"}, {"display_name": "技能", "version": "1.0.0"}, "\nBody\n")
    )
    assert merged["name"] == "s" and merged["display_name"] == "技能" and "Body" in body
    assert secret_hits("f", "token sk-abcdefghijklmnop1234") == [
        "f: possible secret (sk-abcdefghijklmnop1234…)"
    ]
    assert secret_hits("f", "plain text") == []

    # The real loading path: a plugin with a plain-HTTP URL and no en/zh copy
    # must be rejected, and a well-formed one accepted.
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp) / "demo"
        (root / "skill" / "demo").mkdir(parents=True)
        (root / "skill" / "demo" / "SKILL.md").write_text(
            "---\nname: demo\ndescription: A demo skill.\n---\n\nBody.\n", "utf-8"
        )
        manifest = {
            "name": "demo",
            "source": "demo",
            "version": "0.1.0",
            "author": "test",
            "display_name": {"en": "Demo", "zh": "演示"},
            "description": {"en": "Demo.", "zh": "演示。"},
            "examples": {"en": ["x"], "zh": ["x"]},
            "mcp": {"server_key": "demo", "default_url": "http://insecure.example/mcp"},
            "targets": ["claude-code"],
        }
        (root / "plugin.json").write_text(json.dumps(manifest), "utf-8")
        bad = Plugin(root)
        assert any("HTTPS" in error for error in bad.errors), bad.errors
        manifest["mcp"]["default_url"] = "https://secure.example/mcp"
        (root / "plugin.json").write_text(json.dumps(manifest), "utf-8")
        assert Plugin(root).errors == []
    print("self-test: OK")
    return 0


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--check", action="store_true", help="validate without writing")
    mode.add_argument("--package", action="store_true", help="write bundles and ZIPs")
    mode.add_argument("--self-test", action="store_true")
    parser.add_argument("--app", help="one plugin name under plugins/")
    parser.add_argument("--all", action="store_true", help="every plugin (default)")
    parser.add_argument("--out", default=str(DEFAULT_OUT), help="output directory")
    parser.add_argument("--mcp-url", help="override the connector URL for this build")
    args = parser.parse_args(argv[1:])

    if args.self_test:
        return self_test()
    try:
        directories = discover(args.app)
    except PluginError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    errors: list[str] = []
    for directory in directories:
        errors.extend(
            package_plugin(
                directory,
                Path(args.out),
                mcp_url=args.mcp_url,
                write=args.package,
            )
        )
    for error in errors:
        print(error, file=sys.stderr)
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
