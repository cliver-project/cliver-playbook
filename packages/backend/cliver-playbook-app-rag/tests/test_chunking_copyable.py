"""Guard: the chunking subpackage must be copyable into another project.

The package is deliberately importable without the rest of
``cliver_playbook``. Every intra-package import is therefore relative;
an absolute ``cliver_playbook`` import would work inside this
repository but break the copy/import use case that the subpackage
documentation promises.
"""

from __future__ import annotations

import ast
from pathlib import Path

CHUNKING_DIR = (
    Path(__file__).resolve().parents[1] / "src" / "cliver_playbook" / "app" / "rag" / "chunking"
)


def _absolute_cliver_imports(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    offenders: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == "cliver_playbook" or alias.name.startswith("cliver_playbook."):
                    offenders.append(f"{path.name}:{node.lineno}: import {alias.name}")
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                continue
            module = node.module or ""
            if module == "cliver_playbook" or module.startswith("cliver_playbook."):
                offenders.append(f"{path.name}:{node.lineno}: from {module}")
    return offenders


def test_chunking_uses_only_relative_internal_imports() -> None:
    offenders: list[str] = []
    for path in sorted(CHUNKING_DIR.glob("*.py")):
        offenders.extend(_absolute_cliver_imports(path))
    assert offenders == []
