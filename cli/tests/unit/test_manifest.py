from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

from cli.ingestion import manifest
from cli.ingestion.discovery import FileInfo


def test_build_manifest_serializes_files() -> None:
    info = FileInfo(
        path="Contacts/contacts.json",
        local_path=Path("/tmp/Contacts/contacts.json"),
        format="json",
        size=2,
        modified_at=datetime(2026, 1, 1, tzinfo=UTC),
        sha256="a" * 64,
    )

    result = manifest.build_manifest([info])

    assert result == {
        "files": [
            {
                "path": "Contacts/contacts.json",
                "format": "json",
                "size": 2,
                "modified_at": "2026-01-01T00:00:00+00:00",
                "sha256": "a" * 64,
            }
        ]
    }


def test_build_manifest_handles_missing_metadata() -> None:
    info = FileInfo(
        path="noext",
        local_path=Path("/tmp/noext"),
        format=None,
        size=0,
        modified_at=None,
        sha256="b" * 64,
    )

    result = manifest.build_manifest([info])
    entry = cast(Any, result["files"])[0]
    assert entry["format"] is None
    assert entry["modified_at"] is None
