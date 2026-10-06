"""Email embed stage: compute vectors for ``search.chunk`` rows.

Orchestrates the work finder → compute → guarded-write loop. Staleness is
detected by comparing hashes (a chunk's ``emb_*_text_sha256`` against its
``text_sha256``), not by trusting writers, so a chunker rebuild that leaves a
chunk's text unchanged keeps its embedding for free. Writes are guarded: a
vector is written only if the chunk's ``text_sha256`` still equals the one that
was embedded.

Failures are isolated: a text that cannot be embedded (overlong, rejected) is
bisected out of its batch and recorded in ``embedding_failure``; transient
failures stop the run with progress committed.
"""

from __future__ import annotations

import time
import uuid
from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime

from rosalind.application.ports.embedding import (
    Embedder,
    EmbeddingFailureRow,
    EmbeddingRunRow,
    EmbedWrite,
    TransientEmbeddingError,
)
from rosalind.application.ports.unit_of_work import UnitOfWork
from rosalind.domain.search import TokenCounter, validate_vector

DEFAULT_WINDOW = 2048
DEFAULT_BATCH_TOKENS = 4096


@dataclass(frozen=True)
class EmbedOutcome:
    embedded: int
    reused: int
    skipped_not_embeddable: int
    failed: int
    blocked_reason: str | None = None
    budget_exhausted: bool = False


def _group_by_text(work: list) -> dict[str, list]:
    """Group work items by identical text, preserving first-seen order."""
    groups: dict[str, list] = defaultdict(list)
    for item in work:
        groups[item.text].append(item)
    return groups


def _token_batches(
    groups: dict[str, list], counter: TokenCounter, batch_tokens: int
) -> list[list[tuple[str, list]]]:
    """Pack unique texts into batches bounded by a token budget."""
    batches: list[list[tuple[str, list]]] = []
    current: list[tuple[str, list]] = []
    current_tokens = 0
    for text, items in groups.items():
        tokens = counter.count(text)
        if current and current_tokens + tokens > batch_tokens:
            batches.append(current)
            current = []
            current_tokens = 0
        current.append((text, items))
        current_tokens += tokens
    if current:
        batches.append(current)
    return batches


class EmailEmbeddingService:
    def __init__(
        self,
        embedder: Embedder,
        counter: TokenCounter,
        *,
        embed_quotes: bool,
        embed_trash_spam: bool,
        allow_remote_embedding: bool,
        window: int = DEFAULT_WINDOW,
        batch_tokens: int = DEFAULT_BATCH_TOKENS,
        norm_tolerance: float = 1e-3,
    ):
        self._embedder = embedder
        self._counter = counter
        self._embed_quotes = embed_quotes
        self._embed_trash_spam = embed_trash_spam
        self._allow_remote_embedding = allow_remote_embedding
        self._window = window
        self._batch_tokens = batch_tokens
        self._norm_tolerance = norm_tolerance

    def embed(
        self,
        uow: UnitOfWork,
        source_account_id: uuid.UUID,
        *,
        budget_seconds: float | None = None,
        retry_failed: bool = False,
    ) -> EmbedOutcome:
        """Embed chunks that need a vector, most recent first."""
        if self._embedder.locality == "remote" and not self._allow_remote_embedding:
            return EmbedOutcome(
                0,
                0,
                0,
                0,
                blocked_reason=(
                    "embedder is remote; set allow_remote_embedding=true to opt in"
                ),
            )

        space = self._embedder.space
        started_at = datetime.now(UTC)
        deadline = (
            time.monotonic() + budget_seconds if budget_seconds is not None else None
        )

        skipped = uow.embeddings.count_not_embeddable(
            source_account_id=source_account_id,
            embed_quotes=self._embed_quotes,
            embed_trash_spam=self._embed_trash_spam,
        )

        embedded = 0
        reused = 0
        failed = 0
        budget_exhausted = False
        blocked: str | None = None

        while True:
            if deadline is not None and time.monotonic() > deadline:
                budget_exhausted = True
                break

            work = uow.embeddings.find_embed_work(
                space=space,
                source_account_id=source_account_id,
                embed_quotes=self._embed_quotes,
                embed_trash_spam=self._embed_trash_spam,
                retry_failed=retry_failed,
                limit=self._window,
            )
            if not work:
                break

            groups = _group_by_text(work)
            batches = _token_batches(groups, self._counter, self._batch_tokens)

            for batch in batches:
                texts = [text for text, _ in batch]
                ok, failures, transient = self._embed_texts(texts)
                failure_by_text = dict(failures)

                writes: list[EmbedWrite] = []
                for text, items in batch:
                    if text in ok:
                        vector = ok[text]
                        validate_vector(
                            vector, space, norm_tolerance=self._norm_tolerance
                        )
                        for item in items:
                            writes.append(
                                EmbedWrite(
                                    chunk_id=item.chunk_id,
                                    vector=vector,
                                    expected_text_sha256=item.text_sha256,
                                )
                            )
                        embedded += 1
                        reused += len(items) - 1
                    elif text in failure_by_text:
                        for item in items:
                            uow.embeddings.record_failure(
                                row=EmbeddingFailureRow(
                                    chunk_id=item.chunk_id,
                                    space=space.name,
                                    text_sha256=item.text_sha256,
                                    error=failure_by_text[text],
                                    attempts=1,
                                    last_attempt_at=started_at,
                                )
                            )
                            failed += 1

                if writes:
                    uow.embeddings.write_embeddings(space=space, writes=writes)

                if transient is not None:
                    blocked = transient
                    break

            if blocked is not None:
                break

            uow.commit()

        # Record the run even when blocked (disclosure ledger).
        uow.embeddings.record_run(
            row=EmbeddingRunRow(
                space=space.name,
                started_at=started_at,
                finished_at=datetime.now(UTC),
                host=self._embedder.host,
                device_class=self._embedder.device_class,
                dtype=space.dtype,
                revision=space.revision,
                locality=self._embedder.locality,
                chunks_embedded=embedded,
                chunks_failed=failed,
            )
        )
        uow.commit()

        return EmbedOutcome(
            embedded=embedded,
            reused=reused,
            skipped_not_embeddable=skipped,
            failed=failed,
            blocked_reason=blocked,
            budget_exhausted=budget_exhausted,
        )

    def _embed_texts(
        self, texts: list[str]
    ) -> tuple[dict[str, list[float]], list[tuple[str, str]], str | None]:
        """Embed unique texts, bisecting out non-transient failures.

        Returns ``(ok, failures, transient)``: ``ok`` maps text → vector,
        ``failures`` lists ``(text, error)`` for each unembeddable text, and
        ``transient`` is set when a retryable error aborts the batch.
        """
        ok: dict[str, list[float]] = {}
        failures: list[tuple[str, str]] = []
        transient: str | None = None

        def attempt(group: list[str]) -> None:
            nonlocal transient
            if transient is not None:
                return
            try:
                vectors = self._embedder.embed_documents(group)
            except TransientEmbeddingError as exc:
                transient = str(exc)
                return
            except Exception as exc:  # noqa: BLE001 - bisect to the offender
                if len(group) == 1:
                    failures.append((group[0], str(exc)))
                else:
                    mid = len(group) // 2
                    attempt(group[:mid])
                    attempt(group[mid:])
                return
            for text, vector in zip(group, vectors):
                ok[text] = vector

        attempt(texts)
        return ok, failures, transient
