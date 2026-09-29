"""Ports (interfaces) for provider parser adapters.

Concrete implementations live in ``adapters.inbound.ingestion``.
"""

from __future__ import annotations

from typing import Any, Protocol

from rosalind.domain.person import PersonObservation


class PersonParser(Protocol):
    resource_type: str

    def external_id(self, payload: dict[str, Any]) -> str: ...

    def source_etag(self, payload: dict[str, Any]) -> str | None: ...

    def parse(self, payload: dict[str, Any]) -> PersonObservation: ...
