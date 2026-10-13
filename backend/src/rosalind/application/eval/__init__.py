"""Evaluation subsystem (application layer).

Pure types and logic for auditing the search pipeline: dataset schema, metrics,
failure funnel, statistics, experiment config, stage-cache key logic, and the
mapping from a ``SearchTrace`` to an eval record. Concrete I/O lives in
``rosalind.adapters.outbound.eval`` and inbound HTTP in
``rosalind.adapters.inbound.http.routes.eval``; use cases live in
``rosalind.application.services.eval``.

This package is eval-only: non-eval application code must not import it.
"""
