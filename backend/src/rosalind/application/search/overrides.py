"""Internal-only pipeline controls: stage overrides.

Layer: ``application``. These types exist so evaluation and experiments can
perturb the online search pipeline without touching the external MCP or REST
tool surface. They are **never** accepted from a tool parameter.

* ``PipelineOverrides`` mutates a validated ``SearchPlan`` (budgets, fusion
  settings, reranker version) via ``dataclasses.replace``, so the plan's own
  invariants still apply and the change is visible in ``plan.fingerprint``.
"""

from __future__ import annotations

from dataclasses import dataclass, replace

from rosalind.application.search.plan import Budgets, FusionConfig, SearchPlan
from rosalind.application.search.rerank import RerankTextMode

__all__ = ["PipelineOverrides"]


@dataclass(frozen=True, slots=True)
class PipelineOverrides:
    """Stage overrides for experiments. Internal API only.

    ``reranker`` enables reranking with the given version stamp;
    ``disable_reranker`` forces it off. Setting both is an error. Any override
    that would make the plan internally inconsistent raises ``ValueError`` from
    the plan's own ``__post_init__``.
    """

    reranker: str | None = None
    disable_reranker: bool = False
    rerank_text_mode: RerankTextMode | None = None

    lexical_k: int | None = None
    semantic_k: int | None = None
    fused_k: int | None = None
    rerank_k: int | None = None
    window_k: int | None = None

    fusion: FusionConfig | None = None

    def __post_init__(self) -> None:
        if self.reranker is not None and self.disable_reranker:
            raise ValueError("reranker and disable_reranker are mutually exclusive")

    def apply(self, plan: SearchPlan) -> SearchPlan:
        """Return a new plan with the requested overrides applied."""
        budgets = self._apply_budgets(plan.budgets)
        versions = plan.versions
        if self.disable_reranker:
            versions = replace(versions, reranker=None)
        elif self.reranker is not None:
            versions = replace(versions, reranker=self.reranker)
        fusion = self.fusion if self.fusion is not None else plan.fusion
        if (
            budgets is plan.budgets
            and versions is plan.versions
            and fusion is plan.fusion
        ):
            return plan
        return replace(plan, budgets=budgets, versions=versions, fusion=fusion)

    def _apply_budgets(self, budgets: Budgets) -> Budgets:
        if not any(
            value is not None
            for value in (
                self.lexical_k,
                self.semantic_k,
                self.fused_k,
                self.rerank_k,
                self.window_k,
            )
        ):
            return budgets
        return replace(
            budgets,
            lexical_k=(
                self.lexical_k if self.lexical_k is not None else budgets.lexical_k
            ),
            semantic_k=(
                self.semantic_k if self.semantic_k is not None else budgets.semantic_k
            ),
            fused_k=self.fused_k if self.fused_k is not None else budgets.fused_k,
            rerank_k=(self.rerank_k if self.rerank_k is not None else budgets.rerank_k),
            window_k=(self.window_k if self.window_k is not None else budgets.window_k),
        )
