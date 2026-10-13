"""Search trace recorder: one content-free summary event per search run.

Logs the minimal ``SearchTrace`` projection as a single structured INFO event
and, when a session factory is wired, persists it to ``search.request_log``.
Recording is best-effort: a logging or persistence failure must never fail the
search itself.

Never logs or persists query text, filter values (only names/sizes), or chunk
text. See ``rosalind.logging`` for the formatter and correlation context.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

from sqlalchemy.orm import Session

from rosalind.adapters.outbound.persistence import models
from rosalind.application.search.trace import TraceSummary
from rosalind.logging import log_context

logger = logging.getLogger("rosalind.search.trace")

__all__ = ["SearchTraceRecorder", "flush_old_request_logs"]


class SearchTraceRecorder:
    """Records a search summary to the log and, optionally, ``search.request_log``."""

    def __init__(self, session_factory: Callable[[], Session] | None = None) -> None:
        self._session_factory = session_factory

    async def record(self, summary: TraceSummary) -> None:
        with log_context(
            request_id=str(summary.request_id),
            audit_id=str(summary.audit_id),
            account_id=str(summary.account_id),
            plan_fingerprint=summary.plan_fingerprint,
        ):
            logger.info("search_request", extra=_log_fields(summary))

        if self._session_factory is not None:
            try:
                self._persist(summary)
            except Exception:
                logger.warning("search_request_log_persist_failed", exc_info=True)

    def _persist(self, summary: TraceSummary) -> None:
        factory = self._session_factory
        if factory is None:
            return
        row = models.SearchRequestLog(
            account_id=summary.account_id,
            request_id=summary.request_id,
            audit_id=summary.audit_id,
            client_id=summary.client_id,
            plan_fingerprint=summary.plan_fingerprint,
            mode_requested=summary.mode_requested,
            mode_effective=summary.mode_effective,
            strategy=summary.strategy,
            index_version=summary.index_version,
            embedding_model=summary.embedding_model,
            embedding_version=summary.embedding_version,
            reranker_version=summary.reranker_version,
            filter_names=list(summary.filter_names),
            filter_sizes=summary.filter_sizes,
            lexical_count=summary.lexical_count,
            lexical_exhausted=summary.lexical_exhausted,
            lexical_filter_path=summary.lexical_filter_path,
            semantic_count=summary.semantic_count,
            semantic_complete=summary.semantic_complete,
            semantic_filter_path=summary.semantic_filter_path,
            semantic_scan_limit_hit=summary.semantic_scan_limit_hit,
            fused_count=summary.fused_count,
            dropped_by_item_cap=summary.dropped_by_item_cap,
            rerank_applied=summary.rerank_applied,
            rerank_model=summary.rerank_model,
            result_count=summary.result_count,
            warnings=list(summary.warnings),
            degraded=summary.degraded,
            timings_ms=summary.timings_ms,
            returned_chunk_ids=list(summary.returned_chunk_ids),
            returned_item_ids=list(summary.returned_item_ids),
        )
        with factory() as session:
            session.add(row)
            session.commit()


def flush_old_request_logs(session: Session, *, retention_days: int) -> int:
    """Delete ``search.request_log`` rows older than ``retention_days``.

    Returns the number of rows deleted. Callers own the transaction; this is the
    hook a scheduled job (or an operator) uses to enforce retention.
    """
    from datetime import UTC, datetime, timedelta

    from sqlalchemy import delete

    cutoff = datetime.now(UTC) - timedelta(days=retention_days)
    result = session.execute(
        delete(models.SearchRequestLog).where(
            models.SearchRequestLog.created_at < cutoff
        )
    )
    return int(result.rowcount or 0)  # type: ignore[attr-defined]


def _log_fields(summary: TraceSummary) -> dict[str, Any]:
    """Flat, primitive fields for the log record. Never filter values or text."""
    return {
        "mode_requested": summary.mode_requested,
        "mode_effective": summary.mode_effective,
        "strategy": summary.strategy,
        "index_version": summary.index_version,
        "embedding_model": summary.embedding_model,
        "embedding_version": summary.embedding_version,
        "reranker_version": summary.reranker_version,
        "filter_names": list(summary.filter_names),
        "filter_sizes": summary.filter_sizes,
        "lexical_count": summary.lexical_count,
        "lexical_exhausted": summary.lexical_exhausted,
        "lexical_filter_path": summary.lexical_filter_path,
        "semantic_count": summary.semantic_count,
        "semantic_complete": summary.semantic_complete,
        "semantic_filter_path": summary.semantic_filter_path,
        "semantic_scan_limit_hit": summary.semantic_scan_limit_hit,
        "fused_count": summary.fused_count,
        "dropped_by_item_cap": summary.dropped_by_item_cap,
        "rerank_applied": summary.rerank_applied,
        "rerank_model": summary.rerank_model,
        "result_count": summary.result_count,
        "warnings": list(summary.warnings),
        "degraded": summary.degraded,
        "timings_ms": summary.timings_ms,
        "returned_chunk_ids": [str(cid) for cid in summary.returned_chunk_ids],
        "returned_item_ids": [str(iid) for iid in summary.returned_item_ids],
    }
