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
    find . -type f -name '*.sh' -not -path './.git/*' -exec shellcheck {} +

shfmt:
    find . -type f -name '*.sh' -not -path './.git/*' -exec shfmt -d {} +


# ==============================================================================
# Docker
# ==============================================================================

docker-lint:
    hadolint backend/Dockerfile

docker-scan:
    trivy fs .

containers: docker-lint docker-scan


# ==============================================================================
# Secrets
# ==============================================================================

secrets:
    gitleaks git .


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

security:
    just backend-security


# Fast local quality gate
check: format-check lint typecheck test security shellcheck shfmt containers secrets

# Complete CI quality gate
ci: format-check lint typecheck test security shellcheck shfmt containers