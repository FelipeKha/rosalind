"""Per-stage switches for confidentiality (semantic) enforcement.

Layer: ``application``. Plain, framework-free values carried on the search
plan. Configuration is mapped into this type at the composition boundary (the
MCP adapter) so the application layer never imports settings.

A disabled level omits that stage; it never skips the operation. The master
``policy.semantic_enforcement_enabled`` switch gates everything above these, so
with it off the pipeline behaves exactly as before semantic enforcement
existed.

The level set is deliberately split into *build* (offline worker) and *online*
(query path) components so a degraded run can isolate one part of the filter.
"""

from __future__ import annotations

from dataclasses import dataclass

__all__ = ["SemanticEnforcementLevels"]

_LEVEL_NAMES = (
    "candidate_generation",
    "verification",
    "sanitization",
    "lexical",
    "semantic",
    "listing",
    "metadata",
    "thread",
    "rerank",
    "assembly",
    "jit",
    "final_gate",
    "derived",
    "term_features",
    "quoted_copy",
)

_BUILD_LEVEL_NAMES = ("candidate_generation", "verification", "sanitization")


@dataclass(frozen=True, slots=True)
class SemanticEnforcementLevels:
    """Which semantic-enforcement stages are active.

    Offline build levels:
        ``candidate_generation``: the recall-oriented funnel.
        ``verification``: local model verdicts (the deterministic floor always
            remains, even when this is off).
        ``sanitization``: cut-plus-marker and overlay construction.

    Online levels:
        ``lexical`` / ``semantic``: overlay union on each retrieval leg.
        ``listing`` / ``metadata`` / ``thread``: non-ranked read paths.
        ``rerank``: rerank on sanitized text only (off skips reranking).
        ``assembly``: render sanitized display text and redactions.
        ``jit``: synchronous verification of uncovered returned segments.
        ``final_gate``: cross-segment check of the assembled context.
        ``derived``: span-level visibility for extractions and attributes.
        ``term_features``: snippets/highlights/suggestions from overlay text.
        ``quoted_copy``: mask quoted copies of denied emails by segment hash.
    """

    candidate_generation: bool = True
    verification: bool = True
    sanitization: bool = True
    lexical: bool = True
    semantic: bool = True
    listing: bool = True
    metadata: bool = True
    thread: bool = True
    rerank: bool = True
    assembly: bool = True
    jit: bool = True
    final_gate: bool = True
    derived: bool = True
    term_features: bool = True
    quoted_copy: bool = True

    @property
    def output_safe(self) -> bool:
        """Whether at least one output safety net is enabled."""
        return self.assembly or self.final_gate

    @property
    def can_produce_sanitized_text(self) -> bool:
        """Whether any stage can produce sanitized text at all."""
        return self.sanitization or self.jit

    @property
    def build_enabled(self) -> bool:
        """Whether the offline worker has anything to do."""
        return any(getattr(self, name) for name in _BUILD_LEVEL_NAMES)

    def enabled_names(self) -> tuple[str, ...]:
        return tuple(name for name in _LEVEL_NAMES if getattr(self, name))

    def disabled_names(self) -> tuple[str, ...]:
        return tuple(name for name in _LEVEL_NAMES if not getattr(self, name))
