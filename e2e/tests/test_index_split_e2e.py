"""End-to-end test for index stage 1: splitting an mbox into messages.

Creates a dedicated Keycloak user, lets the backend provision its Rosalind
account just-in-time, imports the synthetic mbox through the CLI, runs the full
index pipeline, and verifies the split outputs: both the
``raw.source_record`` rows and the content-addressed objects in SeaweedFS.
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
class ExpectedMessage:
    raw: bytes
    sha256: str
    key: str
    message_id: str | None
    external_id: str


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
        expected.append(
            ExpectedMessage(
                raw=raw,
                sha256=digest,
                key=f"records/{digest[:2]}/{digest}",
                message_id=message_id,
                external_id=message_id or f"no-message-id:{digest}",
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


def _count(conn: psycopg.Connection, sql: str, params=None) -> int:
    return db.query_one(conn, sql, params)[0]


def test_cli_import_and_split_index(
    split_account,
    split_run_rosalind: Callable[[list[str]], subprocess.CompletedProcess[str]],
    split_pg_conn: psycopg.Connection,
    split_bucket: str,
    s3_client,
) -> None:
    expected = _expected_messages()
    assert len(expected) == EXPECTED_MESSAGE_COUNT
    fixture_bytes = FIXTURE.read_bytes()

    # --- The dedicated account does not exist until its first API call. -----
    assert (
        _count(
            split_pg_conn,
            "SELECT count(*) FROM account_identity WHERE issuer = %s AND subject = %s",
            (split_account.issuer, split_account.subject),
        )
        == 0
    )

    whoami = split_run_rosalind(["--json", "auth", "whoami"])
    assert whoami.returncode == 0, whoami.stdout + whoami.stderr
    profile = json.loads(whoami.stdout)
    account_id = profile["account_id"]
    assert profile["email"] == split_account.email

    identity = db.query_one(
        split_pg_conn,
        "SELECT account_id::text FROM account_identity "
        "WHERE issuer = %s AND subject = %s",
        (split_account.issuer, split_account.subject),
    )
    assert identity is not None
    assert identity[0] == account_id
    assert _count(split_pg_conn, "SELECT count(*) FROM account") == 1

    # --- Create the source and import the mbox through the CLI. -------------
    source = split_run_rosalind(
        ["--json", "source", "create", "google", "--name", "google"]
    )
    assert source.returncode == 0, source.stdout + source.stderr
    source_body = json.loads(source.stdout)
    assert source_body["name"] == "google"
    source_id = source_body["source_id"]

    imported = split_run_rosalind(
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
        split_pg_conn,
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
        split_pg_conn,
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

    listed = split_run_rosalind(["--json", "import", "list"])
    assert listed.returncode == 0, listed.stdout + listed.stderr
    imports = json.loads(listed.stdout)
    assert [item["import_id"] for item in imports] == [import_id]

    # --- Run the full index pipeline. ---------------------------------------
    indexed = split_run_rosalind(
        ["--json", "index", import_id, "--self-email", SELF_EMAIL]
    )
    assert indexed.returncode == 0, indexed.stdout + indexed.stderr
    events = _parse_events(indexed.stdout)
    assert events
    assert not any(event["phase"] == "error" for event in events)

    split_events = [event for event in events if event["stage"] == "split"]
    starts = [event for event in split_events if event["phase"] == "start"]
    progresses = [event for event in split_events if event["phase"] == "progress"]
    dones = [event for event in split_events if event["phase"] == "done"]
    assert len(starts) == 1
    assert len(progresses) == 1
    assert len(dones) == 1

    start = starts[0]
    assert start["total_files"] == 1
    assert start["total_bytes"] == len(fixture_bytes)

    progress = progresses[0]
    assert progress["file"] == FIXTURE.name
    assert progress["processed"] == EXPECTED_MESSAGE_COUNT
    assert progress["created"] == EXPECTED_MESSAGE_COUNT
    assert progress["reused"] == 0
    assert progress["failed"] == 0

    done = dones[0]
    expected_bytes = sum(len(message.raw) for message in expected)
    assert done["processed"] == EXPECTED_MESSAGE_COUNT
    assert done["created"] == EXPECTED_MESSAGE_COUNT
    assert done["reused"] == 0
    assert done["failed"] == 0
    assert done["processed_bytes"] == expected_bytes

    # The full pipeline continued past split into the derived stages.
    for stage in ("canonicalize", "reconcile", "enrich", "attachments", "chunk"):
        assert any(
            event["stage"] == stage and event["phase"] == "done" for event in events
        ), f"missing done event for stage {stage}"
    canonicalize = next(
        event
        for event in events
        if event["stage"] == "canonicalize" and event["phase"] == "done"
    )
    assert canonicalize["processed"] == EXPECTED_MESSAGE_COUNT
    assert canonicalize["created"] == EXPECTED_MESSAGE_COUNT
    assert canonicalize["failed"] == 0

    # --- One immutable raw record per message. ------------------------------
    records = db.query_all(
        split_pg_conn,
        "SELECT external_id, payload_sha256, payload_uri, resource_type, "
        "payload, import_id::text, source_account_id::text "
        "FROM raw.source_record WHERE import_id = %s::uuid",
        (import_id,),
    )
    assert len(records) == EXPECTED_MESSAGE_COUNT
    by_external = {record[0]: record for record in records}
    assert set(by_external) == {message.external_id for message in expected}
    assert len({record[1] for record in records}) == EXPECTED_MESSAGE_COUNT

    for message in expected:
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
        assert record_import_id == import_id
        assert record_source_id == source_id

    assert (
        _count(split_pg_conn, "SELECT count(*) FROM core.email_message")
        == EXPECTED_MESSAGE_COUNT
    )
    assert (
        _count(
            split_pg_conn,
            "SELECT processing_status FROM imports WHERE id = %s::uuid",
            (import_id,),
        )
        == "pending"
    )

    # --- One object per message, plus the untouched source archive. ---------
    listing = s3_client.list_objects_v2(Bucket=split_bucket, Prefix="records/")
    keys = {obj["Key"] for obj in listing.get("Contents", [])}
    assert keys == {message.key for message in expected}

    for message in expected:
        body = s3_client.get_object(Bucket=split_bucket, Key=message.key)["Body"].read()
        assert body == message.raw

        parsed = message_from_bytes(body)
        header = parsed.get("Message-ID")
        if message.message_id is None:
            assert header is None
        else:
            assert _normalize_message_id(str(header)) == message.message_id

    archive = s3_client.get_object(
        Bucket=split_bucket, Key=f"imports/{import_id}/{FIXTURE.name}"
    )["Body"].read()
    assert archive == fixture_bytes

    # --- Re-running the pipeline is idempotent. -----------------------------
    rerun = split_run_rosalind(
        ["--json", "index", import_id, "--self-email", SELF_EMAIL]
    )
    assert rerun.returncode == 0, rerun.stdout + rerun.stderr
    rerun_events = _parse_events(rerun.stdout)
    rerun_done = next(
        event
        for event in rerun_events
        if event["stage"] == "split" and event["phase"] == "done"
    )
    assert rerun_done["processed"] == EXPECTED_MESSAGE_COUNT
    assert rerun_done["created"] == 0
    assert rerun_done["reused"] == EXPECTED_MESSAGE_COUNT
    assert rerun_done["failed"] == 0
    rerun_canonicalize = next(
        event
        for event in rerun_events
        if event["stage"] == "canonicalize" and event["phase"] == "done"
    )
    assert rerun_canonicalize["created"] == 0
    assert rerun_canonicalize["reused"] == EXPECTED_MESSAGE_COUNT

    assert (
        _count(
            split_pg_conn,
            "SELECT count(*) FROM raw.source_record WHERE import_id = %s::uuid",
            (import_id,),
        )
        == EXPECTED_MESSAGE_COUNT
    )
    assert (
        _count(split_pg_conn, "SELECT count(*) FROM core.email_message")
        == EXPECTED_MESSAGE_COUNT
    )
    rerun_listing = s3_client.list_objects_v2(Bucket=split_bucket, Prefix="records/")
    assert {obj["Key"] for obj in rerun_listing.get("Contents", [])} == {
        message.key for message in expected
    }
