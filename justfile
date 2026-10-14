# Rosalind project task runner
#
# Run `just` to see available recipes.

set dotenv-load := true


# ==============================================================================
# General
# ==============================================================================

default:
    @just --list


# ==============================================================================
# Infrastructure (PostgreSQL + SeaweedFS via docker-compose)
# ==============================================================================

up:
    docker compose up -d

down:
    docker compose down

migrate:
    cd backend && just migrate

dev:
    docker compose up -d
    cd backend && uv sync --group ml
    cd backend && just migrate
    cd backend && just serve
dev-mcp:
    docker compose up -d
    cd backend && uv sync --group ml
    cd backend && just migrate
    cd backend && just mcp-serve


# ==============================================================================
# Eval mode (isolated stack: own Postgres, object storage and Keycloak)
# ==============================================================================

# Dedicated Compose project so eval volumes/network never touch the dev stack.
# It binds the same host ports as dev, so the two stacks are mutually exclusive.
eval_compose := "docker compose -p rosalind-eval -f docker-compose.eval.yml"
eval_database_url := "postgresql+psycopg://rosalind:rosalind@localhost:5432/rosalind_eval"

# Start the eval infrastructure
eval-up:
    {{eval_compose}} up -d

# Stop the eval infrastructure (keeps eval volumes)
eval-down:
    {{eval_compose}} down

# Tail eval infrastructure logs
eval-logs:
    {{eval_compose}} logs -f --tail=100

# Wipe only the eval project volumes (throwaway eval data; dev volumes untouched)
eval-reset:
    {{eval_compose}} down -v

# Apply migrations to the eval database
eval-migrate:
    cd backend && ROSALIND_DATABASE_URL={{eval_database_url}} just migrate

# Serve the backend in eval mode (same endpoints as dev: :8000)
eval-serve:
    cd backend && \
        ROSALIND_EVAL__ENABLED=true \
        ROSALIND_DATABASE_URL={{eval_database_url}} \
        uv run uvicorn rosalind.adapters.inbound.http.app:app --port 8000 --reload

# One-shot: eval infra + ml deps + migrations + eval backend
eval-dev:
    just eval-up
    cd backend && uv sync --group ml
    just eval-migrate
    just eval-serve


# ==============================================================================
# Backend
# ==============================================================================

backend-install:
    cd backend && uv sync

backend-install-ml:
    cd backend && uv sync --group ml

backend-format:
    cd backend && just format

backend-lint:
    cd backend && just lint

backend-typecheck:
    cd backend && just typecheck

backend-test:
    cd backend && just test

backend-security:
    cd backend && just security

backend-check:
    cd backend && just check

backend-serve:
    cd backend && just serve

backend-mcp-serve:
    cd backend && just mcp-serve


# ==============================================================================
# CLI
# ==============================================================================

cli-install:
    cd cli && uv sync

cli-format:
    cd cli && just format

cli-lint:
    cd cli && just lint

cli-typecheck:
    cd cli && just typecheck

cli-test:
    cd cli && just test

cli-security:
    cd cli && just security

cli-check:
    cd cli && just check

cli-run *ARGS:
    cd cli && just run {{ARGS}}


# ==============================================================================
# End-to-end tests
# ==============================================================================

e2e-install:
    cd e2e && uv sync

e2e-test:
    cd e2e && uv run pytest -m "not rag"

e2e-test-rag:
    just backend-install-ml
    cd e2e && uv run pytest -m rag


# ==============================================================================
# Shell scripts
# ==============================================================================

shellcheck:
    find . -type f -name '*.sh' -not -path './.git/*' -not -path '*/.venv/*' -exec shellcheck {} +

shfmt:
    find . -type f -name '*.sh' -not -path './.git/*' -not -path '*/.venv/*' -exec shfmt -d {} +


# ==============================================================================
# Docker
# ==============================================================================

docker-lint:
    hadolint backend/Dockerfile

docker-scan:
    docker build --pull -t rosalind backend
    trivy image --exit-code 1 --severity CRITICAL,HIGH --ignore-unfixed rosalind

containers: docker-lint docker-scan


# ==============================================================================
# Secrets
# ==============================================================================

secrets:
    gitleaks git .


# ==============================================================================
# Quality gates
# ==============================================================================

check:
    just backend-format
    just backend-check
    just cli-format
    just cli-check
    just shellcheck
    just shfmt
    just containers
    just secrets
    just e2e-test

ci:
    just backend-check
    just cli-check
    just e2e-test
    just shellcheck
    just shfmt
