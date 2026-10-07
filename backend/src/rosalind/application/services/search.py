"""Online search: the Prepare step (online search pipeline, step 1).

``SearchService.prepare`` turns an authenticated context plus a plain
``SearchRequest`` into a frozen ``SearchPlan`` (or a ``ShortCircuit`` when
nothing can match), or raises ``InvalidSearchRequest`` for malformed input.

The pipeline is:

    auth context → scope → cursor decode → validate → normalize
       → [entity/tag/thread lookups ‖ query embedding] → build plan
       → short-circuit checks → audit

Prepare depends only on the narrow ports in
``rosalind.application.search.ports``, so it is independent of MCP, SQL,
pgvector, ParadeDB, and the embedding implementation.
"""

from __future__ import annotations

import asyncio
import time
import uuid
from dataclasses import dataclass

from rosalind.application.canonicalization.email import normalize_email
from rosalind.application.search import (
    Cursor,
    InvalidSearchRequest,
    LexicalResult,
    PreparedQuery,
    PrepareTimings,
    QueryVector,
    RequestContext,
    ResolvedEntity,
    ResolvedFilters,
    ResultView,
    Scope,
    SearchMode,
    SearchPlan,
    SearchRequest,
    SearchResponse,
    SearchStrategy,
    SemanticResult,
    SemanticRetrievalError,
    ShortCircuit,
    ShortCircuitReason,
    SortOrder,
    assemble_list,
    assemble_ranked,
    fuse,
    rerank,
)
from rosalind.application.search.dates import resolve_timezone, to_utc_bounds
from rosalind.application.search.plan import (
    IndexVersions,
    PlanWarning,
    Presentation,
    WarningCode,
)
from rosalind.application.search.ports import (
    AuditEvent,
    AuditPort,
    ChunkTextPort,
    CursorCodecPort,
    CursorDecodeError,
    EmbedderPort,
    EntityResolverPort,
    LexicalRetrieverPort,
    MessageListPort,
    RerankConfig,
    RerankerPort,
    SearchConfig,
    SearchMetadata,
    SearchMetadataPort,
    SearchResultDataPort,
    SearchScopePort,
    SemanticRetrieverPort,
    ThreadResolverPort,
)
from rosalind.application.search.query import normalize_semantic_text, parse_keywords
from rosalind.application.search.tags import canonicalize_language, canonicalize_tag
from rosalind.domain.search import TokenCounter

_SELF = "me"

_UNSEEN_HANDLE_MSG = "no message in scope involves this address"


@dataclass(frozen=True, slots=True)
class PrepareContext:
    """Authenticated identity carried into Prepare, never read from tool args."""

    account_id: uuid.UUID
    client_id: str
    timezone: str | None = None


@dataclass(frozen=True, slots=True)
class _ResolvedPeople:
    senders: frozenset[str]
    recipients: frozenset[str]
    participants: frozenset[str]
    entities: tuple[ResolvedEntity, ...]
    unseen: frozenset[str]


async def _no_embed() -> tuple[None, None]:
    return None, None


class SearchService:
    """Coordinates online email search, beginning with Prepare."""

    def __init__(
        self,
        *,
        scope: SearchScopePort,
        metadata: SearchMetadataPort,
        entities: EntityResolverPort,
        threads: ThreadResolverPort,
        embedder: EmbedderPort,
        codec: CursorCodecPort,
        audit: AuditPort,
        config: SearchConfig,
        lexical: LexicalRetrieverPort,
        semantic: SemanticRetrieverPort,
        reranker: RerankerPort | None,
        rerank_config: RerankConfig | None,
        chunk_text: ChunkTextPort,
        token_counter: TokenCounter,
        result_data: SearchResultDataPort,
        list_retriever: MessageListPort,
    ):
        self._scope = scope
        self._metadata = metadata
        self._entities = entities
        self._threads = threads
        self._embedder = embedder
        self._codec = codec
        self._audit = audit
        self._config = config
        self._lexical = lexical
        self._semantic = semantic
        self._reranker = reranker
        self._rerank_config = rerank_config
        self._chunk_text = chunk_text
        self._token_counter = token_counter
        self._result_data = result_data
        self._list = list_retriever

    async def prepare(
        self,
        context: PrepareContext,
        request: SearchRequest,
    ) -> SearchPlan | ShortCircuit:
        started = time.perf_counter()

        self._validate(request)

        validate_ms = (time.perf_counter() - started) * 1000

        request_context = RequestContext(
            request_id=uuid.uuid4(),
            audit_id=uuid.uuid4(),
            client_id=context.client_id,
        )

        cursor = self._decode_cursor(request.cursor, context.account_id)

        authorized = await self._scope.get_scope(context.account_id)
        effective = _narrow(authorized, request.filters.source_accounts)

        if not effective:
            return await self._short_circuit(
                request_context,
                context,
                scope=None,
                reason=ShortCircuitReason.EMPTY_SCOPE,
                explanation="no source accounts are authorized for this search",
                filters=None,
                mode_requested=None,
                mode_effective=None,
                validate_ms=validate_ms,
                started=started,
            )

        scope = Scope(
            account_id=context.account_id, source_account_ids=frozenset(effective)
        )

        timezone_name = resolve_timezone(
            context.timezone, self._config.default_timezone
        )

        query_text, keywords_text = _trim(request)
        query_text, keywords_text, was_truncated = _cap_texts(
            query_text, keywords_text, self._config.max_query_chars
        )

        semantic_text = (
            normalize_semantic_text(query_text) if query_text is not None else None
        )
        lexical_source = keywords_text if keywords_text is not None else query_text
        lexical = parse_keywords(lexical_source) if lexical_source is not None else None

        has_semantic = query_text is not None
        has_any_query = has_semantic or keywords_text is not None
        strategy = SearchStrategy.RANKED if has_any_query else SearchStrategy.LIST

        if strategy is SearchStrategy.LIST and request.sort is SortOrder.RELEVANCE:
            raise InvalidSearchRequest(
                "sort", "cannot sort by relevance without a query"
            )

        mode_requested = request.mode
        mode_effective, mode_degraded = _decide_mode(
            strategy, mode_requested, has_semantic
        )

        needs_embedding = (
            strategy is SearchStrategy.RANKED
            and mode_effective in (SearchMode.HYBRID, SearchMode.SEMANTIC)
            and self._config.embedding_model is not None
            and self._config.embedding_version is not None
        )

        resolve_started = time.perf_counter()
        thread_id, metadata, resolved_lookups, embed_result = await asyncio.gather(
            self._resolve_thread(scope, request),
            self._metadata.get_metadata(scope.source_account_ids),
            self._resolve_lookups(scope, request),
            self._embed_timed(semantic_text) if needs_embedding else _no_embed(),
        )
        vector, embed_ms = embed_result
        resolve_ms = (time.perf_counter() - resolve_started) * 1000

        # An embedding failure degrades the mode to lexical rather than failing.
        if needs_embedding and vector is None:
            mode_effective, mode_degraded = _degrade_to_lexical(
                mode_effective, lexical is not None
            )
            if mode_effective in (SearchMode.HYBRID, SearchMode.SEMANTIC):
                raise InvalidSearchRequest(
                    "mode",
                    "semantic search is unavailable and there is no lexical fallback",
                )

        people = _build_people(request, resolved_lookups, metadata.known_handles)

        # A person reference that resolved to nothing cannot match.
        if _has_empty_lookup(resolved_lookups):
            return await self._short_circuit(
                request_context,
                context,
                scope=scope,
                reason=ShortCircuitReason.NO_MATCHING_HANDLES,
                explanation="a person reference resolved to no known handles",
                filters=None,
                mode_requested=mode_requested,
                mode_effective=mode_effective,
                validate_ms=validate_ms,
                resolve_ms=resolve_ms,
                embed_ms=embed_ms,
                started=started,
                resolved_entities=people.entities,
                warnings=_warnings_for(mode_degraded, was_truncated),
            )

        if request.filters.thread_of is not None and thread_id is None:
            return await self._short_circuit(
                request_context,
                context,
                scope=scope,
                reason=ShortCircuitReason.THREAD_NOT_FOUND,
                explanation="no such message is visible in scope",
                filters=None,
                mode_requested=mode_requested,
                mode_effective=mode_effective,
                validate_ms=validate_ms,
                resolve_ms=resolve_ms,
                embed_ms=embed_ms,
                started=started,
                resolved_entities=people.entities,
                warnings=_warnings_for(mode_degraded, was_truncated),
            )

        tags_any, tags_exclude, tag_warnings = self._resolve_tags(request, metadata)
        languages, language_warnings = self._resolve_languages(request, metadata)

        sent_from, sent_before = to_utc_bounds(
            request.filters.date_from, request.filters.date_before, timezone_name
        )

        filters = ResolvedFilters(
            senders=people.senders,
            recipients=people.recipients,
            participants=people.participants,
            direction=request.filters.direction,
            tags_any=tags_any,
            tags_exclude=tags_exclude,
            has_attachment=request.filters.has_attachment,
            thread_of=request.filters.thread_of,
            thread_id=thread_id,
            languages=languages,
            sent_from=sent_from,
            sent_before=sent_before,
            timezone_used=timezone_name,
            include_trash_spam=request.filters.include_trash_spam,
        )

        warnings = list(
            _warnings_for(mode_degraded, was_truncated)
            + tag_warnings
            + language_warnings
        )
        warnings.extend(_unseen_warnings(people.unseen))

        if _outside_coverage(sent_from, sent_before, metadata):
            return await self._short_circuit(
                request_context,
                context,
                scope=scope,
                reason=ShortCircuitReason.OUTSIDE_DATA_COVERAGE,
                explanation="the requested date range is outside the imported data",
                filters=filters,
                mode_requested=mode_requested,
                mode_effective=mode_effective,
                validate_ms=validate_ms,
                resolve_ms=resolve_ms,
                embed_ms=embed_ms,
                started=started,
                resolved_entities=people.entities,
                warnings=tuple(warnings),
            )

        prepared_query = _build_query(
            strategy, mode_effective, semantic_text, lexical, vector
        )

        limit, limit_clamped = _resolve_limit(request, self._config.budgets.window_k)
        if limit_clamped:
            warnings.append(
                PlanWarning(
                    code=WarningCode.LIMIT_CLAMPED,
                    message=f"limit clamped to the result window of {limit}",
                    field_name="limit",
                )
            )

        presentation = Presentation(
            sort=_resolve_sort(strategy, request),
            group_by=request.group_by,
            view=request.view,
            limit=limit,
        )

        plan = SearchPlan(
            context=request_context,
            scope=scope,
            filters=filters,
            resolved_entities=people.entities,
            query=prepared_query,
            strategy=strategy,
            mode_requested=mode_requested,
            mode_effective=mode_effective,
            presentation=presentation,
            budgets=self._config.budgets,
            versions=IndexVersions(
                index_version=self._config.index_version,
                embedding_model=self._config.embedding_model,
                embedding_version=self._config.embedding_version,
                reranker=self._config.reranker,
            ),
            fusion=self._config.fusion,
            cursor=cursor,
            warnings=tuple(warnings),
            timings=PrepareTimings(
                validate_ms=validate_ms,
                resolve_ms=resolve_ms,
                embed_ms=embed_ms,
                total_ms=(time.perf_counter() - started) * 1000,
            ),
        )

        if cursor is not None and cursor.fingerprint != plan.fingerprint:
            raise InvalidSearchRequest(
                "cursor", "cursor does not match this search request"
            )

        await self._audit.record(
            _audit_event(
                request_context,
                context,
                scope,
                plan.fingerprint,
                mode_requested,
                mode_effective,
                self._config,
                tuple(warnings),
                None,
                plan.timings,
            )
        )
        return plan

    # -- execution (steps 2-5) -------------------------------------------

    async def search(self, plan: SearchPlan) -> SearchResponse:
        """Run retrieval, fusion, reranking, and assembly for a prepared plan."""
        if plan.strategy is SearchStrategy.LIST:
            listed = await self._list.list(plan)
            return assemble_list(
                plan,
                listed,
                self._codec,
                max_snippet_chars=self._config.snippet_max_chars,
            )

        lexical, semantic, retrieval_warnings = await self._retrieve(plan)
        fused = fuse(plan, lexical, semantic)
        reranked = await rerank(
            plan,
            fused,
            texts=self._chunk_text,
            reranker=self._reranker,
            token_counter=self._token_counter,
            config=self._rerank_config,
        )

        window = reranked.ranked[: plan.budgets.window_k]
        chunk_ids = tuple(hit.chunk_id for hit in window)
        data = await self._result_data.get_results(
            plan,
            chunk_ids,
            include_text=plan.presentation.view is ResultView.SNIPPET,
        )
        return assemble_ranked(
            plan,
            reranked,
            data,
            self._codec,
            max_snippet_chars=self._config.snippet_max_chars,
            extra_warnings=retrieval_warnings,
        )

    async def _retrieve(
        self,
        plan: SearchPlan,
    ) -> tuple[LexicalResult | None, SemanticResult | None, tuple[PlanWarning, ...]]:
        """Run lexical and semantic retrieval in parallel, degrading semantic to
        lexical when a hybrid search loses its vector branch."""
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

    # -- validation -------------------------------------------------------

    def _validate(self, request: SearchRequest) -> None:
        if not (
            (request.query or "").strip()
            or (request.keywords or "").strip()
            or _has_any_filter(request)
        ):
            raise InvalidSearchRequest(
                None, "at least one of query, keywords, or a filter is required"
            )

        filters = request.filters
        if (
            filters.date_from is not None
            and filters.date_before is not None
            and filters.date_from >= filters.date_before
        ):
            raise InvalidSearchRequest(
                "filters.date_from", "date_from must be before date_before"
            )

        if request.mode is SearchMode.SEMANTIC and not (request.query or "").strip():
            raise InvalidSearchRequest(
                "mode",
                "semantic mode requires a natural-language query",
                hint="set query, or use mode=lexical with keywords",
            )

        maximum = self._config.max_list_values
        for name, values in (
            ("sender", filters.sender),
            ("recipient", filters.recipient),
            ("participant", filters.participant),
            ("tags", filters.tags),
            ("exclude_tags", filters.exclude_tags),
            ("language", filters.language),
            ("source_accounts", filters.source_accounts),
        ):
            if len(values) > maximum:
                raise InvalidSearchRequest(name, f"too many values (max {maximum})")

    # -- cursor -----------------------------------------------------------

    def _decode_cursor(self, token: str | None, account_id: uuid.UUID) -> Cursor | None:
        if not token:
            return None
        try:
            return self._codec.decode(
                token,
                account_id=account_id,
                index_version=self._config.index_version,
            )
        except CursorDecodeError as exc:
            raise InvalidSearchRequest("cursor", str(exc)) from exc

    # -- resolution -------------------------------------------------------

    async def _resolve_thread(self, scope: Scope, request: SearchRequest):
        if request.filters.thread_of is None:
            return None
        return await self._threads.resolve_thread(scope, request.filters.thread_of)

    async def _resolve_lookups(self, scope: Scope, request: SearchRequest):
        values = _lookup_values(request)
        if not values:
            return ()
        return await self._entities.resolve(scope, tuple(values))

    async def _embed_timed(
        self, semantic_text: str | None
    ) -> tuple[QueryVector | None, float | None]:
        if semantic_text is None:
            return None, None
        started = time.perf_counter()
        try:
            vector = await self._embedder.embed(
                semantic_text,
                self._config.embedding_model or "",
                self._config.embedding_version or "",
            )
        except Exception:  # noqa: BLE001 - degrade to lexical, never fail Prepare
            return None, (time.perf_counter() - started) * 1000
        return vector, (time.perf_counter() - started) * 1000

    def _resolve_tags(self, request: SearchRequest, metadata: SearchMetadata):
        tags_any: set[str] = set()
        tags_exclude: set[str] = set()
        warnings: list[PlanWarning] = []
        for raw in request.filters.tags:
            resolved, suggestion = canonicalize_tag(raw, metadata.known_tags)
            tags_any.add(resolved)
            if suggestion is not None:
                warnings.append(
                    PlanWarning(
                        code=WarningCode.UNKNOWN_TAG,
                        message=f"no tag {raw!r}",
                        field_name="tags",
                        suggestion=f"did you mean {suggestion!r}?",
                    )
                )
        for raw in request.filters.exclude_tags:
            resolved, suggestion = canonicalize_tag(raw, metadata.known_tags)
            tags_exclude.add(resolved)
            if suggestion is not None:
                warnings.append(
                    PlanWarning(
                        code=WarningCode.UNKNOWN_TAG,
                        message=f"no tag {raw!r}",
                        field_name="exclude_tags",
                        suggestion=f"did you mean {suggestion!r}?",
                    )
                )
        if tags_any & tags_exclude:
            raise InvalidSearchRequest(
                "tags", "a tag cannot be both included and excluded"
            )
        return frozenset(tags_any), frozenset(tags_exclude), tuple(warnings)

    def _resolve_languages(self, request: SearchRequest, metadata: SearchMetadata):
        languages = {canonicalize_language(raw) for raw in request.filters.language}
        warnings = tuple(
            PlanWarning(
                code=WarningCode.UNKNOWN_LANGUAGE,
                message=f"unknown language {lang!r}",
                field_name="language",
            )
            for lang in sorted(languages)
            if lang not in metadata.known_languages
        )
        return frozenset(languages), warnings

    # -- short circuits ---------------------------------------------------

    async def _short_circuit(
        self,
        request_context: RequestContext,
        context: PrepareContext,
        *,
        scope: Scope | None,
        reason: ShortCircuitReason,
        explanation: str,
        filters: ResolvedFilters | None,
        mode_requested: SearchMode | None,
        mode_effective: SearchMode | None,
        validate_ms: float,
        started: float,
        resolve_ms: float = 0.0,
        embed_ms: float | None = None,
        resolved_entities: tuple[ResolvedEntity, ...] = (),
        warnings: tuple[PlanWarning, ...] = (),
    ) -> ShortCircuit:
        result = ShortCircuit(
            context=request_context,
            reason=reason,
            explanation=explanation,
            filters=filters,
            resolved_entities=resolved_entities,
            warnings=warnings,
        )
        timings = PrepareTimings(
            validate_ms=validate_ms,
            resolve_ms=resolve_ms,
            embed_ms=embed_ms,
            total_ms=(time.perf_counter() - started) * 1000,
        )
        await self._audit.record(
            _audit_event(
                request_context,
                context,
                scope,
                None,
                mode_requested,
                mode_effective,
                self._config,
                warnings,
                reason,
                timings,
            )
        )
        return result


# --------------------------------------------------------------------------
# Pure helpers
# --------------------------------------------------------------------------


def _trim(request: SearchRequest) -> tuple[str | None, str | None]:
    query = request.query.strip() if request.query else None
    keywords = request.keywords.strip() if request.keywords else None
    return query or None, keywords or None


def _cap_texts(
    query: str | None, keywords: str | None, max_chars: int
) -> tuple[str | None, str | None, bool]:
    truncated = False
    if query is not None and len(query) > max_chars:
        query = query[:max_chars]
        truncated = True
    if keywords is not None and len(keywords) > max_chars:
        keywords = keywords[:max_chars]
        truncated = True
    return query, keywords, truncated


def _has_any_filter(request: SearchRequest) -> bool:
    f = request.filters
    return bool(
        f.sender
        or f.recipient
        or f.participant
        or f.direction is not None
        or f.date_from is not None
        or f.date_before is not None
        or f.tags
        or f.exclude_tags
        or f.has_attachment is not None
        or f.thread_of is not None
        or f.language
        or f.source_accounts
    )


def _narrow(
    authorized: frozenset[uuid.UUID], requested: frozenset[uuid.UUID]
) -> frozenset[uuid.UUID]:
    if requested:
        return frozenset(authorized) & frozenset(requested)
    return frozenset(authorized)


def _decide_mode(
    strategy: SearchStrategy, mode_requested: SearchMode, has_semantic: bool
) -> tuple[SearchMode, bool]:
    if strategy is SearchStrategy.LIST:
        return mode_requested, False
    if mode_requested is SearchMode.LEXICAL:
        return SearchMode.LEXICAL, False
    if mode_requested is SearchMode.SEMANTIC:
        return SearchMode.SEMANTIC, False
    if has_semantic:
        return SearchMode.HYBRID, False
    return SearchMode.LEXICAL, True


def _degrade_to_lexical(
    mode_effective: SearchMode, has_lexical: bool
) -> tuple[SearchMode, bool]:
    if not has_lexical:
        return mode_effective, False
    if mode_effective in (SearchMode.SEMANTIC, SearchMode.HYBRID):
        return SearchMode.LEXICAL, True
    return mode_effective, False


def _lookup_values(request: SearchRequest) -> list[str]:
    values: list[str] = []
    seen: set[str] = set()
    for raw in (
        *request.filters.sender,
        *request.filters.recipient,
        *request.filters.participant,
    ):
        if _is_lookup(raw) and raw not in seen:
            seen.add(raw)
            values.append(raw)
    return values


def _is_lookup(value: str) -> bool:
    stripped = value.strip()
    if stripped.lower() == _SELF:
        return True
    try:
        uuid.UUID(stripped)
        return True
    except ValueError:
        return False


def _build_people(
    request: SearchRequest,
    resolved_lookups: tuple[ResolvedEntity, ...],
    known_handles: frozenset[str],
) -> _ResolvedPeople:
    lookup_by_value = {entity.requested: entity for entity in resolved_lookups}

    senders: set[str] = set()
    recipients: set[str] = set()
    participants: set[str] = set()
    entities: list[ResolvedEntity] = []
    unseen: set[str] = set()

    def expand(values: frozenset[str], target: set[str]) -> None:
        for value in values:
            if _is_lookup(value):
                entity = lookup_by_value.get(value)
                if entity is not None:
                    target.update(entity.handles)
                    entities.append(entity)
            else:
                handle = normalize_email(value)
                target.add(handle)
                entities.append(
                    ResolvedEntity(
                        requested=value, entity_id=None, handles=frozenset({handle})
                    )
                )
                if handle and handle not in known_handles:
                    unseen.add(handle)

    expand(request.filters.sender, senders)
    expand(request.filters.recipient, recipients)
    expand(request.filters.participant, participants)

    deduped = _dedupe_entities(entities)
    return _ResolvedPeople(
        senders=frozenset(senders),
        recipients=frozenset(recipients),
        participants=frozenset(participants),
        entities=tuple(deduped),
        unseen=frozenset(unseen),
    )


def _dedupe_entities(entities: list[ResolvedEntity]) -> list[ResolvedEntity]:
    seen: set[str] = set()
    deduped: list[ResolvedEntity] = []
    for entity in entities:
        if entity.requested in seen:
            continue
        seen.add(entity.requested)
        deduped.append(entity)
    return deduped


def _has_empty_lookup(resolved_lookups: tuple[ResolvedEntity, ...]) -> bool:
    return any(not entity.handles for entity in resolved_lookups)


def _outside_coverage(sent_from, sent_before, metadata: SearchMetadata) -> bool:
    if metadata.min_sent_at is None or metadata.max_sent_at is None:
        return False
    if sent_before is not None and sent_before <= metadata.min_sent_at:
        return True
    return sent_from is not None and sent_from >= metadata.max_sent_at


def _build_query(
    strategy: SearchStrategy,
    mode_effective: SearchMode,
    semantic_text: str | None,
    lexical,
    vector: QueryVector | None,
) -> PreparedQuery:
    if strategy is SearchStrategy.LIST:
        return PreparedQuery()
    needs_lexical = mode_effective in (SearchMode.HYBRID, SearchMode.LEXICAL)
    needs_vector = mode_effective in (SearchMode.HYBRID, SearchMode.SEMANTIC)
    return PreparedQuery(
        semantic_text=semantic_text if needs_vector else None,
        lexical=lexical if needs_lexical else None,
        vector=vector if needs_vector else None,
    )


def _resolve_sort(strategy: SearchStrategy, request: SearchRequest) -> SortOrder:
    if request.sort is not None:
        return request.sort
    return (
        SortOrder.RELEVANCE
        if strategy is SearchStrategy.RANKED
        else SortOrder.DATE_DESC
    )


def _resolve_limit(request: SearchRequest, window_k: int) -> tuple[int, bool]:
    if request.limit > window_k:
        return window_k, True
    return request.limit, False


def _warnings_for(mode_degraded: bool, was_truncated: bool) -> tuple[PlanWarning, ...]:
    warnings: list[PlanWarning] = []
    if mode_degraded:
        warnings.append(
            PlanWarning(
                code=WarningCode.MODE_DEGRADED,
                message="requested mode could not be served; degraded to lexical",
                field_name="mode",
            )
        )
    if was_truncated:
        warnings.append(
            PlanWarning(
                code=WarningCode.QUERY_TRUNCATED,
                message="query was truncated to the maximum length",
            )
        )
    return tuple(warnings)


def _unseen_warnings(unseen: frozenset[str]) -> list[PlanWarning]:
    return [
        PlanWarning(
            code=WarningCode.UNSEEN_HANDLE,
            message=f"{_UNSEEN_HANDLE_MSG}: {handle!r}",
        )
        for handle in sorted(unseen)
    ]


def _semantic_degraded_warning() -> PlanWarning:
    return PlanWarning(
        code=WarningCode.RETRIEVAL_DEGRADED,
        message="semantic retrieval unavailable; results are lexical-only",
    )


def _audit_event(
    request_context: RequestContext,
    context: PrepareContext,
    scope: Scope | None,
    fingerprint: str | None,
    mode_requested: SearchMode | None,
    mode_effective: SearchMode | None,
    config: SearchConfig,
    warnings: tuple[PlanWarning, ...],
    short_circuit_reason: ShortCircuitReason | None,
    timings: PrepareTimings | None,
) -> AuditEvent:
    return AuditEvent(
        request_id=request_context.request_id,
        audit_id=request_context.audit_id,
        account_id=context.account_id,
        client_id=context.client_id,
        source_account_ids=scope.source_account_ids if scope else frozenset(),
        fingerprint=fingerprint,
        mode_requested=mode_requested.value if mode_requested is not None else None,
        mode_effective=mode_effective.value if mode_effective is not None else None,
        index_version=config.index_version,
        embedding_model=config.embedding_model,
        embedding_version=config.embedding_version,
        warnings=warnings,
        short_circuit_reason=(
            short_circuit_reason.value if short_circuit_reason is not None else None
        ),
        timings=timings,
    )


__all__ = ["PrepareContext", "SearchService"]
