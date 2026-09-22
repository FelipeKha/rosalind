"""Pure manifest logic: paths, storage keys, and import-level hashing."""

import hashlib
import re
import uuid
from dataclasses import dataclass
from datetime import datetime

from rosalind.adapters.inbound.ingestion.errors import InvalidManifestError

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


@dataclass(frozen=True)
class FileEntry:
    """A single file discovered in the provider export."""

    path: str
    sha256: str
    size: int
    format: str | None = None
    modified_at: datetime | None = None


def storage_prefix(import_id: uuid.UUID) -> str:
    return f"imports/{import_id}"


def storage_key(import_id: uuid.UUID, path: str) -> str:
    return f"{storage_prefix(import_id)}/{path}"


def validate_path(path: str) -> str:
    if not path:
        raise InvalidManifestError("file path must not be empty")
    if "\x00" in path:
        raise InvalidManifestError("file path contains a null byte")
    if path.startswith(("/", "\\")):
        raise InvalidManifestError(f"file path must be relative: {path!r}")
    if "\\" in path:
        raise InvalidManifestError(f"file path must use forward slashes: {path!r}")
    if any(part in ("", ".", "..") for part in path.split("/")):
        raise InvalidManifestError(f"file path contains invalid segments: {path!r}")
    return path


def validate_sha256(digest: str) -> str:
    if not _SHA256_RE.fullmatch(digest):
        raise InvalidManifestError(f"invalid sha256 digest: {digest!r}")
    return digest


def compute_import_hash(entries: list[tuple[str, str]]) -> str:
    """Deterministic hash over the sorted collection of (path, sha256)."""
    digest = hashlib.sha256()
    for path, sha256 in sorted(entries, key=lambda entry: entry[0]):
        digest.update(path.encode("utf-8"))
        digest.update(b"\x00")
        digest.update(sha256.encode("ascii"))
        digest.update(b"\x0a")
    return digest.hexdigest()
