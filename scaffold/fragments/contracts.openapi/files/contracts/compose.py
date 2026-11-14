#!/usr/bin/env python3
"""Compose contracts/base/openapi.yaml with contracts/modules/*.yaml.

Usage:
    python3 contracts/compose.py
    python3 contracts/compose.py --check
"""

from __future__ import annotations

import copy
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent
BASE = ROOT / "base" / "openapi.yaml"
OUT = ROOT / "openapi.yaml"
MODULES = ROOT / "modules"


def merge(base: dict, extra: dict, source: Path) -> None:
    for key, value in extra.items():
        if key not in base:
            base[key] = copy.deepcopy(value)
        elif isinstance(base[key], dict) and isinstance(value, dict):
            merge(base[key], value, source)
        elif isinstance(base[key], list) and isinstance(value, list):
            base[key].extend(copy.deepcopy(value))
        else:
            raise SystemExit(f"{source}: OpenAPI conflict at {key!r}")


def main(argv: list[str]) -> int:
    if not BASE.is_file():
        raise SystemExit(f"{BASE}: missing base contract")
    base = yaml.safe_load(BASE.read_text(encoding="utf-8")) or {}
    if not isinstance(base, dict):
        raise SystemExit(f"{BASE}: contract must be a mapping")
    for path in sorted(MODULES.glob("*.yaml")):
        extra = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        if not isinstance(extra, dict):
            raise SystemExit(f"{path}: fragment must be a mapping")
        merge(base, extra, path)
    rendered = yaml.safe_dump(base, sort_keys=False)
    if "--check" in argv[1:]:
        if not OUT.is_file() or OUT.read_text(encoding="utf-8") != rendered:
            print("contracts/openapi.yaml is stale; run `make contracts`", file=sys.stderr)
            return 1
        return 0
    OUT.write_text(rendered, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
