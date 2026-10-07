import hashlib
import math
import random
import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select, update

from rosalind.adapters import composition
from rosalind.adapters.outbound.persistence import models
from rosalind.application.ports.embedding import EmbeddingError, EmbedWrite
from rosalind.application.services.chunking import EmailChunkingService
from rosalind.application.services.embedding import EmailEmbeddingService
from rosalind.domain.search import ChunkingParams, EmbeddingSpace
from tests._account import ensure_account

_SENT_AT = datetime(2026, 3, 17, 9, 32, tzinfo=UTC)

_SPACE = EmbeddingSpace(
    name="bge_m3_v1",
    model_id="BAAI/bge-m3",
    revision="t",
    dtype="float16",
    dimension=1024,
    normalized=True,
    column="emb_bge_m3_v1",
)


def _vector(text: str) -> list[float]:
    rng = random.Random(
        int.from_bytes(hashlib.sha256(text.encode()).digest()[:8], "big")
    )
    vals = [rng.uniform(-1, 1) for _ in range(_SPACE.dimension)]
    norm = math.sqrt(sum(v * v for v in vals))
    return [v / norm for v in vals]


class _CharCounter:
    def __init__(self, version: str = "char/1"):
        self._version = version

    @property
    def version(self) -> str:
        return self._version

    def count(self, text: str) -> int:
        return len(text)

    def split_boundaries(self, text: str, max_tokens: int) -> list[int]:
        return list(range(0, len(text), max_tokens)) + [len(text)]


class _FakeEmbedder:
    def __init__(self, *, fail=None, locality="local"):
        self._fail = set(fail or ())
        self._locality = locality

    @property
    def space(self):
        return _SPACE

    @property
    def locality(self):
        return self._locality

    @property
    def host(self):
        return "fake"

    @property
    def device_class(self):
        return "cpu"

    def embed_documents(self, texts):
        for text in texts:
            if text in self._fail:
                raise EmbeddingError("rejected")
        return [_vector(text) for text in texts]

    def embed_query(self, text):
        return _vector(text)


def _params() -> ChunkingParams:
    return ChunkingParams(
        target_tokens=200,
        max_tokens=480,
        overlap_tokens=20,
        min_tail_tokens=40,
        max_quote_tokens_per_email=1000,
        max_chunks_per_attachment=10,
        include_signature=True,
    )


def _chunker() -> EmailChunkingService:
    return EmailChunkingService(counter=_CharCounter(), params=_params())


def _embedder(**kwargs) -> EmailEmbeddingService:
    defaults: dict[str, Any] = {
        "embedder": _FakeEmbedder(),
        "counter": _CharCounter(),
        "embed_quotes": False,
        "embed_trash_spam": False,
        "allow_remote_embedding": True,
        "window": 100,
        "batch_tokens": 10000,
    }
    defaults.update(kwargs)
    return EmailEmbeddingService(**defaults)


def _make_source(uow) -> uuid.UUID:
    account_id = ensure_account(uow).id
    source = composition.source_service.create_source(
        uow, account_id, provider="google", name="google-personal"
    )
    uow.commit()
    return source.id


def _insert_email(
    db_session,
    source_id: uuid.UUID,
    message_id: str,
    *,
    body: str = "hello body",
    quoted: str | None = "> quoted line",
    is_trash_or_spam: bool = False,
) -> uuid.UUID:
    message = models.EmailMessage(
        id=uuid.uuid4(),
        source_account_id=source_id,
        message_id=message_id,
        message_id_synthetic=False,
        occurred_at=_SENT_AT,
        direction="received",
        has_attachments=False,
        is_trash_or_spam=is_trash_or_spam,
        parser_version="p/1",
        canonicalizer_version="c/1",
        metadata_={},
    )
    db_session.add(message)
    db_session.flush()

    db_session.add(
        models.EmailParticipant(
            id=uuid.uuid4(),
            message_id=message.id,
            role="from",
            name="Mike Turner",
            addr="mike@turnerroofing.com",
            addr_normalized="mike@turnerroofing.com",
            seq=0,
        )
    )

    clean_text = body
    segments = [
        models.EmailSegment(
            id=uuid.uuid4(),
            email_id=message.id,
            seq=0,
            kind="new",
            start_offset=0,
            end_offset=len(body),
            quote_depth=0,
        )
    ]
    if quoted:
        start = len(clean_text) + 1
        clean_text = f"{clean_text}\n{quoted}"
        segments.append(
            models.EmailSegment(
                id=uuid.uuid4(),
                email_id=message.id,
                seq=1,
                kind="quoted",
                start_offset=start,
                end_offset=len(clean_text),
                quote_depth=1,
            )
        )

    db_session.add(
        models.EmailText(
            email_id=message.id,
            clean_text=clean_text,
            clean_method="plain",
            status="done",
            stage_version="enrich/1",
            input_sha256="abc",
            segments_digest=f"digest-{message_id}",
        )
    )
    db_session.add_all(segments)
    db_session.commit()
    return message.id


def _chunks(db_session, email_id: uuid.UUID) -> list[models.Chunk]:
    return list(
        db_session.scalars(
            select(models.Chunk)
            .where(models.Chunk.email_id == email_id)
            .order_by(models.Chunk.chunk_kind, models.Chunk.seq)
        ).all()
    )


def _chunk(uow, source_id) -> None:
    _chunker().chunk(uow, source_id)
    uow.commit()


def _embed(uow, source_id, **kwargs) -> int:
    outcome = _embedder(**kwargs).embed(uow, source_id)
    uow.commit()
    return outcome.embedded


def test_embed_and_rerun_is_noop(uow, db_session) -> None:
    source_id = _make_source(uow)
    email_id = _insert_email(db_session, source_id, "a@x")
    _chunk(uow, source_id)

    assert _embed(uow, source_id) >= 1  # body embedded, quote skipped by default
    body_chunks = [
        c for c in _chunks(db_session, email_id) if c.chunk_kind == "email_body"
    ]
    assert body_chunks
    assert all(c.emb_bge_m3_v1 is not None for c in body_chunks)

    assert _embed(uow, source_id) == 0  # re-run is a no-op


def test_quote_not_embedded_by_default(uow, db_session) -> None:
    source_id = _make_source(uow)
    email_id = _insert_email(db_session, source_id, "a@x", quoted="> quote text")
    _chunk(uow, source_id)

    _embed(uow, source_id)
    kinds = {c.chunk_kind: c.emb_bge_m3_v1 for c in _chunks(db_session, email_id)}
    assert kinds["email_body"] is not None
    assert kinds["email_quote"] is None

    # Enabling embed_quotes queues quotes without rebuilding chunks.
    assert _embed(uow, source_id, embed_quotes=True) >= 1
    kinds = {c.chunk_kind: c.emb_bge_m3_v1 for c in _chunks(db_session, email_id)}
    assert kinds["email_quote"] is not None


def test_spam_skipped_then_queued_when_unspammed(uow, db_session) -> None:
    source_id = _make_source(uow)
    email_id = _insert_email(db_session, source_id, "a@x", is_trash_or_spam=True)
    _chunk(uow, source_id)

    _embed(uow, source_id)
    body = _chunks(db_session, email_id)[0]
    assert body.emb_bge_m3_v1 is None

    db_session.execute(
        update(models.EmailMessage)
        .where(models.EmailMessage.id == email_id)
        .values(is_trash_or_spam=False, updated_at=datetime.now(UTC))
    )
    db_session.commit()
    _chunk(uow, source_id)

    assert _embed(uow, source_id) >= 1
    assert _chunks(db_session, email_id)[0].emb_bge_m3_v1 is not None


def test_changed_text_invalidates(uow, db_session) -> None:
    source_id = _make_source(uow)
    email_id = _insert_email(db_session, source_id, "a@x", body="first version")
    _chunk(uow, source_id)
    _embed(uow, source_id)

    before = _chunks(db_session, email_id)[0].emb_bge_m3_v1
    assert before is not None

    db_session.execute(
        update(models.EmailText)
        .where(models.EmailText.email_id == email_id)
        .values(clean_text="second version", segments_digest="digest-changed")
    )
    db_session.commit()
    _chunk(uow, source_id)

    # The chunk upsert must not touch the embedding columns: the stale vector
    # is kept, and the hash comparison re-queues it below.
    assert _chunks(db_session, email_id)[0].emb_bge_m3_v1 == before

    assert _embed(uow, source_id) >= 1
    after = _chunks(db_session, email_id)[0].emb_bge_m3_v1
    assert after is not None
    assert after != before


def test_unchanged_rebuild_keeps_embedding(uow, db_session) -> None:
    source_id = _make_source(uow)
    email_id = _insert_email(db_session, source_id, "a@x", body="stable text")
    _chunk(uow, source_id)
    _embed(uow, source_id)

    before = _chunks(db_session, email_id)[0].emb_bge_m3_v1

    # A chunk rebuild with unchanged text must not clear the embedding.
    _chunk(uow, source_id)
    assert _embed(uow, source_id) == 0
    assert _chunks(db_session, email_id)[0].emb_bge_m3_v1 == before


def test_guarded_write_skips_stale_chunk(uow, db_session) -> None:
    source_id = _make_source(uow)
    email_id = _insert_email(db_session, source_id, "a@x")
    _chunk(uow, source_id)

    chunk = _chunks(db_session, email_id)[0]
    stale_sha = chunk.text_sha256

    # Simulate an edit landing between read and write.
    db_session.execute(
        update(models.Chunk)
        .where(models.Chunk.id == chunk.id)
        .values(text_sha256="changed-after-read")
    )
    db_session.commit()

    written = uow.embeddings.write_embeddings(
        space=_SPACE,
        writes=[
            EmbedWrite(
                chunk_id=chunk.id, vector=_vector("x"), expected_text_sha256=stale_sha
            )
        ],
    )
    uow.commit()
    assert written == []

    # With the correct hash the write succeeds.
    written = uow.embeddings.write_embeddings(
        space=_SPACE,
        writes=[
            EmbedWrite(
                chunk_id=chunk.id,
                vector=_vector("x"),
                expected_text_sha256="changed-after-read",
            )
        ],
    )
    uow.commit()
    assert written == [chunk.id]


def test_failure_recorded_skipped_and_retried(uow, db_session) -> None:
    source_id = _make_source(uow)
    email_id = _insert_email(db_session, source_id, "a@x", body="rejected text")
    _chunk(uow, source_id)
    chunk = _chunks(db_session, email_id)[0]

    outcome = _embedder(embedder=_FakeEmbedder(fail={chunk.text_for_index})).embed(
        uow, source_id
    )
    uow.commit()
    assert outcome.failed >= 1
    assert chunk.emb_bge_m3_v1 is None

    # Ordinary re-run skips the failed chunk.
    assert _embed(uow, source_id) == 0

    # retry_failed re-attempts it (and now the embedder succeeds).
    outcome = _embedder().embed(uow, source_id, retry_failed=True)
    uow.commit()
    assert outcome.embedded >= 1
    assert _chunks(db_session, email_id)[0].emb_bge_m3_v1 is not None


def test_halfvec_round_trip_within_tolerance(uow, db_session) -> None:
    source_id = _make_source(uow)
    email_id = _insert_email(db_session, source_id, "a@x", body="round trip")
    _chunk(uow, source_id)
    _embed(uow, source_id)

    chunk = _chunks(db_session, email_id)[0]
    original = _vector(chunk.text_for_index)
    stored = chunk.emb_bge_m3_v1
    assert stored is not None
    similarity = sum(a * b for a, b in zip(original, stored))
    assert similarity > 0.999


def test_resync_preserves_embeddings(uow, db_session) -> None:
    source_id = _make_source(uow)
    email_id = _insert_email(db_session, source_id, "a@x", body="resync text")
    _chunk(uow, source_id)
    _embed(uow, source_id)

    before = _chunks(db_session, email_id)[0].emb_bge_m3_v1
    assert before is not None

    # A full chunk + embed re-run (same versions) preserves the vector.
    _chunk(uow, source_id)
    _embed(uow, source_id)
    assert _chunks(db_session, email_id)[0].emb_bge_m3_v1 == before
