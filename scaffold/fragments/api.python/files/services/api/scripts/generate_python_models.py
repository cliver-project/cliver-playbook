#!/usr/bin/env python3
"""Generate project-owned Python models from contracts/openapi.yaml.

Usage:
    cd services/api && uv run python scripts/generate_python_models.py
    cd services/api && uv run python scripts/generate_python_models.py --check
"""

from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

API_ROOT = Path(__file__).resolve().parents[1]
PROJECT_ROOT = API_ROOT.parents[1]
CONTRACT = PROJECT_ROOT / "contracts" / "openapi.yaml"
OUTPUT = PROJECT_ROOT / "contracts" / "generated" / "python" / "models.py"


def _command(output: Path) -> list[str]:
    executable = shutil.which("datamodel-codegen")
    if executable is None:
        raise SystemExit("datamodel-codegen is missing; run `uv sync` in services/api")
    return [
        executable,
        "--input",
        str(CONTRACT),
        "--output",
        str(output),
        "--input-file-type",
        "openapi",
        "--output-model-type",
        "pydantic_v2.BaseModel",
        "--disable-timestamp",
        "--use-annotated",
        "--formatters",
        "builtin",
    ]


def main(argv: list[str]) -> int:
    if not CONTRACT.is_file():
        raise SystemExit(f"{CONTRACT}: composed contract is missing; run `make contracts`")
    check = "--check" in argv
    with tempfile.TemporaryDirectory() as temporary:
        target = Path(temporary) / "models.py"
        subprocess.run(_command(target), check=True)
        generated = target.read_text(encoding="utf-8")
    if check:
        current = OUTPUT.read_text(encoding="utf-8") if OUTPUT.is_file() else ""
        if current != generated:
            print(
                "contracts/generated/python/models.py is stale; run `make contracts`",
                file=sys.stderr,
            )
            return 1
        return 0
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(generated, encoding="utf-8")
    print("contracts/generated/python/models.py generated")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
