from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from rosalind.api.routes import health, imports
from rosalind.ingestion.errors import (
    ImportNotFoundError,
    InvalidImportStateError,
    InvalidManifestError,
)

app = FastAPI(title="Rosalind")

app.include_router(health.router)
app.include_router(imports.router)


@app.exception_handler(ImportNotFoundError)
async def _import_not_found(_: Request, exc: ImportNotFoundError) -> JSONResponse:
    return JSONResponse(status_code=404, content={"detail": str(exc)})


@app.exception_handler(InvalidImportStateError)
async def _invalid_import_state(
    _: Request, exc: InvalidImportStateError
) -> JSONResponse:
    return JSONResponse(status_code=409, content={"detail": str(exc)})


@app.exception_handler(InvalidManifestError)
async def _invalid_manifest(_: Request, exc: InvalidManifestError) -> JSONResponse:
    return JSONResponse(status_code=422, content={"detail": str(exc)})
