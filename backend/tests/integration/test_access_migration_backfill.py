"""Verify migration 0022 backfills role handles from canonical participants."""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from rosalind.adapters.outbound.persistence import models
from tests._db import reset_schemas


def test_role_handles_are_backfilled(postgres_url: str) -> None:
    engine = create_engine(postgres_url)
    reset_schemas(engine)
    cfg = Config("alembic.ini")
    cfg.set_main_option("sqlalchemy.url", postgres_url)

    try:
        command.upgrade(cfg, "0021")
        factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
        sent_at = datetime(2026, 3, 17, 9, 32, tzinfo=UTC)
        with factory() as session:
            source = models.SourceAccount(
                provider="google", name="backfill-test", metadata_={}
            )
            session.add(source)
            session.flush()
            message = models.EmailMessage(
                id=uuid.uuid4(),
                source_account_id=source.id,
                message_id="backfill-message",
                message_id_synthetic=False,
                occurred_at=sent_at,
                direction="received",
                subject="subject",
                has_attachments=False,
                is_trash_or_spam=False,
                parser_version="p/1",
                canonicalizer_version="c/1",
                metadata_={},
            )
            session.add(message)
            session.flush()
            participants = [
                ("from", "john@acme.com"),
                ("to", "mary@example.com"),
                ("cc", "alex@example.com"),
                ("bcc", "secret@example.com"),
            ]
            for seq, (role, address) in enumerate(participants):
                session.add(
                    models.EmailParticipant(
                        id=uuid.uuid4(),
                        message_id=message.id,
                        role=role,
                        addr=address,
                        addr_normalized=address,
                        seq=seq,
                    )
                )
            session.commit()
            message_id = message.id
            source_id = source.id
            source_num = source.num

        with engine.begin() as connection:
            connection.execute(
                text(
                    """
                    INSERT INTO search.chunk (
                        id, email_id, chunk_kind, seq, text_for_display,
                        text_for_index, text_sha256, language, index_version,
                        source_account_id, source_account_num, sent_at,
                        sender_handle, recipient_handles, participant_handles,
                        direction, has_attachment, is_trash_or_spam, tags, meta,
                        created_at
                    ) VALUES (
                        :id, :email_id, 'email_body', 0, 'hello', 'hello',
                        'sha', 'en', 'v1', :source_id, :source_num, :sent_at,
                        'john@acme.com', :recipients, :participants, 'received',
                        false, false, :tags, :meta, :created_at
                    )
                    """
                ),
                {
                    "id": uuid.uuid4(),
                    "email_id": message_id,
                    "source_id": source_id,
                    "source_num": source_num,
                    "sent_at": sent_at,
                    "recipients": ["mary@example.com"],
                    "participants": [address for _, address in participants],
                    "tags": [],
                    "meta": json.dumps({}),
                    "created_at": sent_at,
                },
            )

        command.upgrade(cfg, "0022")

        with engine.connect() as connection:
            row = connection.execute(
                text(
                    "SELECT from_handles, to_handles, cc_handles, bcc_handles "
                    "FROM search.chunk"
                )
            ).one()

        assert row[0] == ["john@acme.com"]
        assert row[1] == ["mary@example.com"]
        assert row[2] == ["alex@example.com"]
        assert row[3] == ["secret@example.com"]
    finally:
        reset_schemas(engine)
        engine.dispose()
