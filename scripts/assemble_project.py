#!/usr/bin/env python3
"""Plan the assembly of a new project from cliver-playbook packages.

P0 is deliberately dry-run only: the planner prints what would be composed and
the skill performs the assembly by hand until the generated skeleton exists.
"""

from __future__ import annotations

import argparse
import json
import sys

PROFILES = {
    "minimal": {
        "backend": ["cliver-playbook-app-basic"],
        "frontend": ["cliver-playbook-app-basic"],
    },
    "web": {
        "backend": ["cliver-playbook-app-basic", "cliver-playbook-app-user"],
        "frontend": ["cliver-playbook-app-basic", "cliver-playbook-app-user"],
    },
    "rag": {
        "backend": [
            "cliver-playbook-app-basic",
            "cliver-playbook-app-user",
            "cliver-playbook-app-rag",
        ],
        "frontend": [
            "cliver-playbook-app-basic",
            "cliver-playbook-app-user",
            "cliver-playbook-app-rag",
        ],
    },
    "mcp": {
        "backend": [
            "cliver-playbook-app-basic",
            "cliver-playbook-app-user",
            "cliver-playbook-app-rag",
            "cliver-playbook-app-mcp",
        ],
        "frontend": [
            "cliver-playbook-app-basic",
            "cliver-playbook-app-user",
            "cliver-playbook-app-rag",
            "cliver-playbook-app-mcp",
        ],
    },
}
MODES = ("compose", "vendor", "generate")


def build_plan(profile: str, mode: str) -> dict:
    """Return the packages and ordered steps for a profile/mode combination."""
    if profile not in PROFILES:
        raise ValueError(f"unknown profile {profile!r}; choose from {sorted(PROFILES)}")
    if mode not in MODES:
        raise ValueError(f"unknown mode {mode!r}; choose from {list(MODES)}")

    selected = PROFILES[profile]
    backend = list(selected["backend"])
    frontend = list(selected["frontend"])
    steps = [
        "Create the project skeleton (workspace manifests, Makefile, .gitignore)",
        f"Add backend packages: {', '.join(backend)}",
        f"Add frontend packages: {', '.join(frontend)}",
        "Wire routers, settings, and migration chains",
        "Wire frontend routes and i18n",
        "Write project-manifest.yaml and validate it",
        "Run lint, tests, build, and the boot smoke",
    ]
    return {
        "profile": profile,
        "mode": mode,
        "backend_packages": backend,
        "frontend_packages": frontend,
        "steps": steps,
    }


def _self_test() -> int:
    plan = build_plan("minimal", "compose")
    assert plan["backend_packages"] == ["cliver-playbook-app-basic"]
    assert plan["frontend_packages"] == ["cliver-playbook-app-basic"]

    plan = build_plan("mcp", "compose")
    assert set(plan["backend_packages"]) == {
        "cliver-playbook-app-basic",
        "cliver-playbook-app-user",
        "cliver-playbook-app-rag",
        "cliver-playbook-app-mcp",
    }
    print("self-test: OK")
    return 0


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", choices=sorted(PROFILES))
    parser.add_argument("--mode", choices=MODES, default="compose")
    parser.add_argument("--target", help="directory the assembled project will use")
    action = parser.add_mutually_exclusive_group()
    action.add_argument("--dry-run", action="store_true", help="print the plan")
    action.add_argument(
        "--apply",
        action="store_true",
        help="create the project (not implemented in P0)",
    )
    action.add_argument("--self-test", action="store_true")
    args = parser.parse_args(argv[1:])

    if args.self_test:
        return _self_test()

    if args.apply:
        print(
            "--apply is not implemented in P0; run with --dry-run and let the "
            "assemble-project skill perform the steps.",
            file=sys.stderr,
        )
        return 1

    if not args.dry_run:
        parser.error("choose --dry-run (P0) or --self-test")
    if not args.profile:
        parser.error("--profile is required with --dry-run")
    if not args.target:
        parser.error("--target is required with --dry-run")

    try:
        plan = build_plan(args.profile, args.mode)
    except ValueError as exc:
        parser.error(str(exc))

    print(json.dumps(plan, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
