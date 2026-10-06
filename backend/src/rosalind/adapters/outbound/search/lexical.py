"""ParadeDB (pg_search) lexical retrieval adapter for online search step 2.1.

Renders the structured ``LexicalQuery`` into engine syntax and runs filtered
BM25 retrieval against ``search.chunk``. It owns every pg_search/PostgreSQL
concept (``@@@``, ``paradedb.score``, the literal tokenizer, array overlap), so
``application`` stays engine-agnostic.

Correctness notes (verified against pg_search 0.26.0):

* The BM25 index (`chunk_bm25_idx`) carries the scope/time/bool fast fields and
  the literal-tokenized text fields (`sender_handle`, ``direction``,
  ``language``). Filters on those columns push into the index scan.
* Filters on the array columns (`recipient_handles`, ``participant_handles``,
  ``tags``) and ``thread_id`` are *not* in the index. ParadeDB still returns
  correct results for these, applying them as heap filters while scanning the
  BM25 candidate stream in score order — so a single ``LIMIT lexical_k + 1``
  query is exact for every filter, and ``exhausted`` needs no iterative
  overfetch. ``filter_path`` reports which of the two situations applied.
* The scope predicate is mandatory and always applied via ``source_account_num``,
  resolved from ``plan.scope``; it can only narrow, never widen.

A deterministic tie-break (``score DESC, id ASC``) makes results reproducible.
"""

from __future__ import annotations

import asyncio
import time
import uuid
from collections.abc import Callable, Sequence
from typing import cast

from sqlalchemy import select, text
from sqlalchemy.orm import Session
from sqlalchemy.sql.elements import ColumnElement

from rosalind.adapters.outbound.persistence import models
from rosalind.application.search import (
    FilterPath,
    LexicalHit,
    LexicalQuery,
    LexicalResult,
    SearchPlan,
)

__all__ = ["ParadeDbLexicalQueryRenderer", "ParadeDbLexicalRetriever"]

_ESCAPE = set('+-!(){}[]^"~*?:\\&|')


def _escape_term(term: str) -> str:
    return "".join("\\" + ch if ch in _ESCAPE else ch for ch in term)


def _quote_phrase(phrase: str) -> str:
    escaped = phrase.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


class ParadeDbLexicalQueryRenderer:
    """Renders a ``LexicalQuery`` into a pg_search query string.

    Terms and phrases are space-joined, which pg_search's default parser
    treats as a disjunction. Terms are escaped so operator characters
    (``C++``, ``2026-0412``, ``(`` ...) are matched literally; phrases are
    quoted so they match as ordered phrases.
    """

    def render(self, query: LexicalQuery) -> str:
        parts = [_escape_term(term) for term in query.terms]
        parts.extend(_quote_phrase(phrase) for phrase in query.phrases)
        return " ".join(parts)


class ParadeDbLexicalRetriever:
    def __init__(self, session_factory: Callable[[], Session]):
        self._factory = session_factory

    async def retrieve(self, plan: SearchPlan) -> LexicalResult:
        return await asyncio.to_thread(self._retrieve, plan)

    def _retrieve(self, plan: SearchPlan) -> LexicalResult:
        lexical = plan.query.lexical
        if lexical is None:
            raise ValueError("lexical retrieval requires a lexical query")

        started = time.perf_counter()
        query_string = ParadeDbLexicalQueryRenderer().render(lexical)

        with self._factory() as session:
            nums = self._scope_nums(session, plan.scope.source_account_ids)
            rows = self._query(session, plan, query_string, nums)

        lexical_k = plan.budgets.lexical_k
        hits = tuple(
            LexicalHit(chunk_id=chunk_id, rank=rank, score=float(score))
            for rank, (chunk_id, score) in enumerate(rows[:lexical_k], start=1)
        )
        return LexicalResult(
            hits=hits,
            exhausted=len(rows) <= lexical_k,
            filter_path=_filter_path(plan),
            elapsed_ms=(time.perf_counter() - started) * 1000,
        )

    def _scope_nums(
        self, session: Session, source_account_ids: frozenset[uuid.UUID]
    ) -> list[int]:
        return list(
            session.scalars(
                select(models.SourceAccount.num).where(
                    models.SourceAccount.id.in_(source_account_ids)
                )
            ).all()
        )

    def _query(
        self,
        session: Session,
        plan: SearchPlan,
        query_string: str,
        nums: Sequence[int],
    ) -> list[tuple[uuid.UUID, float]]:
        chunk = models.Chunk
        conditions: list[ColumnElement[bool]] = [
            cast(ColumnElement[bool], text("text_for_index @@@ :q")),
            chunk.source_account_num.in_(nums),
        ]
        conditions.extend(_filter_conditions(plan))

        limit = plan.budgets.lexical_k + 1
        stmt = (
            select(chunk.id, text("paradedb.score(id) AS score"))
            .where(*conditions)
            .order_by(text("paradedb.score(id) DESC"), chunk.id.asc())
            .limit(limit)
        )
        return list(session.execute(stmt, {"q": query_string}).all())


def _filter_conditions(plan: SearchPlan) -> list[ColumnElement[bool]]:
    chunk = models.Chunk
    filters = plan.filters
    conditions: list[ColumnElement[bool]] = []

    if filters.senders:
        conditions.append(chunk.sender_handle.in_(sorted(filters.senders)))
    if filters.recipients:
        conditions.append(chunk.recipient_handles.overlap(sorted(filters.recipients)))
    if filters.participants:
        conditions.append(
            chunk.participant_handles.overlap(sorted(filters.participants))
        )
    if filters.direction is not None:
        conditions.append(chunk.direction == filters.direction.value)
    if filters.tags_any:
        conditions.append(chunk.tags.overlap(sorted(filters.tags_any)))
    if filters.tags_exclude:
        conditions.append(~chunk.tags.overlap(sorted(filters.tags_exclude)))
    if filters.has_attachment is not None:
        conditions.append(chunk.has_attachment == filters.has_attachment)
    if filters.thread_id is not None:
        conditions.append(chunk.thread_id == filters.thread_id)
    if filters.languages:
        conditions.append(chunk.language.in_(sorted(filters.languages)))
    if filters.sent_from is not None:
        conditions.append(chunk.sent_at >= filters.sent_from)
    if filters.sent_before is not None:
        conditions.append(chunk.sent_at < filters.sent_before)
    if not filters.include_trash_spam:
        conditions.append(chunk.is_trash_or_spam.is_(False))

    return conditions


def _filter_path(plan: SearchPlan) -> FilterPath:
    filters = plan.filters
    overfetch = (
        filters.recipients
        or filters.participants
        or filters.tags_any
        or filters.tags_exclude
        or filters.thread_id is not None
    )
    return "overfetch" if overfetch else "pushdown"
