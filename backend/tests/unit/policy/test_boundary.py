from __future__ import annotations

import ast
from pathlib import Path

POLICY_ROOT = Path(__file__).resolve().parents[3] / "src" / "rosalind" / "policy"

FORBIDDEN_PREFIXES = (
    "rosalind.adapters.composition",
    "rosalind.adapters.inbound",
    "rosalind.adapters.outbound.eval",
    "rosalind.adapters.outbound.google",
    "rosalind.adapters.outbound.object_storage",
    "rosalind.adapters.outbound.search",
    "rosalind.application.eval",
    "rosalind.application.search",
    "rosalind.application.services",
)


def _imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text())
    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            modules.add(node.module)
    return modules


def test_policy_service_never_imports_the_rag_stack() -> None:
    violations: list[str] = []
    for path in POLICY_ROOT.rglob("*.py"):
        if "migrations" in path.parts:
            continue
        for module in _imports(path):
            if module.startswith(FORBIDDEN_PREFIXES):
                violations.append(f"{path.relative_to(POLICY_ROOT)}: {module}")

    assert violations == []
