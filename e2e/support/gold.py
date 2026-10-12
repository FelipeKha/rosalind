"""Load and validate the version-controlled email-RAG gold query set."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml

GOLD_PATH = Path(__file__).resolve().parents[1] / "gold" / "email_rag_cases.yaml"


@dataclass(frozen=True)
class Evidence:
    message_id: str
    fact: str | None = None


@dataclass(frozen=True)
class GoldCase:
    id: str
    query: str
    behavior: str
    evidence: tuple[Evidence, ...]
    any_of: bool
    min_rank: int | None
    required_facts: tuple[str, ...]
    answerable: bool = True


def load_gold(path: Path = GOLD_PATH) -> list[GoldCase]:
    data = yaml.safe_load(path.read_text())
    cases: list[GoldCase] = []
    for raw in data["cases"]:
        cases.append(
            GoldCase(
                id=raw["id"],
                query=raw["query"],
                behavior=raw.get("behavior", ""),
                evidence=tuple(
                    Evidence(message_id=e["message_id"], fact=e.get("fact"))
                    for e in raw.get("evidence", [])
                ),
                any_of=bool(raw.get("any_of", False)),
                min_rank=raw.get("min_rank"),
                required_facts=tuple(raw.get("required_facts", [])),
                answerable=bool(raw.get("answerable", True)),
            )
        )
    return cases
