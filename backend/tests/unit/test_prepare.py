"""Unit tests for the Prepare step of online email search.

The ports are replaced by deterministic fakes, so these tests exercise the
orchestration, validation, normalization, mode selection, short circuits, and
cursor/fingerprint semantics without touching MCP, a database, or an embedding
service.
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, date, datetime

import pytest

from rosalind.application.search import (
    Direction,
    GroupBy,
    InvalidSearchRequest,
    PreparedQuery,
    QueryVector,
    ResolvedEntity,
    ResultView,
    SearchMode,
    SearchPlan,
    SearchRequest,
    SearchRequestFilters,
    SearchStrategy,
    ShortCircuit,
    ShortCircuitReason,
    SortOrder,
    vector_digest,
)
from rosalind.application.search.cursor import HmacCursorCodec
from rosalind.application.search.plan import (
    Budgets,
    FusionConfig,
    WarningCode,
)
from rosalind.application.search.ports import (
    AuditEvent,
    SearchConfig,
    SearchMetadata,
)
from rosalind.application.services.search import PrepareContext, SearchService

ACCOUNT = uuid.uuid4()
CLIENT = "rosalind-cli"
SA1 = uuid.uuid4()
SA2 = uuid.uuid4()
SELF = "me@example.com"
PERSON_ID = uuid.uuid4()
PERSON_HANDLE = "alex@example.com"
THREAD_ID = uuid.uuid4()
MESSAGE_ID = uuid.uuid4()

VECTOR = (1.0, 0.0, 0.0)


class FakeScope:
    def __init__(self, authorized: frozenset[uuid.UUID] = frozenset({SA1, SA2})):
        self.authorized = frozenset(authorized)

    async def get_scope(self, account_id: uuid.UUID) -> frozenset[uuid.UUID]:
        return self.authorized


class FakeMetadata:
    def __init__(self, **kw):
        self.value = SearchMetadata(
            min_sent_at=kw.get("min", datetime(2025, 1, 1, tzinfo=UTC)),
            max_sent_at=kw.get("max", datetime(2026, 12, 31, tzinfo=UTC)),
            known_tags=frozenset(kw.get("tags", ["gmail:Projects", "gmail:Inbox"])),
            known_languages=frozenset(kw.get("languages", ["en", "fr"])),
            known_handles=frozenset(kw.get("handles", [SELF, PERSON_HANDLE])),
        )

    async def get_metadata(self, source_account_ids) -> SearchMetadata:
        return self.value


class FakeEntities:
    def __init__(self, results: dict[str, ResolvedEntity] | None = None):
        self.results = results or {}
        self.calls: list[tuple[str, ...]] = []

    async def resolve(self, scope, values) -> tuple[ResolvedEntity, ...]:
        self.calls.append(tuple(values))
        return tuple(
            self.results.get(value, ResolvedEntity(value, None, frozenset()))
            for value in values
        )


class FakeThreads:
    def __init__(self, threads: dict[uuid.UUID, uuid.UUID] | None = None):
        self.threads = threads or {}

    async def resolve_thread(self, scope, message_id):
        return self.threads.get(message_id)


class FakeEmbedder:
    def __init__(self, fail: bool = False):
        self.fail = fail
        self.calls: list[str] = []

    async def embed(self, text, model, version) -> QueryVector:
        self.calls.append(text)
        if self.fail:
            raise RuntimeError("embedder down")
        return QueryVector(
            values=VECTOR,
            model=model,
            model_version=version,
            digest=vector_digest(VECTOR),
        )


class FakeAudit:
    def __init__(self):
        self.events: list[AuditEvent] = []

    async def record(self, event: AuditEvent) -> None:
        self.events.append(event)


def make_config(**kw) -> SearchConfig:
    return SearchConfig(
        index_version=kw.get("index_version", "v1"),
        embedding_model=kw.get("embedding_model", "bge-m3"),
        embedding_version=kw.get("embedding_version", "v1"),
        reranker=None,
        budgets=Budgets(
            lexical_k=50,
            semantic_k=50,
            fused_k=40,
            rerank_k=30,
            window_k=kw.get("window_k", 25),
        ),
        fusion=FusionConfig(),
        max_query_chars=kw.get("max_query_chars", 1000),
        max_list_values=kw.get("max_list_values", 10),
        default_timezone=kw.get("default_timezone", "UTC"),
    )


def make_service(**kw) -> tuple[SearchService, dict]:
    scope = kw.get("scope", FakeScope())
    metadata = kw.get("metadata", FakeMetadata())
    entities = kw.get("entities", FakeEntities())
    threads = kw.get("threads", FakeThreads())
    embedder = kw.get("embedder", FakeEmbedder())
    audit = kw.get("audit", FakeAudit())
    codec = kw.get("codec", HmacCursorCodec(b"test-key"))
    config = kw.get("config", make_config())
    service = SearchService(
        scope=scope,
        metadata=metadata,
        entities=entities,
        threads=threads,
        embedder=embedder,
        codec=codec,
        audit=audit,
        config=config,
    )
    parts = {
        "scope": scope,
        "metadata": metadata,
        "entities": entities,
        "threads": threads,
        "embedder": embedder,
        "audit": audit,
        "codec": codec,
        "config": config,
    }
    return service, parts


def req(**kw) -> SearchRequest:
    filters = kw.pop("filters", SearchRequestFilters())
    return SearchRequest(
        query=kw.get("query"),
        keywords=kw.get("keywords"),
        filters=filters,
        sort=kw.get("sort"),
        group_by=kw.get("group_by", GroupBy.MESSAGE),
        view=kw.get("view", ResultView.SNIPPET),
        limit=kw.get("limit", 10),
        cursor=kw.get("cursor"),
        mode=kw.get("mode", SearchMode.HYBRID),
    )


def run(service: SearchService, request: SearchRequest, **ctx):
    context = PrepareContext(account_id=ACCOUNT, client_id=CLIENT, **ctx)
    return asyncio.run(service.prepare(context, request))


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


def test_empty_request_is_rejected() -> None:
    service, _ = make_service()
    with pytest.raises(InvalidSearchRequest):
        run(service, req())


def test_invalid_date_range_is_rejected() -> None:
    service, _ = make_service()
    filters = SearchRequestFilters(
        date_from=date(2026, 6, 1), date_before=date(2026, 1, 1)
    )
    with pytest.raises(InvalidSearchRequest):
        run(service, req(filters=filters))


def test_semantic_mode_without_query_is_rejected() -> None:
    service, _ = make_service()
    with pytest.raises(InvalidSearchRequest):
        run(service, req(keywords="roof", mode=SearchMode.SEMANTIC))


def test_too_many_filter_values_is_rejected() -> None:
    service, _ = make_service(config=make_config(max_list_values=2))
    filters = SearchRequestFilters(sender=frozenset({"a@x.com", "b@x.com", "c@x.com"}))
    with pytest.raises(InvalidSearchRequest):
        run(service, req(filters=filters))


def test_sort_relevance_without_query_is_rejected() -> None:
    service, _ = make_service()
    filters = SearchRequestFilters(direction=Direction.RECEIVED)
    with pytest.raises(InvalidSearchRequest):
        run(service, req(filters=filters, sort=SortOrder.RELEVANCE))


# ---------------------------------------------------------------------------
# Scope
# ---------------------------------------------------------------------------


def test_scope_narrows_to_requested_source_accounts() -> None:
    service, _ = make_service()
    filters = SearchRequestFilters(source_accounts=frozenset({SA1}))
    plan = run(service, req(filters=filters))
    assert isinstance(plan, SearchPlan)
    assert plan.scope.source_account_ids == frozenset({SA1})


def test_source_accounts_outside_scope_short_circuits() -> None:
    service, _ = make_service()
    filters = SearchRequestFilters(source_accounts=frozenset({uuid.uuid4()}))
    result = run(service, req(filters=filters))
    assert isinstance(result, ShortCircuit)
    assert result.reason is ShortCircuitReason.EMPTY_SCOPE


def test_empty_authorized_scope_short_circuits() -> None:
    service, _ = make_service(scope=FakeScope(authorized=frozenset()))
    result = run(service, req(query="hello"))
    assert isinstance(result, ShortCircuit)
    assert result.reason is ShortCircuitReason.EMPTY_SCOPE


# ---------------------------------------------------------------------------
# People resolution
# ---------------------------------------------------------------------------


def test_me_expands_to_self_handles() -> None:
    entities = FakeEntities({"me": ResolvedEntity("me", None, frozenset({SELF}))})
    service, _ = make_service(entities=entities)
    filters = SearchRequestFilters(sender=frozenset({"me"}))
    plan = run(service, req(filters=filters))
    assert isinstance(plan, SearchPlan)
    assert plan.filters.senders == frozenset({SELF})


def test_entity_id_expands_to_handles() -> None:
    entities = FakeEntities(
        {
            str(PERSON_ID): ResolvedEntity(
                str(PERSON_ID), PERSON_ID, frozenset({PERSON_HANDLE})
            )
        }
    )
    service, _ = make_service(entities=entities)
    filters = SearchRequestFilters(participant=frozenset({str(PERSON_ID)}))
    plan = run(service, req(filters=filters))
    assert plan.filters.participants == frozenset({PERSON_HANDLE})


def test_unknown_handle_warns_but_proceeds() -> None:
    service, _ = make_service()
    filters = SearchRequestFilters(sender=frozenset({"never.seen@example.com"}))
    plan = run(service, req(filters=filters))
    assert isinstance(plan, SearchPlan)
    assert plan.filters.senders == frozenset({"never.seen@example.com"})
    assert any(w.code is WarningCode.UNSEEN_HANDLE for w in plan.warnings)


def test_entity_with_no_handles_short_circuits() -> None:
    entities = FakeEntities(
        {str(PERSON_ID): ResolvedEntity(str(PERSON_ID), PERSON_ID, frozenset())}
    )
    service, _ = make_service(entities=entities)
    filters = SearchRequestFilters(sender=frozenset({str(PERSON_ID)}))
    result = run(service, req(filters=filters))
    assert isinstance(result, ShortCircuit)
    assert result.reason is ShortCircuitReason.NO_MATCHING_HANDLES


# ---------------------------------------------------------------------------
# Tags and languages
# ---------------------------------------------------------------------------


def test_unknown_tag_warns_with_suggestion() -> None:
    service, _ = make_service()
    filters = SearchRequestFilters(tags=frozenset({"gmail:Project"}))
    plan = run(service, req(filters=filters))
    assert isinstance(plan, SearchPlan)
    warnings = {w.code: w for w in plan.warnings}
    assert WarningCode.UNKNOWN_TAG in warnings
    assert "gmail:Projects" in (warnings[WarningCode.UNKNOWN_TAG].suggestion or "")


def test_known_tag_is_canonicalized() -> None:
    service, _ = make_service()
    filters = SearchRequestFilters(tags=frozenset({"gmail:projects"}))
    plan = run(service, req(filters=filters))
    assert plan.filters.tags_any == frozenset({"gmail:Projects"})


def test_include_and_exclude_same_tag_is_rejected() -> None:
    service, _ = make_service()
    filters = SearchRequestFilters(
        tags=frozenset({"gmail:Projects"}), exclude_tags=frozenset({"gmail:Projects"})
    )
    with pytest.raises(InvalidSearchRequest):
        run(service, req(filters=filters))


def test_unknown_language_warns() -> None:
    service, _ = make_service()
    filters = SearchRequestFilters(language=frozenset({"xx"}))
    plan = run(service, req(filters=filters))
    assert isinstance(plan, SearchPlan)
    assert any(w.code is WarningCode.UNKNOWN_LANGUAGE for w in plan.warnings)


# ---------------------------------------------------------------------------
# Thread resolution
# ---------------------------------------------------------------------------


def test_thread_of_resolves_to_current_thread() -> None:
    service, _ = make_service(threads=FakeThreads({MESSAGE_ID: THREAD_ID}))
    filters = SearchRequestFilters(thread_of=MESSAGE_ID)
    plan = run(service, req(filters=filters))
    assert plan.filters.thread_of == MESSAGE_ID
    assert plan.filters.thread_id == THREAD_ID


def test_missing_thread_short_circuits() -> None:
    service, _ = make_service(threads=FakeThreads({}))
    filters = SearchRequestFilters(thread_of=MESSAGE_ID)
    result = run(service, req(filters=filters))
    assert isinstance(result, ShortCircuit)
    assert result.reason is ShortCircuitReason.THREAD_NOT_FOUND


# ---------------------------------------------------------------------------
# Dates and coverage
# ---------------------------------------------------------------------------


def test_dates_normalize_to_utc_and_record_timezone() -> None:
    service, _ = make_service()
    filters = SearchRequestFilters(
        date_from=date(2026, 3, 1), date_before=date(2026, 4, 1)
    )
    plan = run(service, req(filters=filters), timezone="Europe/Paris")
    assert plan.filters.timezone_used == "Europe/Paris"
    assert plan.filters.sent_from is not None
    assert plan.filters.sent_before is not None
    assert plan.filters.sent_from.utcoffset().total_seconds() == 0
    assert plan.filters.sent_before.utcoffset().total_seconds() == 0


def test_invalid_timezone_falls_back_to_default() -> None:
    service, _ = make_service(config=make_config(default_timezone="UTC"))
    filters = SearchRequestFilters(date_from=date(2026, 3, 1))
    plan = run(service, req(filters=filters), timezone="Not/AZone")
    assert plan.filters.timezone_used == "UTC"


def test_date_range_outside_coverage_short_circuits() -> None:
    metadata = FakeMetadata(
        min=datetime(2025, 1, 1, tzinfo=UTC), max=datetime(2025, 6, 1, tzinfo=UTC)
    )
    service, _ = make_service(metadata=metadata)
    filters = SearchRequestFilters(date_from=date(2026, 1, 1))
    result = run(service, req(filters=filters))
    assert isinstance(result, ShortCircuit)
    assert result.reason is ShortCircuitReason.OUTSIDE_DATA_COVERAGE


# ---------------------------------------------------------------------------
# Strategy and mode
# ---------------------------------------------------------------------------


def test_filter_only_request_is_list_strategy() -> None:
    service, _ = make_service()
    filters = SearchRequestFilters(direction=Direction.SENT)
    plan = run(service, req(filters=filters))
    assert plan.strategy is SearchStrategy.LIST
    assert plan.presentation.sort is SortOrder.DATE_DESC
    assert plan.query == PreparedQuery()


def test_query_request_is_ranked_with_relevance_default() -> None:
    service, _ = make_service()
    plan = run(service, req(query="holidays in Spain"))
    assert plan.strategy is SearchStrategy.RANKED
    assert plan.presentation.sort is SortOrder.RELEVANCE


def test_hybrid_embeds_and_builds_lexical() -> None:
    service, parts = make_service()
    plan = run(service, req(query="holidays in Spain", mode=SearchMode.HYBRID))
    assert plan.mode_effective is SearchMode.HYBRID
    assert plan.query.vector is not None
    assert plan.query.lexical is not None
    assert plan.query.semantic_text == "holidays in Spain"
    assert parts["embedder"].calls == ["holidays in Spain"]


def test_lexical_skips_embedding() -> None:
    service, parts = make_service()
    plan = run(service, req(query="roof quote", mode=SearchMode.LEXICAL))
    assert plan.mode_effective is SearchMode.LEXICAL
    assert plan.query.lexical is not None
    assert plan.query.vector is None
    assert parts["embedder"].calls == []


def test_hybrid_with_keywords_only_degrades_to_lexical() -> None:
    service, _ = make_service()
    plan = run(service, req(keywords='"12 Elm St"', mode=SearchMode.HYBRID))
    assert plan.mode_effective is SearchMode.LEXICAL
    assert any(w.code is WarningCode.MODE_DEGRADED for w in plan.warnings)


def test_embedding_failure_degrades_to_lexical() -> None:
    service, _ = make_service(embedder=FakeEmbedder(fail=True))
    plan = run(service, req(query="holidays in Spain", mode=SearchMode.HYBRID))
    assert plan.mode_effective is SearchMode.LEXICAL
    assert plan.query.vector is None
    assert plan.query.lexical is not None
    assert any(w.code is WarningCode.MODE_DEGRADED for w in plan.warnings)


def test_semantic_mode_embeds_only() -> None:
    service, parts = make_service()
    plan = run(service, req(query="holidays in Spain", mode=SearchMode.SEMANTIC))
    assert plan.mode_effective is SearchMode.SEMANTIC
    assert plan.query.vector is not None
    assert plan.query.lexical is None
    assert parts["embedder"].calls == ["holidays in Spain"]


# ---------------------------------------------------------------------------
# Limit and budgets
# ---------------------------------------------------------------------------


def test_limit_above_window_is_clamped() -> None:
    service, _ = make_service(config=make_config(window_k=5))
    plan = run(service, req(query="hello", limit=25))
    assert plan.presentation.limit == 5
    assert any(w.code is WarningCode.LIMIT_CLAMPED for w in plan.warnings)


# ---------------------------------------------------------------------------
# Cursor and fingerprint
# ---------------------------------------------------------------------------


def test_same_request_yields_identical_fingerprint() -> None:
    service1, _ = make_service()
    service2, _ = make_service()
    request = req(query="holidays in Spain")
    plan1 = run(service1, request)
    plan2 = run(service2, request)
    assert plan1.fingerprint == plan2.fingerprint


def test_cursor_fingerprint_mismatch_is_rejected() -> None:
    codec = HmacCursorCodec(b"test-key")
    from rosalind.application.search import Cursor

    token = codec.encode(
        Cursor(fingerprint="deadbeef", window_offset=0),
        account_id=ACCOUNT,
        index_version="v1",
    )
    service, _ = make_service(codec=codec)
    with pytest.raises(InvalidSearchRequest):
        run(service, req(query="hello", cursor=token))


def test_cursor_index_version_mismatch_is_rejected() -> None:
    codec = HmacCursorCodec(b"test-key")
    from rosalind.application.search import Cursor

    token = codec.encode(
        Cursor(fingerprint="deadbeef", window_offset=0),
        account_id=ACCOUNT,
        index_version="v2",
    )
    service, _ = make_service(codec=codec)
    with pytest.raises(InvalidSearchRequest):
        run(service, req(query="hello", cursor=token))


def test_cursor_account_mismatch_is_rejected() -> None:
    codec = HmacCursorCodec(b"test-key")
    from rosalind.application.search import Cursor

    token = codec.encode(
        Cursor(fingerprint="deadbeef", window_offset=0),
        account_id=uuid.uuid4(),
        index_version="v1",
    )
    service, _ = make_service(codec=codec)
    with pytest.raises(InvalidSearchRequest):
        run(service, req(query="hello", cursor=token))


# ---------------------------------------------------------------------------
# Concurrency and audit
# ---------------------------------------------------------------------------


def test_independent_lookups_overlap() -> None:
    events: list[str] = []

    class CoordinatingEmbedder:
        async def embed(self, text, model, version):
            events.append("embed_start")
            await asyncio.sleep(0.02)
            events.append("embed_end")
            return QueryVector(VECTOR, model, version, vector_digest(VECTOR))

    class CoordinatingEntities:
        async def resolve(self, scope, values):
            events.append("entities_start")
            await asyncio.sleep(0.02)
            events.append("entities_end")
            return ()

    service, _ = make_service(
        embedder=CoordinatingEmbedder(), entities=CoordinatingEntities()
    )
    filters = SearchRequestFilters(participant=frozenset({str(PERSON_ID)}))
    run(service, req(query="holidays in Spain", filters=filters))

    assert events.index("embed_start") < events.index("entities_end")
    assert events.index("entities_start") < events.index("embed_end")


def test_audit_recorded_for_plan() -> None:
    service, parts = make_service()
    run(service, req(query="hello"))
    assert len(parts["audit"].events) == 1
    event = parts["audit"].events[0]
    assert event.account_id == ACCOUNT
    assert event.mode_effective == "hybrid"
    assert event.fingerprint is not None
    assert event.short_circuit_reason is None


def test_audit_recorded_for_short_circuit() -> None:
    service, parts = make_service(scope=FakeScope(authorized=frozenset()))
    run(service, req(query="hello"))
    assert len(parts["audit"].events) == 1
    assert parts["audit"].events[0].short_circuit_reason == "empty_scope"
