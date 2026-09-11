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
    cd backend && uv sync

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
    just backend-check
    just cli-check
    just shellcheck
    just shfmt
    just containers
    just secrets

ci: 
    just backend-check
    just cli-check
    just shellcheck
    just shfmt