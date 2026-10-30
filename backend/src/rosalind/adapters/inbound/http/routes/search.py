"""Email search endpoint (a REST peer of the MCP ``search`` tool).

Thin transport adapter: maps the HTTP request onto the application-layer
``SearchRequest``, calls the same ``SearchService`` the MCP tool uses, and maps
the result back. No retrieval, fusion, reranking, or assembly logic lives here.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends

from rosalind.adapters import composition
from rosalind.adapters.inbound.http.dependencies import AccountDep, get_current_account
from rosalind.adapters.inbound.http.schemas import search as schemas
from rosalind.adapters.outbound.persistence.session import SessionLocal
from rosalind.application.search import (
    Direction,
    GroupBy,
    ResultView,
    SearchMode,
    SearchPlan,
    SearchRequest,
    SearchRequestFilters,
    SearchResponse,
    ShortCircuit,
    SortOrder,
)
from rosalind.application.services.search import PrepareContext

router = APIRouter(
    prefix="/search", tags=["search"], dependencies=[Depends(get_current_account)]
)


@router.post("", response_model=schemas.SearchResultResponse)
async def search(
    body: schemas.SearchEmailsInput,
    account: AccountDep,
) -> schemas.SearchResultResponse:
    request = _to_search_request(body)
    service = composition.build_search_service(SessionLocal)
    context = PrepareContext(account_id=account.id, client_id="rosalind-rest")
    prepared = await service.prepare(context, request)
    if isinstance(prepared, ShortCircuit):
        return _to_short_circuit(prepared)
    trace = await service.run(prepared)
    return _to_response(prepared, trace.response)


def _to_search_request(input: schemas.SearchEmailsInput) -> SearchRequest:
    filters = input.filters
    return SearchRequest(
        query=input.query,
        keywords=input.keywords,
        filters=SearchRequestFilters(
            sender=frozenset(filters.sender or ()),
            recipient=frozenset(filters.recipient or ()),
            participant=frozenset(filters.participant or ()),
            direction=Direction(filters.direction) if filters.direction else None,
            date_from=filters.date_from,
            date_before=filters.date_before,
            tags=frozenset(filters.tags or ()),
            exclude_tags=frozenset(filters.exclude_tags or ()),
            has_attachment=filters.has_attachment,
            thread_of=filters.thread_of,
            language=frozenset(filters.language or ()),
            source_accounts=frozenset(filters.source_accounts or ()),
            include_trash_spam=filters.include_trash_spam,
        ),
        sort=SortOrder(input.sort) if input.sort else None,
        group_by=GroupBy(input.group_by),
        view=ResultView(input.view),
        limit=input.limit,
        cursor=input.cursor,
        mode=SearchMode(input.mode),
    )


def _to_response(
    plan: SearchPlan, response: SearchResponse
) -> schemas.SearchResultResponse:
    return schemas.SearchResultResponse(
        request_id=plan.context.request_id,
        audit_id=plan.context.audit_id,
        mode_requested=plan.mode_requested.value,
        mode_effective=plan.mode_effective.value,
        fingerprint=plan.fingerprint,
        applied_filters=response.applied_filters,
        warnings=[_to_warning(w) for w in response.warnings],
        results=[_to_item(record) for record in response.results],
        total_estimate=response.total_estimate,
        next_cursor=response.next_cursor,
    )


def _to_short_circuit(result: ShortCircuit) -> schemas.SearchResultResponse:
    return schemas.SearchResultResponse(
        request_id=result.context.request_id,
        audit_id=result.context.audit_id,
        short_circuit=result.reason.value,
        explanation=result.explanation,
        applied_filters=result.applied(),
        warnings=[_to_warning(w) for w in result.warnings],
    )


def _to_item(record) -> schemas.SearchResultItem:
    return schemas.SearchResultItem(
        item_id=record.item_id,
        thread_id=record.thread_id,
        chunk_id=record.chunk_id,
        subject=record.subject,
        sender=record.sender,
        date=record.date,
        snippet=record.snippet,
        matched_in=record.matched_in,
        score=record.score,
        citation=schemas.SearchCitation(
            item_id=record.citation.item_id,
            chunk_id=record.citation.chunk_id,
            thread_id=record.citation.thread_id,
        ),
    )


def _to_warning(warning) -> schemas.SearchWarning:
    return schemas.SearchWarning(
        code=warning.code.value,
        message=warning.message,
        field_name=warning.field_name,
        suggestion=warning.suggestion,
    )
