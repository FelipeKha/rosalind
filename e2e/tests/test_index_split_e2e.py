"""End-to-end test for the offline index pipeline.

Creates a dedicated Keycloak user, lets the backend provision its Rosalind
account just-in-time, imports the synthetic mbox through the CLI, runs the full
index pipeline, and verifies the split, canonicalize, reconcile, enrich,
attachments, and chunk stages.
"""

from __future__ import annotations

import hashlib
import json
import mailbox
import re
import subprocess
from collections import Counter
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
EXPECTED_ENRICH_STAGE_VERSION = "enrich/1+selectolax/1+lingua/2"
EXPECTED_ATTACHMENT_STAGE_VERSION = "attachments/1"
EXPECTED_ATTACHMENT_ERROR = "PDF has no text layer"
EXPECTED_CHUNK_COUNT = 19
EXPECTED_BODY_CHUNK_COUNT = 18
EXPECTED_QUOTE_CHUNK_COUNT = 1
EXPECTED_CHUNK_BUILD_COUNT = 19
IMPORT_ID_RE = re.compile(r"ID:\s+([0-9a-f-]{36})")

THREAD_ROOT_OVERRIDES = {
    "msg-002@example.test": "msg-001@example.test",
    "msg-003@example.test": "msg-001@example.test",
    "msg-007@example.test": "msg-006@example.test",
    "msg-017@example.test": "msg-root-migration@example.test",
}


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


def _expected_thread_roots(ctx: PipelineContext) -> dict[str, str]:
    """Every message is its own root unless it belongs to a reply chain."""
    roots = {message.external_id: message.external_id for message in ctx.expected}
    assert set(THREAD_ROOT_OVERRIDES) <= set(roots)
    roots.update(THREAD_ROOT_OVERRIDES)
    return roots


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


def _verify_reconcile_stage(
    ctx: PipelineContext,
    conn: psycopg.Connection,
    events: list[dict],
) -> dict[str, str]:
    reconcile_events = _stage_events(events, "reconcile")
    starts = [event for event in reconcile_events if event["phase"] == "start"]
    assert len(starts) == 1

    done = _done_event(events, "reconcile")
    assert done["details"] == {
        "threads_created": 0,
        "threads_removed": 0,
        "messages_reassigned": 0,
    }

    expected_roots = _expected_thread_roots(ctx)
    rows = db.query_all(
        conn,
        "SELECT m.message_id, t.root_message_id, m.thread_changed_at, "
        "m.thread_id::text "
        "FROM core.email_message m "
        "JOIN core.email_thread t ON t.id = m.thread_id",
    )
    assert len(rows) == EXPECTED_MESSAGE_COUNT

    roots: dict[str, str] = {}
    thread_ids: dict[str, str] = {}
    for message_id, root_message_id, thread_changed_at, thread_id in rows:
        roots[message_id] = root_message_id
        thread_ids[message_id] = thread_id
        assert thread_changed_at is None
    assert roots == expected_roots

    assert thread_ids["msg-001@example.test"] == thread_ids["msg-002@example.test"]
    assert thread_ids["msg-001@example.test"] == thread_ids["msg-003@example.test"]
    assert thread_ids["msg-006@example.test"] == thread_ids["msg-007@example.test"]
    assert thread_ids["msg-017@example.test"] != thread_ids["msg-005@example.test"]

    synthetic = next(message for message in ctx.expected if message.message_id is None)
    assert thread_ids[synthetic.external_id] is not None

    thread_counts = dict(
        db.query_all(
            conn,
            "SELECT t.root_message_id, count(*) "
            "FROM core.email_thread t "
            "JOIN core.email_message m ON m.thread_id = t.id "
            "GROUP BY t.root_message_id",
        )
    )
    expected_counts = Counter(expected_roots.values())
    assert thread_counts == dict(expected_counts)
    assert _count(conn, "SELECT count(*) FROM core.email_thread") == len(
        expected_counts
    )
    assert (
        _count(
            conn,
            "SELECT count(*) FROM core.email_thread t "
            "LEFT JOIN core.email_message m ON m.thread_id = t.id "
            "WHERE m.id IS NULL",
        )
        == 0
    )
    assert (
        _count(
            conn,
            "SELECT count(*) FROM core.email_thread WHERE provider_hint IS NOT NULL",
        )
        == 0
    )

    return thread_ids


def _verify_enrich_stage(
    ctx: PipelineContext,
    conn: psycopg.Connection,
    events: list[dict],
    *,
    rerun: bool = False,
) -> tuple[list[tuple], list[tuple]]:
    enrich_events = _stage_events(events, "enrich")
    starts = [event for event in enrich_events if event["phase"] == "start"]
    assert len(starts) == 1

    done = _done_event(events, "enrich")
    expected_processed = 0 if rerun else EXPECTED_MESSAGE_COUNT
    expected_done = 0 if rerun else EXPECTED_MESSAGE_COUNT
    assert done["processed"] == expected_processed
    assert done["details"] == {
        "done": expected_done,
        "empty": 0,
        "failed": 0,
        "budget_exhausted": False,
    }

    texts = db.query_all(
        conn,
        "SELECT m.message_id, t.clean_text, t.clean_method, t.status, "
        "t.error, t.stage_version, t.input_sha256, t.segments_digest, "
        "t.created_at, t.updated_at, m.content_sha256 "
        "FROM derived.email_text t "
        "JOIN core.email_message m ON m.id = t.email_id "
        "ORDER BY m.message_id",
    )
    assert len(texts) == EXPECTED_MESSAGE_COUNT
    assert {row[0] for row in texts} == {
        message.external_id for message in ctx.expected
    }

    clean_by_id: dict[str, str] = {}
    for row in texts:
        (
            message_id,
            clean_text,
            clean_method,
            status,
            error,
            stage_version,
            input_sha256,
            segments_digest,
            _created_at,
            _updated_at,
            content_sha256,
        ) = row
        clean_by_id[message_id] = clean_text
        assert clean_text
        assert status == "done"
        assert error is None
        assert stage_version == EXPECTED_ENRICH_STAGE_VERSION
        assert input_sha256 == content_sha256
        assert segments_digest is not None
        assert clean_method == (
            "html" if message_id == "msg-015@example.test" else "plain"
        )

    assert "réunion" in clean_by_id["msg-006@example.test"]
    assert "25 March" in clean_by_id["msg-015@example.test"]
    assert "> 12 March works for me" in clean_by_id["msg-003@example.test"]

    segments = db.query_all(
        conn,
        "SELECT m.message_id, s.seq, s.kind, s.start_offset, s.end_offset, "
        "s.language, s.language_confidence, s.quote_depth, "
        "s.attribution_raw, s.quoted_author, s.quoted_at, "
        "s.covered_by_email_id, s.coverage_checked_at "
        "FROM derived.email_segment s "
        "JOIN core.email_message m ON m.id = s.email_id "
        "ORDER BY m.message_id, s.seq",
    )
    assert len(segments) == 20

    by_message: dict[str, list[tuple]] = {}
    for segment in segments:
        by_message.setdefault(segment[0], []).append(segment)

    assert set(by_message) == set(clean_by_id)
    kinds = Counter(segment[2] for segment in segments)
    assert kinds == {"new": 19, "quoted": 1}

    languages: Counter = Counter()
    for message_id, message_segments in by_message.items():
        clean_text = clean_by_id[message_id]
        assert [segment[1] for segment in message_segments] == list(
            range(len(message_segments))
        )
        assert any(segment[2] == "new" for segment in message_segments)

        previous_end = 0
        for segment in message_segments:
            (
                _message_id,
                _seq,
                kind,
                start_offset,
                end_offset,
                language,
                language_confidence,
                quote_depth,
                attribution_raw,
                quoted_author,
                quoted_at,
                covered_by_email_id,
                coverage_checked_at,
            ) = segment
            assert start_offset == previous_end
            assert end_offset > start_offset
            previous_end = end_offset

            assert attribution_raw is None
            assert quoted_author is None
            assert quoted_at is None
            assert covered_by_email_id is None
            assert coverage_checked_at is None

            if kind == "quoted":
                assert quote_depth == 1
            else:
                assert quote_depth == 0

            if language is None:
                assert language_confidence is None
            else:
                assert language_confidence is not None
                assert 0 < language_confidence <= 1
            languages[language] += 1

        assert previous_end == len(clean_text)

    assert dict(languages) == {"en": 18, "fr": 1, None: 1}

    msg_003 = by_message["msg-003@example.test"]
    quoted = [segment for segment in msg_003 if segment[2] == "quoted"]
    assert len(quoted) == 1
    assert quoted[0][3:5] == (92, 169)
    assert clean_by_id["msg-003@example.test"][92:169].startswith(
        "> 12 March works for me"
    )
    tail = msg_003[-1]
    assert tail[2] == "new"
    assert tail[5] is None
    assert tail[4] - tail[3] == 13

    msg_006 = by_message["msg-006@example.test"]
    assert len(msg_006) == 1
    assert msg_006[0][5] == "fr"

    for message_id, message_segments in by_message.items():
        if message_id == "msg-006@example.test":
            continue
        for segment in message_segments:
            if segment[5] is not None:
                assert segment[5] == "en"

    return texts, segments


def _verify_attachments_stage(
    ctx: PipelineContext,
    conn: psycopg.Connection,
    events: list[dict],
    *,
    rerun: bool = False,
) -> list[tuple]:
    attachment_events = _stage_events(events, "attachments")
    starts = [event for event in attachment_events if event["phase"] == "start"]
    assert len(starts) == 1

    done = _done_event(events, "attachments")
    expected_processed = 0 if rerun else 1
    expected_needs_ocr = 0 if rerun else 1
    assert done["processed"] == expected_processed
    assert done["details"] == {
        "done": 0,
        "empty": 0,
        "needs_ocr": expected_needs_ocr,
        "unsupported": 0,
        "too_large": 0,
        "encrypted": 0,
        "failed": 0,
        "budget_exhausted": False,
    }

    expected_shas = {
        attachment.sha256
        for message in ctx.expected
        for attachment in message.attachments
    }
    assert len(expected_shas) == 1

    rows = db.query_all(
        conn,
        "SELECT blob_sha256, status, text, method, page_count, language, "
        "error, truncated, text_sha256, stage_version, created_at, updated_at "
        "FROM derived.attachment_text",
    )
    assert len(rows) == 1
    (
        blob_sha256,
        status,
        text,
        method,
        page_count,
        language,
        error,
        truncated,
        text_sha256,
        stage_version,
        _created_at,
        _updated_at,
    ) = rows[0]
    assert blob_sha256 in expected_shas
    assert status == "needs_ocr"
    assert text is None
    assert method is None
    assert page_count is None
    assert language is None
    assert text_sha256 is None
    assert truncated is False
    assert error == EXPECTED_ATTACHMENT_ERROR
    assert stage_version == EXPECTED_ATTACHMENT_STAGE_VERSION

    attachment_rows = db.query_all(
        conn,
        "SELECT sha256, storage_key FROM core.email_attachment "
        "WHERE disposition != 'inline'",
    )
    assert {row[0] for row in attachment_rows} == expected_shas
    for sha256, storage_key in attachment_rows:
        assert storage_key == f"blobs/{sha256[:2]}/{sha256}"

    return rows


def _verify_chunk_stage(
    ctx: PipelineContext,
    conn: psycopg.Connection,
    events: list[dict],
    *,
    rerun: bool = False,
) -> tuple[list[tuple], list[tuple]]:
    chunk_events = _stage_events(events, "chunk")
    starts = [event for event in chunk_events if event["phase"] == "start"]
    assert len(starts) == 1

    done = _done_event(events, "chunk")
    expected_processed = 0 if rerun else EXPECTED_MESSAGE_COUNT
    assert done["processed"] == expected_processed
    assert done["details"] == {
        "chunks_written": 0 if rerun else EXPECTED_CHUNK_COUNT,
        "chunks_unchanged": 0,
        "skipped_not_ready": 0 if rerun else 1,
        "failed": 0,
    }

    source_num = db.query_one(
        conn,
        "SELECT num FROM source_account WHERE id = %s::uuid",
        (ctx.source_id,),
    )[0]

    chunks = db.query_all(
        conn,
        "SELECT m.message_id, c.chunk_kind, c.seq, c.attachment_id, "
        "c.text_for_display, c.text_for_index, c.text_sha256, c.language, "
        "c.index_version, c.thread_id::text, m.thread_id::text, "
        "c.source_account_id::text, c.source_account_num, c.sent_at, "
        "m.occurred_at, c.sender_handle, c.recipient_handles, "
        "c.participant_handles, c.direction, c.has_attachment, "
        "c.is_trash_or_spam, c.tags, c.meta, c.created_at "
        "FROM search.chunk c "
        "JOIN core.email_message m ON m.id = c.email_id "
        "ORDER BY m.message_id, c.chunk_kind, c.seq",
    )
    assert len(chunks) == EXPECTED_CHUNK_COUNT

    expected_sent = {
        "msg-002@example.test",
        "msg-007@example.test",
        "msg-014@example.test",
    }
    expected_trash = {
        message.external_id
        for message in ctx.expected
        if any(tag.lower() in {"spam", "trash"} for tag in message.provider_tags)
    }
    expected_with_attachments = {
        message.external_id for message in ctx.expected if message.attachments
    }
    by_message = {message.external_id: message for message in ctx.expected}

    kinds: Counter = Counter()
    languages: Counter = Counter()
    index_versions: set[str] = set()
    chunked_messages: set[str] = set()
    quoted_messages: set[str] = set()

    for chunk in chunks:
        (
            message_id,
            chunk_kind,
            seq,
            attachment_id,
            text_for_display,
            text_for_index,
            text_sha256,
            language,
            index_version,
            chunk_thread_id,
            message_thread_id,
            source_account_id,
            source_account_num,
            sent_at,
            occurred_at,
            sender_handle,
            recipient_handles,
            participant_handles,
            direction,
            has_attachment,
            is_trash_or_spam,
            tags,
            meta,
            _created_at,
        ) = chunk
        message = by_message[message_id]
        kinds[chunk_kind] += 1
        languages[language] += 1
        index_versions.add(index_version)

        assert attachment_id is None
        assert seq == 0
        assert text_for_display
        assert text_for_display in text_for_index
        assert text_sha256 == hashlib.sha256(text_for_index.encode("utf-8")).hexdigest()
        assert chunk_thread_id == message_thread_id
        assert source_account_id == ctx.source_id
        assert source_account_num == source_num
        assert sent_at == occurred_at
        assert direction == ("sent" if message_id in expected_sent else "received")
        assert has_attachment is (message_id in expected_with_attachments)
        assert is_trash_or_spam is (message_id in expected_trash)
        assert set(tags) == {f"gmail:{tag}" for tag in message.provider_tags}
        assert meta == {}

        from_participants = sorted(
            (
                participant
                for participant in message.participants
                if participant.role == "from"
            ),
            key=lambda participant: participant.seq,
        )
        assert sender_handle == (from_participants[0].addr if from_participants else "")
        assert set(recipient_handles) == {
            participant.addr
            for participant in message.participants
            if participant.role in ("to", "cc", "bcc")
        }
        assert set(participant_handles) == {
            participant.addr for participant in message.participants
        }

        if chunk_kind == "email_body":
            assert text_for_index.startswith("Email |")
            chunked_messages.add(message_id)
        elif chunk_kind == "email_quote":
            assert text_for_index.startswith("Quoted history |")
            quoted_messages.add(message_id)
        else:  # pragma: no cover - the fixture has no attachment chunks
            raise AssertionError(f"unexpected chunk kind: {chunk_kind}")

    assert kinds == {
        "email_body": EXPECTED_BODY_CHUNK_COUNT,
        "email_quote": EXPECTED_QUOTE_CHUNK_COUNT,
    }
    assert chunked_messages == {message.external_id for message in ctx.expected}
    assert quoted_messages == {"msg-003@example.test"}
    assert dict(languages) == {"en": 18, "fr": 1}
    assert len(index_versions) == 1
    chunk_index_version = index_versions.pop()
    assert chunk_index_version.startswith("chunker/1+prefix/1+bge-m3/")

    msg_003_kinds = {chunk[1] for chunk in chunks if chunk[0] == "msg-003@example.test"}
    assert msg_003_kinds == {"email_body", "email_quote"}
    msg_003_body = next(
        chunk
        for chunk in chunks
        if chunk[0] == "msg-003@example.test" and chunk[1] == "email_body"
    )
    msg_003_quote = next(
        chunk
        for chunk in chunks
        if chunk[0] == "msg-003@example.test" and chunk[1] == "email_quote"
    )
    assert "> 12 March works for me" not in msg_003_body[4]
    assert "> 12 March works for me" in msg_003_quote[4]

    msg_008_body = next(
        chunk
        for chunk in chunks
        if chunk[0] == "msg-008@example.test" and chunk[1] == "email_body"
    )
    assert "attachments: q1-budget.pdf" in msg_008_body[5]

    msg_006_body = next(chunk for chunk in chunks if chunk[0] == "msg-006@example.test")
    assert msg_006_body[7] == "fr"

    text_digests = dict(
        db.query_all(
            conn,
            "SELECT m.message_id, t.segments_digest "
            "FROM derived.email_text t "
            "JOIN core.email_message m ON m.id = t.email_id",
        )
    )

    builds = db.query_all(
        conn,
        "SELECT m.message_id, b.chunk_kind, b.attachment_id, "
        "b.index_version, b.source_digest, b.built_at, b.chunk_count, "
        "b.status, b.error "
        "FROM search.chunk_build b "
        "JOIN core.email_message m ON m.id = b.email_id "
        "ORDER BY m.message_id, b.chunk_kind",
    )
    assert len(builds) == EXPECTED_CHUNK_BUILD_COUNT
    build_kinds: Counter = Counter()
    built_at_values: set = set()
    for build in builds:
        (
            message_id,
            chunk_kind,
            attachment_id,
            index_version,
            source_digest,
            built_at,
            chunk_count,
            status,
            error,
        ) = build
        build_kinds[chunk_kind] += 1
        built_at_values.add(built_at)
        assert attachment_id is None
        assert index_version == chunk_index_version
        assert source_digest == text_digests[message_id]
        assert chunk_count == 1
        assert status == "done"
        assert error is None

    assert build_kinds == {
        "email_body": EXPECTED_BODY_CHUNK_COUNT,
        "email_quote": EXPECTED_QUOTE_CHUNK_COUNT,
    }
    assert len(built_at_values) == 1

    return chunks, builds


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
    thread_ids = _verify_reconcile_stage(ctx, split_pg_conn, events)
    enrich_snapshot = _verify_enrich_stage(ctx, split_pg_conn, events)
    attachment_snapshot = _verify_attachments_stage(ctx, split_pg_conn, events)
    chunk_snapshot = _verify_chunk_stage(ctx, split_pg_conn, events)

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
    rerun_thread_ids = _verify_reconcile_stage(ctx, split_pg_conn, rerun_events)
    assert rerun_thread_ids == thread_ids
    rerun_enrich_snapshot = _verify_enrich_stage(
        ctx, split_pg_conn, rerun_events, rerun=True
    )
    assert rerun_enrich_snapshot == enrich_snapshot
    rerun_attachment_snapshot = _verify_attachments_stage(
        ctx, split_pg_conn, rerun_events, rerun=True
    )
    assert rerun_attachment_snapshot == attachment_snapshot
    rerun_chunk_snapshot = _verify_chunk_stage(
        ctx, split_pg_conn, rerun_events, rerun=True
    )
    assert rerun_chunk_snapshot == chunk_snapshot
