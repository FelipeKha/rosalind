from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from rosalind.adapters.inbound.http.routes import auth, health, imports, people, sources
from rosalind.application.errors import (
    ImportNotFoundError,
    InvalidImportStateError,
    InvalidManifestError,
    InvalidStateError,
    ProviderError,
    SourceNotFoundError,
    TokenNotFoundError,
)
from rosalind.security import SecurityError

app = FastAPI(title="Rosalind")

app.include_router(health.router)
app.include_router(imports.router)
app.include_router(sources.router)
app.include_router(auth.router)
app.include_router(people.router)


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
