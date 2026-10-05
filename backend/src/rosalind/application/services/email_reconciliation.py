"""Email thread reconciliation service.

Turns each message's reply chain into a canonical thread root and applies it
across the whole source account. Pure root computation lives in
``domain.email.threading``; this service only orchestrates load → compute →
write, so it contains no SQL and no graph logic.
"""

from __future__ import annotations

import uuid

from rosalind.application.ports.repositories import ThreadReconcileResult
from rosalind.application.ports.unit_of_work import UnitOfWork
from rosalind.domain.email import compute_thread_roots


class EmailReconciliationService:
    def reconcile(
        self, uow: UnitOfWork, source_account_id: uuid.UUID
    ) -> ThreadReconcileResult:
        edges = uow.email_canonical.list_thread_edges(source_account_id)
        roots = compute_thread_roots(edges)
        result = uow.email_canonical.reconcile_threads(source_account_id, roots)
        uow.commit()
        return result
