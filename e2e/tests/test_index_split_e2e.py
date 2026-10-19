"""End-to-end test for the offline index pipeline.

Creates a dedicated Keycloak user, lets the backend provision its Rosalind
account just-in-time, imports the synthetic mbox through the CLI, runs the full
index pipeline, and verifies the split and canonicalize stages.
"""

from __future__ import annotations

import hashlib
import json
import mailbox
import re
import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from email import message_from_bytes
from email.utils import getaddresses
from pathlib import Path

import psycopg
from support import db

FIXTURE = (
    Path(__file__).resolve().parents[1]
    / "fixtures"
    / "google"
    / "takeout"
    / "Mail"
    / "rosalind_synthetic_emails.mbox"
)
EXPECTED_MESSAGE_COUNT = 18
SELF_EMAIL = "felipe@example.test"
IMPORT_ID_RE = re.compile(r"ID:\s+([0-9a-f-]{36})")


@dataclass(frozen=True)
class ExpectedParticipant:
    role: str
    addr: str
    seq: int


@dataclass(frozen=True)
class ExpectedAttachment:
    filename: str
    declared_mime: str
    payload: bytes
    sha256: str
    storage_key: str


@dataclass(frozen=True)
class ExpectedMessage:
    raw: bytes
    sha256: str
    key: str
    message_id: str | None
    external_id: str
    provider_tags: tuple[str, ...]
    participants: tuple[ExpectedParticipant, ...]
    attachments: tuple[ExpectedAttachment, ...]


@dataclass(frozen=True)
class PipelineContext:
    account_id: str
    source_id: str
    import_id: str
    fixture_bytes: bytes
    expected: list[ExpectedMessage]


def _normalize_message_id(value: str) -> str:
    value = value.strip()
    if value.startswith("<") and value.endswith(">"):
        return value[1:-1].strip()
    return value


def _expected_messages() -> list[ExpectedMessage]:
    mbox = mailbox.mbox(str(FIXTURE))
    try:
        messages = list(mbox)
    finally:
        mbox.close()

    expected: list[ExpectedMessage] = []
    for message in messages:
        raw = message.as_bytes()
        digest = hashlib.sha256(raw).hexdigest()
        header = message.get("Message-ID")
        message_id = _normalize_message_id(str(header)) if header else None
        external_id = message_id or f"no-message-id:{digest}"

        participants: list[ExpectedParticipant] = []
        for role in ("from", "to", "cc", "bcc"):
            seq = 0
            for _name, addr in getaddresses(message.get_all(role.title(), [])):
                if not addr:
                    continue
                participants.append(
                    ExpectedParticipant(
                        role=role,
                        addr=addr.strip().lower(),
                        seq=seq,
                    )
                )
                seq += 1

        labels = message.get("X-Gmail-Labels")
        provider_tags = (
            tuple(tag.strip() for tag in str(labels).split(",") if tag.strip())
            if labels
            else ()
        )

        attachments: list[ExpectedAttachment] = []
        for part in message.walk():
            if (
                part.get_content_disposition() != "attachment"
                or part.get_filename() is None
            ):
                continue
            payload = part.get_payload(decode=True) or b""
            payload_sha = hashlib.sha256(payload).hexdigest()
            attachments.append(
                ExpectedAttachment(
                    filename=part.get_filename(),
                    declared_mime=part.get_content_type(),
                    payload=payload,
                    sha256=payload_sha,
                    storage_key=f"blobs/{payload_sha[:2]}/{payload_sha}",
                )
            )

        expected.append(
            ExpectedMessage(
                raw=raw,
                sha256=digest,
                key=f"records/{digest[:2]}/{digest}",
                message_id=message_id,
                external_id=external_id,
                provider_tags=provider_tags,
                participants=tuple(participants),
                attachments=tuple(attachments),
            )
        )
    return expected


def _parse_events(stdout: str) -> list[dict]:
    events: list[dict] = []
    for line in stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            events.append(json.loads(line))
        except json.JSONDecodeError as exc:
            raise AssertionError(
                f"index emitted a non-JSON line: {line!r}\nfull output:\n{stdout}"
            ) from exc
    return events


def _stage_events(events: list[dict], stage: str) -> list[dict]:
    return [event for event in events if event["stage"] == stage]


def _done_event(events: list[dict], stage: str) -> dict:
    matches = [
        event for event in _stage_events(events, stage) if event["phase"] == "done"
    ]
    assert len(matches) == 1, f"expected one {stage} done event, got {matches}"
    return matches[0]


def _count(conn: psycopg.Connection, sql: str, params=None) -> int:
    return db.query_one(conn, sql, params)[0]


# ---------------------------------------------------------------------------
# Pipeline preparation
# ---------------------------------------------------------------------------


def _setup_test_account(conn: psycopg.Connection, run_rosalind, account) -> str:
    """Provision the dedicated account on its first authenticated API call."""
    assert (
        _count(
            conn,
            "SELECT count(*) FROM account_identity WHERE issuer = %s AND subject = %s",
            (account.issuer, account.subject),
        )
        == 0
    )

    whoami = run_rosalind(["--json", "auth", "whoami"])
    assert whoami.returncode == 0, whoami.stdout + whoami.stderr
    profile = json.loads(whoami.stdout)
    account_id = profile["account_id"]
    assert profile["email"] == account.email

    identity = db.query_one(
        conn,
        "SELECT account_id::text FROM account_identity "
        "WHERE issuer = %s AND subject = %s",
        (account.issuer, account.subject),
    )
    assert identity is not None
    assert identity[0] == account_id
    assert _count(conn, "SELECT count(*) FROM account") == 1
    return account_id


def _create_source(run_rosalind) -> str:
    source = run_rosalind(["--json", "source", "create", "google", "--name", "google"])
    assert source.returncode == 0, source.stdout + source.stderr
    source_body = json.loads(source.stdout)
    assert source_body["name"] == "google"
    return source_body["source_id"]


def _import_test_data(
    conn: psycopg.Connection,
    run_rosalind,
    account_id: str,
    source_id: str,
) -> str:
    fixture_bytes = FIXTURE.read_bytes()
    imported = run_rosalind(
        [
            "import",
            "create",
            "--source",
            "google",
            "--via",
            "file",
            str(FIXTURE),
        ]
    )
    assert imported.returncode == 0, imported.stdout + imported.stderr
    assert "Import completed" in imported.stdout
    match = IMPORT_ID_RE.search(imported.stdout)
    assert match, imported.stdout
    import_id = match.group(1)

    import_row = db.query_one(
        conn,
        "SELECT account_id::text, source_account_id::text, ingestion_status, "
        "processing_status, file_count, total_size "
        "FROM imports WHERE id = %s::uuid",
        (import_id,),
    )
    assert import_row is not None
    (
        row_account_id,
        row_source_id,
        ingestion_status,
        processing_status,
        file_count,
        total_size,
    ) = import_row
    assert row_account_id == account_id
    assert row_source_id == source_id
    assert ingestion_status == "completed"
    assert processing_status == "pending"
    assert file_count == 1
    assert total_size == len(fixture_bytes)

    file_row = db.query_one(
        conn,
        "SELECT path, format, size, sha256, storage_key "
        "FROM import_files WHERE import_id = %s::uuid",
        (import_id,),
    )
    assert file_row is not None
    path, format_, size, sha256, storage_key = file_row
    assert path == FIXTURE.name
    assert format_ == "mbox"
    assert size == len(fixture_bytes)
    assert sha256 == hashlib.sha256(fixture_bytes).hexdigest()
    assert storage_key == f"imports/{import_id}/{FIXTURE.name}"

    listed = run_rosalind(["--json", "import", "list"])
    assert listed.returncode == 0, listed.stdout + listed.stderr
    imports = json.loads(listed.stdout)
    assert [item["import_id"] for item in imports] == [import_id]
    return import_id


def _run_index(run_rosalind, import_id: str) -> list[dict]:
    indexed = run_rosalind(["--json", "index", import_id, "--self-email", SELF_EMAIL])
    assert indexed.returncode == 0, indexed.stdout + indexed.stderr
    events = _parse_events(indexed.stdout)
    assert events
    assert not any(event["phase"] == "error" for event in events)
    return events


# ---------------------------------------------------------------------------
# Stage verification
# ---------------------------------------------------------------------------


def _verify_split_stage(
    ctx: PipelineContext,
    conn: psycopg.Connection,
    s3_client,
    bucket: str,
    events: list[dict],
    *,
    rerun: bool = False,
) -> None:
    expected_created = 0 if rerun else EXPECTED_MESSAGE_COUNT
    expected_reused = EXPECTED_MESSAGE_COUNT if rerun else 0

    split_events = _stage_events(events, "split")
    starts = [event for event in split_events if event["phase"] == "start"]
    progresses = [event for event in split_events if event["phase"] == "progress"]
    assert len(starts) == 1
    assert len(progresses) == 1

    start = starts[0]
    assert start["total_files"] == 1
    assert start["total_bytes"] == len(ctx.fixture_bytes)

    progress = progresses[0]
    assert progress["file"] == FIXTURE.name
    assert progress["processed"] == EXPECTED_MESSAGE_COUNT
    assert progress["created"] == expected_created
    assert progress["reused"] == expected_reused
    assert progress["failed"] == 0

    done = _done_event(events, "split")
    expected_bytes = sum(len(message.raw) for message in ctx.expected)
    assert done["processed"] == EXPECTED_MESSAGE_COUNT
    assert done["created"] == expected_created
    assert done["reused"] == expected_reused
    assert done["failed"] == 0
    assert done["processed_bytes"] == expected_bytes

    records = db.query_all(
        conn,
        "SELECT external_id, payload_sha256, payload_uri, resource_type, "
        "payload, import_id::text, source_account_id::text "
        "FROM raw.source_record WHERE import_id = %s::uuid",
        (ctx.import_id,),
    )
    assert len(records) == EXPECTED_MESSAGE_COUNT
    by_external = {record[0]: record for record in records}
    assert set(by_external) == {message.external_id for message in ctx.expected}
    assert len({record[1] for record in records}) == EXPECTED_MESSAGE_COUNT

    for message in ctx.expected:
        (
            external_id,
            payload_sha256,
            payload_uri,
            resource_type,
            payload,
            record_import_id,
            record_source_id,
        ) = by_external[message.external_id]
        assert external_id == message.external_id
        assert payload_sha256 == message.sha256
        assert payload_uri == message.key
        assert resource_type == "gmail.message"
        assert payload is None
        assert record_import_id == ctx.import_id
        assert record_source_id == ctx.source_id

    listing = s3_client.list_objects_v2(Bucket=bucket, Prefix="records/")
    keys = {obj["Key"] for obj in listing.get("Contents", [])}
    assert keys == {message.key for message in ctx.expected}

    for message in ctx.expected:
        body = s3_client.get_object(Bucket=bucket, Key=message.key)["Body"].read()
        assert body == message.raw

        parsed = message_from_bytes(body)
        header = parsed.get("Message-ID")
        if message.message_id is None:
            assert header is None
        else:
            assert _normalize_message_id(str(header)) == message.message_id

    archive = s3_client.get_object(
        Bucket=bucket, Key=f"imports/{ctx.import_id}/{FIXTURE.name}"
    )["Body"].read()
    assert archive == ctx.fixture_bytes


def _verify_canonicalize_stage(
    ctx: PipelineContext,
    conn: psycopg.Connection,
    s3_client,
    bucket: str,
    events: list[dict],
    *,
    rerun: bool = False,
) -> None:
    expected_created = 0 if rerun else EXPECTED_MESSAGE_COUNT
    expected_reused = EXPECTED_MESSAGE_COUNT if rerun else 0

    canonicalize_events = _stage_events(events, "canonicalize")
    starts = [event for event in canonicalize_events if event["phase"] == "start"]
    assert len(starts) == 1

    done = _done_event(events, "canonicalize")
    assert done["processed"] == EXPECTED_MESSAGE_COUNT
    assert done["created"] == expected_created
    assert done["reused"] == expected_reused
    assert done["failed"] == 0

    messages = db.query_all(
        conn,
        "SELECT message_id, message_id_synthetic, direction, "
        "is_trash_or_spam, has_attachments, occurred_at, parser_version, "
        "canonicalizer_version, content_sha256, text_plain, text_html "
        "FROM core.email_message",
    )
    assert len(messages) == EXPECTED_MESSAGE_COUNT
    by_message_id = {row[0]: row for row in messages}
    expected_ids = {message.external_id for message in ctx.expected}
    assert set(by_message_id) == expected_ids

    expected_trash = {
        message.external_id
        for message in ctx.expected
        if any(tag.lower() in {"spam", "trash"} for tag in message.provider_tags)
    }
    expected_sent = {
        "msg-002@example.test",
        "msg-007@example.test",
        "msg-014@example.test",
    }
    expected_with_attachments = {
        message.external_id for message in ctx.expected if message.attachments
    }
    synthetic = next(message for message in ctx.expected if message.message_id is None)

    for message in ctx.expected:
        row = by_message_id[message.external_id]
        (
            message_id,
            message_id_synthetic,
            direction,
            is_trash_or_spam,
            has_attachments,
            occurred_at,
            parser_version,
            canonicalizer_version,
            content_sha256,
            text_plain,
            text_html,
        ) = row
        assert message_id == message.external_id
        assert message_id_synthetic is (message.external_id == synthetic.external_id)
        assert direction == (
            "sent" if message.external_id in expected_sent else "received"
        )
        assert is_trash_or_spam is (message.external_id in expected_trash)
        assert has_attachments is (message.external_id in expected_with_attachments)
        assert occurred_at is not None
        assert parser_version
        assert canonicalizer_version
        assert content_sha256 is not None
        assert text_plain is not None or text_html is not None

    tags = db.query_all(
        conn,
        "SELECT m.message_id, t.tag FROM core.email_tag t "
        "JOIN core.email_message m ON m.id = t.message_id",
    )
    expected_tags = {
        (message.external_id, f"gmail:{tag}")
        for message in ctx.expected
        for tag in message.provider_tags
    }
    assert set(tags) == expected_tags

    participants = db.query_all(
        conn,
        "SELECT m.message_id, p.role, p.addr_normalized, p.seq "
        "FROM core.email_participant p "
        "JOIN core.email_message m ON m.id = p.message_id",
    )
    expected_participants = {
        (message.external_id, participant.role, participant.addr, participant.seq)
        for message in ctx.expected
        for participant in message.participants
    }
    assert set(participants) == expected_participants

    attachments = db.query_all(
        conn,
        "SELECT m.message_id, a.filename, a.declared_mime, a.disposition, "
        "a.size, a.sha256, a.storage_key, a.status "
        "FROM core.email_attachment a "
        "JOIN core.email_message m ON m.id = a.message_id",
    )
    expected_attachments = [
        (message.external_id, attachment)
        for message in ctx.expected
        for attachment in message.attachments
    ]
    assert len(attachments) == len(expected_attachments)
    by_attachment = {(row[0], row[5]): row for row in attachments}
    for message_id, attachment in expected_attachments:
        row = by_attachment[(message_id, attachment.sha256)]
        (
            _,
            filename,
            declared_mime,
            disposition,
            size,
            sha256,
            storage_key,
            status,
        ) = row
        assert filename == attachment.filename
        assert declared_mime == attachment.declared_mime
        assert disposition == "attachment"
        assert size == len(attachment.payload)
        assert sha256 == attachment.sha256
        assert storage_key == attachment.storage_key
        assert status == "present"

        body = s3_client.get_object(Bucket=bucket, Key=storage_key)["Body"].read()
        assert body == attachment.payload

    assert (
        _count(conn, "SELECT count(*) FROM core.email_message_observation")
        == EXPECTED_MESSAGE_COUNT
    )
    assert (
        _count(
            conn,
            "SELECT count(*) FROM ("
            "  SELECT message_id FROM core.email_message_observation "
            "  GROUP BY message_id HAVING count(*) <> 1"
            ") AS non_singleton",
        )
        == 0
    )
    observed_records = {
        row[0]
        for row in db.query_all(
            conn,
            "SELECT source_record_id::text FROM core.email_message_observation",
        )
    }
    raw_records = {
        row[0]
        for row in db.query_all(
            conn,
            "SELECT id::text FROM raw.source_record WHERE import_id = %s::uuid",
            (ctx.import_id,),
        )
    }
    assert observed_records == raw_records

    assert (
        db.query_one(
            conn,
            "SELECT processing_status FROM imports WHERE id = %s::uuid",
            (ctx.import_id,),
        )[0]
        == "pending"
    )


# ---------------------------------------------------------------------------
# Main test
# ---------------------------------------------------------------------------


def test_cli_import_and_index_pipeline(
    split_account,
    split_run_rosalind: Callable[[list[str]], subprocess.CompletedProcess[str]],
    split_pg_conn: psycopg.Connection,
    split_bucket: str,
    s3_client,
) -> None:
    expected = _expected_messages()
    assert len(expected) == EXPECTED_MESSAGE_COUNT
    fixture_bytes = FIXTURE.read_bytes()

    account_id = _setup_test_account(split_pg_conn, split_run_rosalind, split_account)
    source_id = _create_source(split_run_rosalind)
    import_id = _import_test_data(
        split_pg_conn, split_run_rosalind, account_id, source_id
    )
    ctx = PipelineContext(
        account_id=account_id,
        source_id=source_id,
        import_id=import_id,
        fixture_bytes=fixture_bytes,
        expected=expected,
    )

    events = _run_index(split_run_rosalind, import_id)
    _verify_split_stage(ctx, split_pg_conn, s3_client, split_bucket, events)
    _verify_canonicalize_stage(ctx, split_pg_conn, s3_client, split_bucket, events)

    rerun_events = _run_index(split_run_rosalind, import_id)
    _verify_split_stage(
        ctx,
        split_pg_conn,
        s3_client,
        split_bucket,
        rerun_events,
        rerun=True,
    )
    _verify_canonicalize_stage(
        ctx,
        split_pg_conn,
        s3_client,
        split_bucket,
        rerun_events,
        rerun=True,
    )
