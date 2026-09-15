import uuid

import pytest

from rosalind.ingestion import manifest
from rosalind.ingestion.errors import InvalidManifestError


def test_storage_key_uses_import_id_and_path() -> None:
    import_id = uuid.uuid4()
    assert manifest.storage_key(import_id, "Contacts/contacts.json") == (
        f"imports/{import_id}/Contacts/contacts.json"
    )


def test_storage_prefix() -> None:
    import_id = uuid.uuid4()
    assert manifest.storage_prefix(import_id) == f"imports/{import_id}"


@pytest.mark.parametrize(
    "path",
    [
        "Contacts/contacts.json",
        "Mail/mbox/All mail Including Spam and Trash.mbox",
        "archive_browser.html",
    ],
)
def test_validate_path_accepts_relative_paths(path: str) -> None:
    assert manifest.validate_path(path) == path


@pytest.mark.parametrize(
    "path",
    [
        "",
        "/absolute/path.json",
        "\\windows\\style.json",
        "../escape.json",
        "Contacts/../contacts.json",
        "Contacts//contacts.json",
        "Contacts/",
        ".",
        "..",
        "a\x00b",
    ],
)
def test_validate_path_rejects_invalid_paths(path: str) -> None:
    with pytest.raises(InvalidManifestError):
        manifest.validate_path(path)


def test_validate_sha256_accepts_valid_digest() -> None:
    digest = "a" * 64
    assert manifest.validate_sha256(digest) == digest


@pytest.mark.parametrize(
    "digest",
    ["a" * 63, "a" * 65, "A" * 64, "g" * 64, "", "not-a-hash"],
)
def test_validate_sha256_rejects_invalid_digests(digest: str) -> None:
    with pytest.raises(InvalidManifestError):
        manifest.validate_sha256(digest)


def test_compute_import_hash_is_order_independent() -> None:
    entries_a = [("b.json", "b" * 64), ("a.json", "a" * 64)]
    entries_b = [("a.json", "a" * 64), ("b.json", "b" * 64)]
    assert manifest.compute_import_hash(entries_a) == manifest.compute_import_hash(
        entries_b
    )


def test_compute_import_hash_is_deterministic() -> None:
    entries = [("Contacts/contacts.json", "c" * 64)]
    assert manifest.compute_import_hash(entries) == manifest.compute_import_hash(
        entries
    )


def test_compute_import_hash_differs_when_content_differs() -> None:
    assert manifest.compute_import_hash([("a.json", "a" * 64)]) != (
        manifest.compute_import_hash([("a.json", "b" * 64)])
    )


def test_compute_import_hash_empty_collection() -> None:
    assert manifest.compute_import_hash([]) == manifest.compute_import_hash([])
