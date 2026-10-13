"""The eval subsystem is one-way: production modules must not import it.

Eval lives in distributed locations; only those locations (and the composition
root + gated app factory) may reference eval modules.
"""

from __future__ import annotations

import re
from pathlib import Path

SRC = Path(__file__).resolve().parents[2] / "src" / "rosalind"

# Files/dirs allowed to import eval modules.
_ALLOWED_PREFIXES = (
    "application/eval/",
    "application/services/eval.py",
    "adapters/outbound/eval/",
    "adapters/inbound/http/routes/eval.py",
    "adapters/inbound/http/schemas/eval.py",
    "adapters/composition.py",
    "adapters/inbound/http/app.py",
)

_EVAL_MODULES = (
    "rosalind.application.eval",
    "rosalind.adapters.outbound.eval",
    "rosalind.adapters.inbound.http.routes.eval",
    "rosalind.adapters.inbound.http.schemas.eval",
)


def _imports_eval(text: str) -> bool:
    pattern = re.compile(
        r"(^\s*(?:from|import)\s+("
        + "|".join(re.escape(m) for m in _EVAL_MODULES)
        + r")\b)",
        re.MULTILINE,
    )
    return bool(pattern.search(text))


def test_production_does_not_import_eval() -> None:
    offenders: list[str] = []
    for path in SRC.rglob("*.py"):
        rel = path.relative_to(SRC).as_posix()
        if rel.startswith(_ALLOWED_PREFIXES):
            continue
        if _imports_eval(path.read_text()):
            offenders.append(rel)
    assert offenders == [], f"production modules import eval: {offenders}"
