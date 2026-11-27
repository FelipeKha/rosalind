"""Policy service application factory."""

from __future__ import annotations

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from rosalind.config import settings
from rosalind.logging import configure_logging
from rosalind.policy.adapters.llm_ollama import ensure_local
from rosalind.policy.api.routes import router
from rosalind.policy.domain.errors import (
    ConstraintNotReadyError,
    DraftNotFoundError,
    ModelNotAllowedError,
    ParserError,
    PolicyError,
    PolicyNotFoundError,
    UnsupportedConstraintError,
)
from rosalind.security import SecurityError


def _validate_policy_config() -> None:
    policy = settings.policy
    if not policy.enabled:
        return
    for model in policy.models:
        ensure_local(model.base_url)
    if (
        policy.default_model is not None
        and policy.model_for(policy.default_model) is None
    ):
        raise RuntimeError(
            f"default policy model {policy.default_model!r} is not in the allowlist"
        )


@asynccontextmanager
async def _lifespan(_: FastAPI) -> AsyncGenerator[None]:
    configure_logging(
        settings.log_level,
        settings.log_format,
        log_query_text=False,
    )
    _validate_policy_config()
    yield


def _register_exception_handlers(application: FastAPI) -> None:
    @application.exception_handler(DraftNotFoundError)
    async def _draft_not_found(_: Request, exc: DraftNotFoundError) -> JSONResponse:
        return JSONResponse(status_code=404, content={"detail": str(exc)})

    @application.exception_handler(PolicyNotFoundError)
    async def _policy_not_found(_: Request, exc: PolicyNotFoundError) -> JSONResponse:
        return JSONResponse(status_code=404, content={"detail": str(exc)})

    @application.exception_handler(ConstraintNotReadyError)
    async def _constraint_not_ready(
        _: Request, exc: ConstraintNotReadyError
    ) -> JSONResponse:
        return JSONResponse(status_code=409, content={"detail": str(exc)})

    @application.exception_handler(ModelNotAllowedError)
    async def _model_not_allowed(_: Request, exc: ModelNotAllowedError) -> JSONResponse:
        return JSONResponse(status_code=422, content={"detail": str(exc)})

    @application.exception_handler(UnsupportedConstraintError)
    async def _unsupported_constraint(
        _: Request, exc: UnsupportedConstraintError
    ) -> JSONResponse:
        return JSONResponse(status_code=422, content={"detail": str(exc)})

    @application.exception_handler(ParserError)
    async def _parser_error(_: Request, exc: ParserError) -> JSONResponse:
        return JSONResponse(status_code=502, content={"detail": str(exc)})

    @application.exception_handler(SecurityError)
    async def _security_error(_: Request, exc: SecurityError) -> JSONResponse:
        return JSONResponse(status_code=500, content={"detail": str(exc)})

    @application.exception_handler(PolicyError)
    async def _policy_error(_: Request, exc: PolicyError) -> JSONResponse:
        return JSONResponse(status_code=400, content={"detail": str(exc)})


def create_app() -> FastAPI:
    application = FastAPI(
        title="Rosalind Policy Service",
        lifespan=_lifespan,
    )

    @application.get("/health", tags=["health"])
    def health() -> dict[str, str]:
        return {"status": "ok"}

    application.include_router(router)
    _register_exception_handlers(application)
    return application


app = create_app()
