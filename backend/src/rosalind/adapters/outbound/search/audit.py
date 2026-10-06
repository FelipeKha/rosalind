"""Structured-logging audit adapter for the Prepare step.

Phase 1 records Prepare outcomes to the log rather than a durable table; the
retrieval phases will settle what a persisted ``search_audit`` row must store.
The query vector is never logged (only the plan fingerprint and metadata).
"""

from __future__ import annotations

import logging

from rosalind.application.search.ports import AuditEvent

logger = logging.getLogger("rosalind.search.audit")

__all__ = ["LoggingAudit"]


class LoggingAudit:
    async def record(self, event: AuditEvent) -> None:
        logger.info(
            "search_prepare",
            extra={
                "request_id": str(event.request_id),
                "audit_id": str(event.audit_id),
                "account_id": str(event.account_id),
                "client_id": event.client_id,
                "source_account_ids": sorted(str(i) for i in event.source_account_ids),
                "fingerprint": event.fingerprint,
                "mode_requested": event.mode_requested,
                "mode_effective": event.mode_effective,
                "index_version": event.index_version,
                "embedding_model": event.embedding_model,
                "embedding_version": event.embedding_version,
                "warnings": [warning.code.value for warning in event.warnings],
                "short_circuit_reason": event.short_circuit_reason,
                "timings_ms": _timings(event),
            },
        )


def _timings(event: AuditEvent) -> dict[str, float | None] | None:
    if event.timings is None:
        return None
    return {
        "validate_ms": event.timings.validate_ms,
        "resolve_ms": event.timings.resolve_ms,
        "embed_ms": event.timings.embed_ms,
        "total_ms": event.timings.total_ms,
    }
