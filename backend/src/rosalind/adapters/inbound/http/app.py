from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from rosalind.adapters.inbound.http.routes import (
    auth,
    health,
    imports,
    me,
    people,
    search,
    sources,
)
from rosalind.application.errors import (
    ImportNotFoundError,
    InvalidImportStateError,
    InvalidManifestError,
    InvalidStateError,
    ProviderError,
    SelfPersonError,
    SourceNotFoundError,
    TokenNotFoundError,
    UnsupportedImportTypeError,
)
from rosalind.application.search import InvalidSearchRequest
from rosalind.config import settings
from rosalind.logging import configure_logging
from rosalind.security import SecurityError


@asynccontextmanager
async def _lifespan(_: FastAPI) -> AsyncGenerator[None]:
    configure_logging(
        settings.log_level,
        settings.log_format,
        log_query_text=settings.log_query_text,
    )
    yield


app = FastAPI(title="Rosalind", lifespan=_lifespan)

app.include_router(health.router)
app.include_router(me.router)
app.include_router(imports.router)
app.include_router(sources.router)
app.include_router(auth.router)
app.include_router(people.router)
app.include_router(search.router)

if settings.eval.enabled:
    # Eval routes exist only in eval mode; the eval subsystem is never imported
    # by the rest of the app.
    from rosalind.adapters.inbound.http.routes import eval as eval_routes

    app.include_router(eval_routes.router)


@app.exception_handler(ImportNotFoundError)
async def _import_not_found(_: Request, exc: ImportNotFoundError) -> JSONResponse:
    return JSONResponse(status_code=404, content={"detail": str(exc)})


@app.exception_handler(SourceNotFoundError)
async def _source_not_found(_: Request, exc: SourceNotFoundError) -> JSONResponse:
    return JSONResponse(status_code=404, content={"detail": str(exc)})


@app.exception_handler(InvalidImportStateError)
async def _invalid_import_state(
    _: Request, exc: InvalidImportStateError
) -> JSONResponse:
    return JSONResponse(status_code=409, content={"detail": str(exc)})


@app.exception_handler(InvalidManifestError)
async def _invalid_manifest(_: Request, exc: InvalidManifestError) -> JSONResponse:
    return JSONResponse(status_code=422, content={"detail": str(exc)})


@app.exception_handler(UnsupportedImportTypeError)
async def _unsupported_import_type(
    _: Request, exc: UnsupportedImportTypeError
) -> JSONResponse:
    return JSONResponse(status_code=422, content={"detail": str(exc)})


@app.exception_handler(InvalidStateError)
async def _invalid_state(_: Request, exc: InvalidStateError) -> JSONResponse:
    return JSONResponse(status_code=400, content={"detail": str(exc)})


@app.exception_handler(TokenNotFoundError)
async def _token_not_found(_: Request, exc: TokenNotFoundError) -> JSONResponse:
    return JSONResponse(status_code=409, content={"detail": str(exc)})


@app.exception_handler(ProviderError)
async def _provider_error(_: Request, exc: ProviderError) -> JSONResponse:
    return JSONResponse(status_code=502, content={"detail": str(exc)})


@app.exception_handler(SecurityError)
async def _security_error(_: Request, exc: SecurityError) -> JSONResponse:
    return JSONResponse(status_code=500, content={"detail": str(exc)})


@app.exception_handler(SelfPersonError)
async def _self_person_error(_: Request, exc: SelfPersonError) -> JSONResponse:
    return JSONResponse(status_code=422, content={"detail": str(exc)})


@app.exception_handler(InvalidSearchRequest)
async def _invalid_search_request(
    _: Request, exc: InvalidSearchRequest
) -> JSONResponse:
    return JSONResponse(
        status_code=422,
        content={
            "detail": exc.message,
            "field": exc.field_name,
            "hint": exc.hint,
        },
    )
