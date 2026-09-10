# Rosalind project task runner
#
# Run `just` to see available recipes.


# ==============================================================================
# General
# ==============================================================================

default:
    @just --list


# ==============================================================================
# Backend
# ==============================================================================

backend-install:
    uv sync --directory backend

backend-format:
    uv run --directory backend ruff format .

backend-format-check:
    uv run --directory backend ruff format --check .

backend-lint:
    uv run --directory backend ruff check .

backend-typecheck:
    uv run --directory backend mypy .

backend-test:
    uv run --directory backend pytest

backend-security:
    uv run --directory backend bandit -r src
    uv run --directory backend pip-audit

backend-check: backend-format-check backend-lint backend-typecheck backend-test backend-security

backend-serve:
    uv run --directory backend uvicorn rosalind.api.app:app --reload


# ==============================================================================
# Shell scripts
# ==============================================================================

shellcheck:
    shellcheck scripts/**/*.sh

shfmt:
    shfmt -d scripts/


# ==============================================================================
# Docker
# ==============================================================================

docker-lint:
    hadolint backend/Dockerfile


# ==============================================================================
# Secrets
# ==============================================================================

secrets:
    gitleaks detect


# ==============================================================================
# Container security
# ==============================================================================

container-security:
    trivy fs .


# ==============================================================================
# Quality gates
# ==============================================================================

format:
    just backend-format

format-check:
    just backend-format-check

lint:
    just backend-lint

typecheck:
    just backend-typecheck

test:
    just backend-test

security: backend-security secrets

containers: docker-lint container-security

check: format-check lint typecheck test security

ci: check shellcheck shfmt containers