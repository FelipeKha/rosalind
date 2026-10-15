"""Online search orchestrator: runs retrieval → fusion → rerank → assembly.

Layer: ``application``. ``SearchPipeline`` owns steps 2–5 of the online search
pipeline (step 1, Prepare, stays in ``SearchService``). It depends only on the
ports in ``rosalind.application.search.ports`` and the pure stage functions
(``fuse``, ``rerank``, ``assemble_*``), so the same object serves production,
tests and evaluation. Serving and auditing share this one orchestrator.

Every run returns a ``SearchTrace`` carrying the plan, each stage result, the
final ``SearchResponse`` and per-stage timings. Callers that only need the
response use ``SearchService.search``/``.run(...).response``.

``overrides`` perturb budgets/fusion/reranker for experiments; it is an internal
API, never exposed as a tool parameter.
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import replace

from rosalind.application.search.assemble import (
    assemble_list,
    assemble_ranked,
)
from rosalind.application.search.fusion import FusedCandidates, fuse
from rosalind.application.search.overrides import PipelineOverrides
from rosalind.application.search.plan import (
    PlanWarning,
    SearchPlan,
    SearchStrategy,
    WarningCode,
)
from rosalind.application.search.ports import (
    ChunkTextPort,
    CursorCodecPort,
    LexicalRetrieverPort,
    MessageListPort,
    RerankConfig,
    RerankerPort,
    SearchResultDataPort,
    SemanticRetrieverPort,
    TraceRecorderPort,
)
from rosalind.application.search.request import ResultView
from rosalind.application.search.rerank import RerankResult, RerankTextMode, rerank
from rosalind.application.search.retrieve import LexicalResult
from rosalind.application.search.semantic import (
    SemanticResult,
    SemanticRetrievalError,
)
from rosalind.application.search.trace import SearchTrace, TraceLevel
from rosalind.domain.search import TokenCounter

__all__ = ["SearchPipeline"]


class SearchPipeline:
    """Steps 2–5 of online search: retrieve, fuse, rerank, assemble."""

    def __init__(
        self,
        *,
        lexical: LexicalRetrieverPort,
        semantic: SemanticRetrieverPort,
        chunk_text: ChunkTextPort,
        codec: CursorCodecPort,
        result_data: SearchResultDataPort,
        list_retriever: MessageListPort,
        snippet_max_chars: int,
        reranker: RerankerPort | None = None,
        rerank_config: RerankConfig | None = None,
        token_counter: TokenCounter | None = None,
        trace_recorder: TraceRecorderPort | None = None,
    ) -> None:
        self._lexical = lexical
        self._semantic = semantic
        self._chunk_text = chunk_text
        self._codec = codec
        self._result_data = result_data
        self._list = list_retriever
        self._snippet_max_chars = snippet_max_chars
        self._reranker = reranker
        self._rerank_config = rerank_config
        self._token_counter = token_counter
        self._trace_recorder = trace_recorder

    async def run(
        self,
        plan: SearchPlan,
        *,
        trace_level: TraceLevel = "minimal",
        overrides: PipelineOverrides | None = None,
    ) -> SearchTrace:
        """Run the pipeline for a prepared plan and return its trace."""
        started = time.perf_counter()
        rerank_text_mode = None
        if overrides is not None:
            plan = overrides.apply(plan)
            rerank_text_mode = overrides.rerank_text_mode
        timings: dict[str, float] = {}

        if plan.strategy is SearchStrategy.LIST:
            return await self._run_list(plan, trace_level, timings, started)

        retrieve_started = time.perf_counter()
        lexical, semantic, retrieval_warnings = await self._retrieve_all(plan)
        timings["retrieve_ms"] = (time.perf_counter() - retrieve_started) * 1000
        fused = fuse(plan, lexical, semantic)
        reranked = await self._rerank(plan, fused, timings, rerank_text_mode)

        results_started = time.perf_counter()
        window = reranked.ranked[: plan.budgets.window_k]
        chunk_ids = tuple(hit.chunk_id for hit in window)
        data = await self._result_data.get_results(
            plan,
            chunk_ids,
            include_text=plan.presentation.view is ResultView.SNIPPET,
        )
        timings["results_ms"] = (time.perf_counter() - results_started) * 1000

        assemble_started = time.perf_counter()
        response = assemble_ranked(
            plan,
            reranked,
            data,
            self._codec,
            max_snippet_chars=self._snippet_max_chars,
            extra_warnings=retrieval_warnings,
        )
        timings["assemble_ms"] = (time.perf_counter() - assemble_started) * 1000
        timings["total_ms"] = (time.perf_counter() - started) * 1000

        trace = SearchTrace(
            plan=plan,
            response=response,
            lexical=lexical,
            semantic=semantic,
            fused=fused,
            reranked=reranked,
            timings_ms=timings,
            trace_level=trace_level,
        )
        await self._record(trace)
        return trace

    async def _run_list(
        self,
        plan: SearchPlan,
        trace_level: TraceLevel,
        timings: dict[str, float],
        started: float,
    ) -> SearchTrace:
        list_started = time.perf_counter()
        listed = await self._list.list(plan)
        timings["list_ms"] = (time.perf_counter() - list_started) * 1000
        response = assemble_list(
            plan,
            listed,
            self._codec,
            max_snippet_chars=self._snippet_max_chars,
        )
        timings["total_ms"] = (time.perf_counter() - started) * 1000
        trace = SearchTrace(
            plan=plan,
            response=response,
            timings_ms=timings,
            trace_level=trace_level,
        )
        await self._record(trace)
        return trace

    async def _record(self, trace: SearchTrace) -> None:
        """Best-effort summary recording. Never fails the search."""
        if self._trace_recorder is None:
            return
        try:
            await self._trace_recorder.record(trace.to_summary())
        except Exception:
            logging.getLogger("rosalind.search.trace").warning(
                "search_trace_record_failed", exc_info=True
            )

    async def _rerank(
        self,
        plan: SearchPlan,
        fused: FusedCandidates,
        timings: dict[str, float],
        rerank_text_mode: RerankTextMode | None = None,
    ) -> RerankResult:
        config = self._rerank_config
        if rerank_text_mode is not None and config is not None:
            config = replace(config, text_mode=rerank_text_mode)
        started = time.perf_counter()
        reranked = await rerank(
            plan,
            fused,
            texts=self._chunk_text,
            reranker=self._reranker,
            token_counter=self._token_counter,
            config=config,
        )
        timings["rerank_ms"] = (time.perf_counter() - started) * 1000
        return reranked

    async def _retrieve_all(
        self, plan: SearchPlan
    ) -> tuple[LexicalResult | None, SemanticResult | None, tuple[PlanWarning, ...]]:
        """Run lexical and semantic retrieval in parallel.

        A hybrid search that loses its vector branch degrades to lexical with a
        warning rather than failing the whole request.
        """
        needs_lexical = plan.query.lexical is not None
        needs_semantic = plan.query.vector is not None

        if needs_lexical and needs_semantic:
            lexical_task = asyncio.create_task(self._lexical.retrieve(plan))
            semantic_task = asyncio.create_task(self._semantic.retrieve(plan))
            lexical = await lexical_task
            try:
                semantic = await semantic_task
            except SemanticRetrievalError:
                return lexical, None, (_semantic_degraded_warning(),)
            return lexical, semantic, ()

        if needs_lexical:
            return await self._lexical.retrieve(plan), None, ()

        if needs_semantic:
            return None, await self._semantic.retrieve(plan), ()

        raise ValueError("ranked plan has neither a lexical nor a semantic query")


def _semantic_degraded_warning() -> PlanWarning:
    return PlanWarning(
        code=WarningCode.RETRIEVAL_DEGRADED,
        message="semantic retrieval unavailable; results are lexical-only",
    )
