"""Unit tests for the ``SearchPipeline`` orchestrator and ``SearchTrace``.

The stage ports are replaced by deterministic fakes, so these tests pin the
orchestration (retrieval → fusion → rerank → assembly), the ``resume_from``
cache contract for every stage, and the internal stage overrides — without a
database or a model. They are the behaviour-preserving regression guard for the
extraction of steps 2–5 out of ``SearchService``.
"""

from __future__ import annotations

import asyncio
import uuid
from dataclasses import dataclass, replace
from datetime import UTC, datetime

import pytest

from rosalind.application.search import (
    Budgets,
    Direction,
    FusionConfig,
    FusionStrategy,
    GroupBy,
    IndexVersions,
    LexicalHit,
    LexicalQuery,
    LexicalResult,
    PipelineCache,
    PipelineOverrides,
    PreparedQuery,
    Presentation,
    QueryVector,
    RequestContext,
    RerankTextMode,
    ResolvedFilters,
    ResultView,
    ResumeStage,
    Scope,
    SearchMode,
    SearchPlan,
    SearchStrategy,
    SemanticHit,
    SemanticResult,
    SemanticRetrievalError,
    SortOrder,
    WarningCode,
    vector_digest,
)
from rosalind.application.search.assemble import (
    ListResult,
    SearchResultData,
)
from rosalind.application.search.cursor import HmacCursorCodec
from rosalind.application.search.fusion import FusedCandidate, FusedCandidates
from rosalind.application.search.ports import RerankConfig
from rosalind.application.search.rerank import ChunkText
from rosalind.application.services.search_pipeline import SearchPipeline
from rosalind.domain.search import ChunkKind

ACCOUNT = uuid.uuid4()
SA = uuid.uuid4()
A1, A2, B1, C1 = (uuid.uuid4() for _ in range(4))
EMAIL_A, EMAIL_B, EMAIL_C = (uuid.uuid4() for _ in range(3))

CODEC = HmacCursorCodec(b"test-key")
_WHEN = datetime(2026, 3, 17, 9, 32, tzinfo=UTC)
_VECTOR = (1.0, 0.0, 0.0)


# ---------------------------------------------------------------------------
# Fixtures / fakes
# ---------------------------------------------------------------------------


def _plan(
    *,
    mode: SearchMode = SearchMode.LEXICAL,
    strategy: SearchStrategy = SearchStrategy.RANKED,
    group_by: GroupBy = GroupBy.MESSAGE,
    view: ResultView = ResultView.SNIPPET,
    limit: int = 10,
    window_k: int = 10,
    reranker: str | None = None,
    fusion: FusionConfig | None = None,
    direction: Direction | None = None,
) -> SearchPlan:
    if strategy is SearchStrategy.LIST:
        query = PreparedQuery()
        sort = SortOrder.DATE_DESC
        mode_requested = mode
    else:
        sort = SortOrder.RELEVANCE
        mode_requested = mode
        lexical = (
            LexicalQuery(terms=("roof",))
            if mode in (SearchMode.LEXICAL, SearchMode.HYBRID)
            else None
        )
        vector = (
            QueryVector(
                values=_VECTOR,
                model="bge-m3",
                model_version="v1",
                digest=vector_digest(_VECTOR),
            )
            if mode in (SearchMode.SEMANTIC, SearchMode.HYBRID)
            else None
        )
        query = PreparedQuery(
            semantic_text="roof quote" if vector is not None else None,
            lexical=lexical,
            vector=vector,
        )
    return SearchPlan(
        context=RequestContext(
            request_id=uuid.uuid4(), audit_id=uuid.uuid4(), client_id="test"
        ),
        scope=Scope(account_id=ACCOUNT, source_account_ids=frozenset({SA})),
        filters=ResolvedFilters(direction=direction),
        resolved_entities=(),
        query=query,
        strategy=strategy,
        mode_requested=mode_requested,
        mode_effective=mode,
        presentation=Presentation(sort=sort, group_by=group_by, view=view, limit=limit),
        budgets=Budgets(
            lexical_k=50, semantic_k=50, fused_k=40, rerank_k=30, window_k=window_k
        ),
        versions=IndexVersions(
            index_version="v1",
            embedding_model="bge-m3" if mode is not SearchMode.LEXICAL else None,
            embedding_version="v1" if mode is not SearchMode.LEXICAL else None,
            reranker=reranker,
        ),
        fusion=fusion if fusion is not None else FusionConfig(),
    )


def _lexical(
    hits: list[tuple[uuid.UUID, float]], *, exhausted: bool = False
) -> LexicalResult:
    return LexicalResult(
        hits=tuple(
            LexicalHit(chunk_id=cid, email_id=EMAIL_A, rank=i, score=score)
            for i, (cid, score) in enumerate(hits, start=1)
        ),
        exhausted=exhausted,
        filter_path="pushdown",
        elapsed_ms=1.0,
    )


def _semantic(
    hits: list[tuple[uuid.UUID, float]], *, complete: bool = True
) -> SemanticResult:
    return SemanticResult(
        hits=tuple(
            SemanticHit(chunk_id=cid, email_id=EMAIL_A, rank=i, distance=distance)
            for i, (cid, distance) in enumerate(hits, start=1)
        ),
        complete=complete,
        filter_path="exact",
        scan_limit_hit=False,
        elapsed_ms=2.0,
    )


class FakeLexical:
    def __init__(self, result: LexicalResult | None = None) -> None:
        self.result = result if result is not None else _lexical([(A1, 5.0), (A2, 4.0)])
        self.calls = 0

    async def retrieve(self, plan: SearchPlan) -> LexicalResult:
        self.calls += 1
        return self.result


class FakeSemantic:
    def __init__(
        self, result: SemanticResult | None = None, *, raises: bool = False
    ) -> None:
        self.result = (
            result if result is not None else _semantic([(B1, 0.1), (A1, 0.2)])
        )
        self.raises = raises
        self.calls = 0

    async def retrieve(self, plan: SearchPlan) -> SemanticResult:
        self.calls += 1
        if self.raises:
            raise SemanticRetrievalError("backend down")
        return self.result


class FakeChunkText:
    def __init__(self) -> None:
        self.calls = 0
        self.modes: list[object] = []

    async def get_rerank_texts(self, chunk_ids, mode) -> tuple[ChunkText, ...]:
        self.calls += 1
        self.modes.append(mode)
        return tuple(
            ChunkText(chunk_id=cid, text=f"passage {i}")
            for i, cid in enumerate(chunk_ids)
        )


class FakeResultData:
    def __init__(self, mapping: dict[uuid.UUID, uuid.UUID] | None = None) -> None:
        self.mapping = mapping or {}
        self.calls = 0

    async def get_results(self, plan, chunk_ids, *, include_text):
        self.calls += 1
        return tuple(
            SearchResultData(
                chunk_id=cid,
                item_id=self.mapping.get(cid, cid),
                thread_id=None,
                chunk_kind=ChunkKind.EMAIL_BODY,
                occurred_at=_WHEN,
                sender_handle="mike@turnerroofing.com",
                subject="Roof quote",
                display_text=f"display {cid}" if include_text else None,
                attachment_name=None,
            )
            for cid in chunk_ids
        )


class FakeListRetriever:
    def __init__(self) -> None:
        self.calls = 0

    async def list(self, plan) -> ListResult:
        self.calls += 1
        return ListResult(
            items=(
                SearchResultData(
                    chunk_id=A1,
                    item_id=EMAIL_A,
                    thread_id=None,
                    chunk_kind=ChunkKind.EMAIL_BODY,
                    occurred_at=_WHEN,
                    sender_handle="mike@turnerroofing.com",
                    subject="Roof quote",
                    display_text="hello",
                    attachment_name=None,
                ),
            ),
            total=1,
        )


class FakeReranker:
    def __init__(self) -> None:
        self.calls = 0

    async def rerank(self, query, passages):
        self.calls += 1
        # Highest score for the last passage, to force a reorder.
        return tuple(float(i) for i in range(len(passages)))


class FakeTokenCounter:
    @property
    def version(self) -> str:
        return "fake/1"

    def count(self, text: str) -> int:
        return len(text.split())

    def split_boundaries(self, text: str, max_tokens: int) -> list[int]:
        return [0, len(text)]


@dataclass
class Fakes:
    lexical: FakeLexical
    semantic: FakeSemantic
    chunk_text: FakeChunkText
    result_data: FakeResultData
    list_retriever: FakeListRetriever
    reranker: FakeReranker | None


def make_pipeline(
    *,
    lexical: FakeLexical | None = None,
    semantic: FakeSemantic | None = None,
    reranker: bool = False,
    mapping: dict[uuid.UUID, uuid.UUID] | None = None,
) -> tuple[SearchPipeline, Fakes]:
    lex = lexical or FakeLexical()
    sem = semantic or FakeSemantic()
    chunk_text = FakeChunkText()
    result_data = FakeResultData(mapping)
    list_retriever = FakeListRetriever()
    reranker_obj = FakeReranker() if reranker else None
    pipeline = SearchPipeline(
        lexical=lex,
        semantic=sem,
        chunk_text=chunk_text,
        codec=CODEC,
        result_data=result_data,
        list_retriever=list_retriever,
        snippet_max_chars=200,
        reranker=reranker_obj,
        rerank_config=RerankConfig(max_input_tokens=512) if reranker else None,
        token_counter=FakeTokenCounter() if reranker else None,
    )
    return pipeline, Fakes(
        lexical=lex,
        semantic=sem,
        chunk_text=chunk_text,
        result_data=result_data,
        list_retriever=list_retriever,
        reranker=reranker_obj,
    )


def run(coro):
    return asyncio.run(coro)


# ---------------------------------------------------------------------------
# Behaviour regression: ranked, list, degradation, rerank
# ---------------------------------------------------------------------------


def test_ranked_run_returns_deterministic_response() -> None:
    pipeline, _ = make_pipeline()
    trace = run(pipeline.run(_plan(mode=SearchMode.LEXICAL)))
    assert trace.response.results
    assert [r.chunk_id for r in trace.response.results] == [A1, A2]
    assert trace.lexical is not None
    assert trace.fused is not None
    assert trace.reranked is not None
    assert "total_ms" in trace.timings_ms


def test_list_strategy_uses_list_retriever() -> None:
    pipeline, fakes = make_pipeline()
    trace = run(
        pipeline.run(_plan(strategy=SearchStrategy.LIST, direction=Direction.RECEIVED))
    )
    assert fakes.list_retriever.calls == 1
    assert fakes.lexical.calls == 0
    assert trace.response.total_estimate == 1


def test_hybrid_semantic_failure_degrades_to_lexical() -> None:
    pipeline, _ = make_pipeline(semantic=FakeSemantic(raises=True))
    trace = run(pipeline.run(_plan(mode=SearchMode.HYBRID)))
    codes = {w.code for w in trace.response.warnings}
    assert WarningCode.RETRIEVAL_DEGRADED in codes
    assert trace.semantic is None
    assert trace.fused is not None
    assert trace.fused.semantic_used is False


def test_rerank_applied_reorders_results() -> None:
    pipeline, fakes = make_pipeline(reranker=True)
    trace = run(
        pipeline.run(_plan(mode=SearchMode.LEXICAL, reranker="bge-reranker-v2-m3/v1"))
    )
    assert trace.reranked is not None and trace.reranked.applied is True
    assert fakes.reranker is not None and fakes.reranker.calls == 1
    # Fused order is [A1, A2]; the fake scores the last passage highest.
    assert [r.chunk_id for r in trace.response.results] == [A2, A1]


def test_rerank_disabled_by_default() -> None:
    pipeline, fakes = make_pipeline()
    trace = run(pipeline.run(_plan(mode=SearchMode.LEXICAL)))
    assert trace.reranked is not None and trace.reranked.applied is False
    assert fakes.reranker is None


# ---------------------------------------------------------------------------
# resume_from: one per stage
# ---------------------------------------------------------------------------


def test_resume_from_lexical_recomputes_everything() -> None:
    pipeline, fakes = make_pipeline()
    trace = run(
        pipeline.run(_plan(mode=SearchMode.LEXICAL), resume_from=ResumeStage.LEXICAL)
    )
    assert fakes.lexical.calls == 1
    assert fakes.semantic.calls == 0
    assert trace.response.results


def test_resume_from_semantic_reuses_cached_lexical() -> None:
    pipeline, fakes = make_pipeline()
    cached = PipelineCache(lexical=_lexical([(A1, 5.0)]))
    trace = run(
        pipeline.run(
            _plan(mode=SearchMode.HYBRID),
            resume_from=ResumeStage.SEMANTIC,
            cached=cached,
        )
    )
    assert fakes.lexical.calls == 0
    assert fakes.semantic.calls == 1
    assert trace.lexical is cached.lexical


def test_resume_from_fuse_skips_both_retrievers() -> None:
    pipeline, fakes = make_pipeline()
    cached = PipelineCache(
        lexical=_lexical([(A1, 5.0)]),
        semantic=_semantic([(B1, 0.1)]),
    )
    trace = run(
        pipeline.run(
            _plan(mode=SearchMode.HYBRID),
            resume_from=ResumeStage.FUSE,
            cached=cached,
        )
    )
    assert fakes.lexical.calls == 0
    assert fakes.semantic.calls == 0
    assert trace.fused is not None
    assert {c.chunk_id for c in trace.fused.candidates} == {A1, B1}


def test_resume_from_rerank_reuses_cached_fused() -> None:
    pipeline, fakes = make_pipeline(reranker=True)
    fused = FusedCandidates(
        candidates=(
            FusedCandidate(
                chunk_id=A1,
                email_id=EMAIL_A,
                fused_score=0.5,
                fused_rank=1,
                lexical_rank=1,
                lexical_score=5.0,
                semantic_rank=None,
                semantic_distance=None,
            ),
        ),
        lexical_used=True,
        semantic_used=False,
        dropped_by_item_cap=0,
    )
    trace = run(
        pipeline.run(
            _plan(mode=SearchMode.LEXICAL, reranker="bge-reranker-v2-m3/v1"),
            resume_from=ResumeStage.RERANK,
            cached=PipelineCache(fused=fused),
        )
    )
    assert fakes.lexical.calls == 0
    assert fakes.reranker is not None and fakes.reranker.calls == 1
    assert trace.fused is fused


def test_resume_from_assemble_reuses_cached_rerank() -> None:
    pipeline, _ = make_pipeline(reranker=True)
    reranked = run(
        pipeline.run(_plan(mode=SearchMode.LEXICAL, reranker="bge-reranker-v2-m3/v1"))
    ).reranked
    assert reranked is not None

    pipeline2, fakes2 = make_pipeline(reranker=True)
    trace = run(
        pipeline2.run(
            _plan(mode=SearchMode.LEXICAL, reranker="bge-reranker-v2-m3/v1"),
            resume_from=ResumeStage.ASSEMBLE,
            cached=PipelineCache(reranked=reranked),
        )
    )
    assert fakes2.lexical.calls == 0
    assert fakes2.reranker is not None and fakes2.reranker.calls == 0
    assert trace.reranked is reranked


@pytest.mark.parametrize(
    "stage",
    [
        ResumeStage.SEMANTIC,
        ResumeStage.FUSE,
        ResumeStage.RERANK,
        ResumeStage.ASSEMBLE,
    ],
)
def test_resume_without_required_cache_raises(stage: ResumeStage) -> None:
    pipeline = make_pipeline(reranker=True)[0]
    with pytest.raises(ValueError):
        run(pipeline.run(_plan(mode=SearchMode.LEXICAL), resume_from=stage))


# ---------------------------------------------------------------------------
# Overrides (internal API only)
# ---------------------------------------------------------------------------


def test_override_rerank_k_changes_plan_and_fingerprint() -> None:
    pipeline, _ = make_pipeline(reranker=True)
    base = _plan(mode=SearchMode.LEXICAL, reranker="bge-reranker-v2-m3/v1")
    trace = run(pipeline.run(base, overrides=PipelineOverrides(rerank_k=20)))
    assert trace.plan.budgets.rerank_k == 20
    assert trace.plan.fingerprint != base.fingerprint


def test_override_disable_reranker() -> None:
    pipeline, _ = make_pipeline()
    trace = run(
        pipeline.run(
            _plan(mode=SearchMode.LEXICAL, reranker="bge-reranker-v2-m3/v1"),
            overrides=PipelineOverrides(disable_reranker=True),
        )
    )
    assert trace.plan.rerank_enabled is False


def test_override_reranker_and_disable_conflict() -> None:
    with pytest.raises(ValueError):
        PipelineOverrides(reranker="x", disable_reranker=True)


def test_override_fusion_strategy_changes_fingerprint() -> None:
    base = _plan(mode=SearchMode.LEXICAL)
    convex = FusionConfig(strategy=FusionStrategy.CONVEX, convex_alpha=0.5)
    overridden = PipelineOverrides(fusion=convex).apply(base)
    assert overridden.fusion.strategy is FusionStrategy.CONVEX
    assert overridden.fingerprint != base.fingerprint


def test_override_rerank_text_mode_reaches_chunk_text() -> None:
    pipeline, fakes = make_pipeline(reranker=True)
    run(
        pipeline.run(
            _plan(mode=SearchMode.LEXICAL, reranker="bge-reranker-v2-m3/v1"),
            overrides=PipelineOverrides(rerank_text_mode=RerankTextMode.DISPLAY),
        )
    )
    assert fakes.chunk_text.modes == [RerankTextMode.DISPLAY]


# ---------------------------------------------------------------------------
# Trace projection
# ---------------------------------------------------------------------------


def test_minimal_summary_omits_candidate_lists() -> None:
    pipeline, _ = make_pipeline()
    trace = run(pipeline.run(_plan(mode=SearchMode.LEXICAL), trace_level="minimal"))
    summary = trace.to_summary()
    assert summary.lexical_count == 2
    assert summary.lexical_candidate_ids is None
    assert summary.fused_candidate_ids is None


def test_full_summary_keeps_candidate_lists() -> None:
    pipeline, _ = make_pipeline()
    trace = run(pipeline.run(_plan(mode=SearchMode.LEXICAL), trace_level="full"))
    summary = trace.to_summary()
    assert summary.lexical_candidate_ids == (A1, A2)
    assert summary.fused_candidate_ids is not None


def test_summary_never_carries_filter_values() -> None:
    pipeline, _ = make_pipeline()
    plan = _plan(mode=SearchMode.LEXICAL)
    plan = replace(
        plan,
        filters=ResolvedFilters(senders=frozenset({"secret@example.com"})),
    )
    trace = run(pipeline.run(plan))
    summary = trace.to_summary()
    assert summary.filter_names == ("sender",)
    assert summary.filter_sizes == {"sender": 1}
    assert "secret@example.com" not in repr(summary)


def test_summary_replay_plan_only_when_opted_in() -> None:
    pipeline, _ = make_pipeline()
    trace = run(pipeline.run(_plan(mode=SearchMode.LEXICAL)))
    assert trace.to_summary().plan is None
    assert trace.to_summary(include_plan=True).plan is trace.plan


# ---------------------------------------------------------------------------
# SearchService delegation (the adapters' entry point)
# ---------------------------------------------------------------------------


class _UnusedAsync:
    async def get_scope(self, account_id):  # pragma: no cover - unused in run()
        raise NotImplementedError

    async def get_metadata(self, source_account_ids):  # pragma: no cover
        raise NotImplementedError

    async def resolve(self, scope, values):  # pragma: no cover
        raise NotImplementedError

    async def resolve_thread(self, scope, message_id):  # pragma: no cover
        raise NotImplementedError

    async def embed(self, text, model, version):  # pragma: no cover
        raise NotImplementedError

    async def record(self, event):  # pragma: no cover
        raise NotImplementedError


def _make_service(lexical=None, semantic=None, reranker=False):
    from rosalind.application.search.ports import SearchConfig
    from rosalind.application.services.search import SearchService

    config = SearchConfig(
        index_version="v1",
        embedding_model=None,
        embedding_version=None,
        reranker="bge-reranker-v2-m3/v1" if reranker else None,
        budgets=Budgets(
            lexical_k=50, semantic_k=50, fused_k=40, rerank_k=30, window_k=10
        ),
        fusion=FusionConfig(),
        max_query_chars=1000,
        max_list_values=50,
        default_timezone="UTC",
        snippet_max_chars=200,
    )
    unused = _UnusedAsync()
    service = SearchService(
        scope=unused,
        metadata=unused,
        entities=unused,
        threads=unused,
        embedder=unused,
        codec=CODEC,
        audit=unused,
        config=config,
        lexical=lexical or FakeLexical(),
        semantic=semantic or FakeSemantic(),
        reranker=FakeReranker() if reranker else None,
        rerank_config=RerankConfig(max_input_tokens=512) if reranker else None,
        chunk_text=FakeChunkText(),
        token_counter=FakeTokenCounter(),
        result_data=FakeResultData(),
        list_retriever=FakeListRetriever(),
    )
    return service


def test_search_service_search_matches_run_response() -> None:
    service = _make_service()
    plan = _plan(mode=SearchMode.LEXICAL)
    response = run(service.search(plan))
    trace = run(service.run(plan))
    assert response == trace.response
    assert [r.chunk_id for r in response.results] == [A1, A2]


def test_search_service_run_exposes_trace() -> None:
    service = _make_service()
    trace = run(service.run(_plan(mode=SearchMode.LEXICAL)))
    assert trace.lexical is not None
    assert trace.fused is not None
    assert trace.reranked is not None
