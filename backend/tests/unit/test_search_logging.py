"""Log-capture tests for the search summary event.

The summary is content-free: it carries the plan fingerprint, versions, filter
names/sizes, per-stage counts, timings and returned IDs — never query text,
addresses, subjects or chunk text.
"""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
from datetime import UTC, datetime

from rosalind.adapters.outbound.search.trace_log import SearchTraceRecorder
from rosalind.application.search import (
    Budgets,
    GroupBy,
    IndexVersions,
    LexicalHit,
    LexicalQuery,
    LexicalResult,
    PreparedQuery,
    Presentation,
    RequestContext,
    ResolvedFilters,
    ResultView,
    Scope,
    SearchMode,
    SearchPlan,
    SearchStrategy,
    SortOrder,
)
from rosalind.application.search.assemble import SearchResultData
from rosalind.application.search.cursor import HmacCursorCodec
from rosalind.application.services.search_pipeline import SearchPipeline
from rosalind.domain.search import ChunkKind
from rosalind.logging import JsonFormatter

ACCOUNT = uuid.uuid4()
SA = uuid.uuid4()
CHUNK = uuid.uuid4()
ITEM = uuid.uuid4()

_SECRET_QUERY = "roof quote secret"
_SECRET_SENDER = "secret@example.com"

_WHEN = datetime(2026, 3, 17, 9, 32, tzinfo=UTC)


class _FakeLexical:
    async def retrieve(self, plan: SearchPlan) -> LexicalResult:
        return LexicalResult(
            hits=(LexicalHit(chunk_id=CHUNK, email_id=ITEM, rank=1, score=5.0),),
            exhausted=False,
            filter_path="pushdown",
            elapsed_ms=1.0,
        )


class _FakeSemantic:
    async def retrieve(self, plan: SearchPlan):
        raise AssertionError("semantic branch should not run in lexical mode")


class _FakeChunkText:
    async def get_rerank_texts(self, chunk_ids, mode):  # pragma: no cover
        raise AssertionError("rerank should not run")


class _FakeResultData:
    async def get_results(self, plan, chunk_ids, *, include_text):
        return tuple(
            SearchResultData(
                chunk_id=cid,
                item_id=ITEM,
                thread_id=None,
                chunk_kind=ChunkKind.EMAIL_BODY,
                occurred_at=_WHEN,
                sender_handle=_SECRET_SENDER,
                subject=_SECRET_QUERY,
                display_text=_SECRET_QUERY,
                attachment_name=None,
            )
            for cid in chunk_ids
        )


class _FakeListRetriever:
    async def list(self, plan):  # pragma: no cover
        raise AssertionError("list retriever should not run")


def _plan() -> SearchPlan:
    return SearchPlan(
        context=RequestContext(
            request_id=uuid.uuid4(), audit_id=uuid.uuid4(), client_id="test"
        ),
        scope=Scope(account_id=ACCOUNT, source_account_ids=frozenset({SA})),
        filters=ResolvedFilters(senders=frozenset({_SECRET_SENDER})),
        resolved_entities=(),
        query=PreparedQuery(lexical=LexicalQuery(terms=("roof",))),
        strategy=SearchStrategy.RANKED,
        mode_requested=SearchMode.LEXICAL,
        mode_effective=SearchMode.LEXICAL,
        presentation=Presentation(
            sort=SortOrder.RELEVANCE,
            group_by=GroupBy.MESSAGE,
            view=ResultView.SNIPPET,
            limit=10,
        ),
        budgets=Budgets(
            lexical_k=50, semantic_k=50, fused_k=40, rerank_k=30, window_k=10
        ),
        versions=IndexVersions(
            index_version="v1",
            embedding_model=None,
            embedding_version=None,
            reranker=None,
        ),
    )


class _CapturingHandler(logging.Handler):
    def __init__(self) -> None:
        super().__init__()
        self.setFormatter(JsonFormatter())
        self.records: list[dict] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.records.append(json.loads(self.format(record)))


def _run_capture(plan: SearchPlan) -> list[dict]:
    handler = _CapturingHandler()
    logger = logging.getLogger("rosalind.search.trace")
    previous_level = logger.level
    previous_propagate = logger.propagate
    previous_disabled = logger.disabled
    logger.setLevel(logging.INFO)
    logger.propagate = False
    logger.disabled = False
    logger.addHandler(handler)
    try:
        pipeline = SearchPipeline(
            lexical=_FakeLexical(),
            semantic=_FakeSemantic(),
            chunk_text=_FakeChunkText(),
            codec=HmacCursorCodec(b"key"),
            result_data=_FakeResultData(),
            list_retriever=_FakeListRetriever(),
            snippet_max_chars=200,
            trace_recorder=SearchTraceRecorder(),
        )
        asyncio.run(pipeline.run(plan))
    finally:
        logger.removeHandler(handler)
        logger.setLevel(previous_level)
        logger.propagate = previous_propagate
        logger.disabled = previous_disabled
    return handler.records


def test_one_summary_event_per_request() -> None:
    plan = _plan()
    records = _run_capture(plan)
    summary = [r for r in records if r.get("event") == "search_request"]
    assert len(summary) == 1
    assert summary[0]["request_id"] == str(plan.context.request_id)
    assert summary[0]["audit_id"] == str(plan.context.audit_id)
    assert summary[0]["account_id"] == str(plan.scope.account_id)
    assert summary[0]["plan_fingerprint"] == plan.fingerprint


def test_summary_has_required_fields() -> None:
    records = _run_capture(_plan())
    summary = next(r for r in records if r.get("event") == "search_request")
    required = {
        "mode_requested",
        "mode_effective",
        "strategy",
        "index_version",
        "embedding_model",
        "embedding_version",
        "reranker_version",
        "filter_names",
        "filter_sizes",
        "lexical_count",
        "semantic_count",
        "fused_count",
        "result_count",
        "warnings",
        "degraded",
        "timings_ms",
        "returned_chunk_ids",
        "returned_item_ids",
    }
    assert required <= set(summary)
    assert summary["result_count"] == 1
    assert str(CHUNK) in summary["returned_chunk_ids"]
    assert str(ITEM) in summary["returned_item_ids"]


def test_summary_is_content_free() -> None:
    records = _run_capture(_plan())
    summary = next(r for r in records if r.get("event") == "search_request")
    serialized = json.dumps(summary)
    assert _SECRET_QUERY not in serialized
    assert _SECRET_SENDER not in serialized
    # Only the filter's name and size are kept, never its value.
    assert summary["filter_names"] == ["sender"]
    assert summary["filter_sizes"] == {"sender": 1}
