"""Tests for the stage cache: keys, resume selection, and upstream-skip.

The end-to-end test drives the real ``SearchPipeline`` with fake ports and
asserts that rerunning (or changing only a downstream stage) does not call the
upstream ports again.
"""

from __future__ import annotations

import asyncio
import uuid
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

from rosalind.application.search import (
    Budgets,
    FusionConfig,
    FusionStrategy,
    GroupBy,
    IndexVersions,
    LexicalHit,
    LexicalQuery,
    LexicalResult,
    PreparedQuery,
    Presentation,
    QueryVector,
    RequestContext,
    ResolvedFilters,
    ResultView,
    ResumeStage,
    Scope,
    SearchMode,
    SearchPlan,
    SearchStrategy,
    SemanticHit,
    SemanticResult,
    SortOrder,
    vector_digest,
)
from rosalind.application.search.assemble import SearchResultData
from rosalind.application.search.cursor import HmacCursorCodec
from rosalind.application.search.fusion import FusedCandidates
from rosalind.application.search.overrides import PipelineCache
from rosalind.application.search.ports import RerankConfig
from rosalind.application.search.rerank import ChunkText, RerankResult, RerankStats
from rosalind.application.services.search_pipeline import SearchPipeline
from rosalind.domain.search import ChunkKind

from rosalind_eval.cache import (
    StageCache,
    cached_run,
    select_resume,
    stage_keys,
)

ACCOUNT = uuid.uuid4()
SA = uuid.uuid4()
C1, C2, C3 = (uuid.uuid4() for _ in range(3))
I1, I2, I3 = (uuid.uuid4() for _ in range(3))
_WHEN = datetime(2026, 3, 17, 9, 32, tzinfo=UTC)
_VECTOR = (1.0, 0.0, 0.0)
_CODEC = HmacCursorCodec(b"test-key")


def _plan(*, fusion: FusionConfig | None = None, lexical: bool = True) -> SearchPlan:
    lexical_query = LexicalQuery(terms=("roof",)) if lexical else None
    vector = QueryVector(
        values=_VECTOR,
        model="bge-m3",
        model_version="v1",
        digest=vector_digest(_VECTOR),
    )
    return SearchPlan(
        context=RequestContext(
            request_id=uuid.uuid4(), audit_id=uuid.uuid4(), client_id="test"
        ),
        scope=Scope(account_id=ACCOUNT, source_account_ids=frozenset({SA})),
        filters=ResolvedFilters(),
        resolved_entities=(),
        query=PreparedQuery(
            semantic_text="roof quote", lexical=lexical_query, vector=vector
        ),
        strategy=SearchStrategy.RANKED,
        mode_requested=SearchMode.HYBRID,
        mode_effective=SearchMode.HYBRID,
        presentation=Presentation(
            sort=SortOrder.RELEVANCE,
            group_by=GroupBy.MESSAGE,
            view=ResultView.METADATA,
            limit=5,
        ),
        budgets=Budgets(
            lexical_k=10, semantic_k=10, fused_k=10, rerank_k=5, window_k=5
        ),
        versions=IndexVersions(
            index_version="v1",
            embedding_model="bge-m3",
            embedding_version="v1",
            reranker="bge-reranker-v2-m3/v1",
        ),
        fusion=fusion or FusionConfig(),
    )


class FakeLexical:
    def __init__(self) -> None:
        self.calls = 0

    async def retrieve(self, plan: SearchPlan) -> LexicalResult:
        self.calls += 1
        return LexicalResult(
            hits=(
                LexicalHit(chunk_id=C1, email_id=I1, rank=1, score=9.0),
                LexicalHit(chunk_id=C2, email_id=I2, rank=2, score=4.0),
            ),
            exhausted=True,
            filter_path="pushdown",
            elapsed_ms=1.0,
        )


class FakeSemantic:
    def __init__(self) -> None:
        self.calls = 0

    async def retrieve(self, plan: SearchPlan) -> SemanticResult:
        self.calls += 1
        return SemanticResult(
            hits=(SemanticHit(chunk_id=C3, email_id=I3, rank=1, distance=0.1),),
            complete=True,
            filter_path="exact",
            scan_limit_hit=False,
            elapsed_ms=2.0,
        )


class FakeChunkText:
    def __init__(self) -> None:
        self.calls = 0

    async def get_rerank_texts(self, chunk_ids, mode):
        self.calls += 1
        return tuple(
            ChunkText(chunk_id=cid, text=f"passage {i}")
            for i, cid in enumerate(chunk_ids)
        )


class FakeReranker:
    def __init__(self) -> None:
        self.calls = 0

    async def rerank(self, query, passages):
        self.calls += 1
        return tuple(float(i) for i in range(len(passages)))


class FakeTokenCounter:
    @property
    def version(self) -> str:
        return "fake/1"

    def count(self, text: str) -> int:
        return len(text.split())

    def split_boundaries(self, text: str, max_tokens: int) -> list[int]:
        return [0, len(text)]


class FakeResultData:
    def __init__(self) -> None:
        self.calls = 0
        self._items = {C1: I1, C2: I2, C3: I3}

    async def get_results(self, plan, chunk_ids, *, include_text):
        self.calls += 1
        return tuple(
            SearchResultData(
                chunk_id=cid,
                item_id=self._items[cid],
                thread_id=None,
                chunk_kind=ChunkKind.EMAIL_BODY,
                occurred_at=_WHEN,
                sender_handle="mike@turnerroofing.com",
                subject="Roof quote",
                display_text=None,
                attachment_name=None,
            )
            for cid in chunk_ids
        )


class FakeListRetriever:
    async def list(self, plan):  # pragma: no cover - ranked only
        raise AssertionError("list retriever should not run")


class Ports:
    def __init__(self) -> None:
        self.lexical = FakeLexical()
        self.semantic = FakeSemantic()
        self.chunk_text = FakeChunkText()
        self.reranker = FakeReranker()
        self.result_data = FakeResultData()

    def pipeline(self) -> SearchPipeline:
        return SearchPipeline(
            lexical=self.lexical,
            semantic=self.semantic,
            chunk_text=self.chunk_text,
            codec=_CODEC,
            result_data=self.result_data,
            list_retriever=FakeListRetriever(),
            snippet_max_chars=200,
            reranker=self.reranker,
            rerank_config=RerankConfig(max_input_tokens=512),
            token_counter=FakeTokenCounter(),
        )


# --------------------------------------------------------------------------
# Keys and resume selection
# --------------------------------------------------------------------------


def test_stage_keys_ignore_downstream_fusion() -> None:
    base = _plan()
    convex = replace(
        base, fusion=FusionConfig(strategy=FusionStrategy.CONVEX, convex_alpha=0.5)
    )
    keys_base = stage_keys(base)
    keys_convex = stage_keys(convex)
    assert keys_base.lexical == keys_convex.lexical
    assert keys_base.semantic == keys_convex.semantic
    assert keys_base.fused != keys_convex.fused


def test_stage_keys_change_with_lexical_k() -> None:
    base = _plan()
    bigger = replace(base, budgets=replace(base.budgets, lexical_k=99))
    assert stage_keys(base).lexical != stage_keys(bigger).lexical
    assert stage_keys(base).semantic == stage_keys(bigger).semantic


def test_select_resume_prefers_latest_cached_stage() -> None:
    plan = _plan()
    assert select_resume(plan, PipelineCache()) is ResumeStage.LEXICAL
    assert (
        select_resume(plan, PipelineCache(lexical=_lexical_sentinel()))
        is ResumeStage.SEMANTIC
    )
    lex = _lexical_sentinel()
    sem = _semantic_sentinel()
    assert (
        select_resume(plan, PipelineCache(lexical=lex, semantic=sem))
        is ResumeStage.FUSE
    )
    assert (
        select_resume(plan, PipelineCache(fused=_fused_sentinel()))
        is ResumeStage.RERANK
    )
    assert (
        select_resume(plan, PipelineCache(reranked=_rerank_sentinel()))
        is ResumeStage.ASSEMBLE
    )


def test_select_resume_lexical_only_needs_only_lexical() -> None:
    plan = _plan(lexical=True)
    plan = replace(
        plan,
        query=PreparedQuery(
            semantic_text="roof quote",
            lexical=LexicalQuery(terms=("roof",)),
            vector=None,
        ),
        mode_requested=SearchMode.LEXICAL,
        mode_effective=SearchMode.LEXICAL,
        versions=IndexVersions(
            index_version="v1",
            embedding_model=None,
            embedding_version=None,
            reranker=None,
        ),
    )
    lex = _lexical_sentinel()
    assert select_resume(plan, PipelineCache(lexical=lex)) is ResumeStage.FUSE


def _lexical_sentinel() -> LexicalResult:
    return LexicalResult(hits=(), exhausted=True, filter_path="pushdown")


def _semantic_sentinel() -> SemanticResult:
    return SemanticResult(
        hits=(), complete=True, filter_path="exact", scan_limit_hit=False
    )


def _fused_sentinel() -> FusedCandidates:
    return FusedCandidates(
        candidates=(), lexical_used=True, semantic_used=True, dropped_by_item_cap=0
    )


def _rerank_sentinel() -> RerankResult:
    return RerankResult(
        ranked=(),
        applied=False,
        model=None,
        warnings=(),
        stats=RerankStats(
            candidates_in=0,
            scored=0,
            dropped_missing=0,
            truncated_passages=0,
            batches=0,
            fetch_ms=0.0,
            score_ms=0.0,
        ),
        elapsed_ms=0.0,
    )


# --------------------------------------------------------------------------
# Upstream-skip through the real pipeline
# --------------------------------------------------------------------------


def _run(pipeline: SearchPipeline, plan: SearchPlan, store: StageCache):
    return asyncio.run(cached_run(pipeline.run, plan, store))


def test_rerun_resumes_at_assemble_and_skips_upstream(tmp_path: Path) -> None:
    ports = Ports()
    pipeline = ports.pipeline()
    store = StageCache(tmp_path)
    plan = _plan()

    first, resume_first = _run(pipeline, plan, store)
    assert resume_first is ResumeStage.LEXICAL
    assert ports.lexical.calls == 1
    assert ports.semantic.calls == 1
    assert ports.chunk_text.calls == 1
    assert ports.reranker.calls == 1

    second, resume_second = _run(pipeline, plan, store)
    assert resume_second is ResumeStage.ASSEMBLE
    assert ports.lexical.calls == 1
    assert ports.semantic.calls == 1
    assert ports.chunk_text.calls == 1
    assert ports.reranker.calls == 1
    assert second.response.results == first.response.results


def test_changing_fusion_only_reruns_downstream(tmp_path: Path) -> None:
    ports = Ports()
    pipeline = ports.pipeline()
    store = StageCache(tmp_path)

    _run(pipeline, _plan(), store)
    assert ports.lexical.calls == 1
    assert ports.semantic.calls == 1

    convex = replace(
        _plan(), fusion=FusionConfig(strategy=FusionStrategy.CONVEX, convex_alpha=0.5)
    )
    _, resume = _run(pipeline, convex, store)

    assert resume is ResumeStage.FUSE
    assert ports.lexical.calls == 1  # lexical not recomputed
    assert ports.semantic.calls == 1  # semantic not recomputed
    assert ports.chunk_text.calls == 2  # rerank recomputed
    assert ports.reranker.calls == 2
