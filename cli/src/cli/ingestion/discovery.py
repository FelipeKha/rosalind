"""Local file discovery, metadata collection, and hashing."""

import hashlib
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

CHUNK_SIZE = 1024 * 1024


@dataclass(frozen=True)
class FileInfo:
    path: str
    local_path: Path
    format: str | None
    size: int
    modified_at: datetime | None
    sha256: str


def discover(root: Path) -> list[FileInfo]:
    files: list[FileInfo] = []
    for entry in sorted(root.rglob("*")):
        if entry.is_symlink() or not entry.is_file():
            continue
        relative = entry.relative_to(root).as_posix()
        files.append(
            FileInfo(
                path=relative,
                local_path=entry,
                format=_format_of(entry),
                size=entry.stat().st_size,
                modified_at=_modified_at(entry),
                sha256=sha256_file(entry),
            )
        )
    return files


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(CHUNK_SIZE), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _format_of(path: Path) -> str | None:
    if not path.suffix:
        return None
    return path.suffix.lstrip(".").lower()


def _modified_at(path: Path) -> datetime | None:
    try:
        stat = path.stat()
    except OSError:
        return None
    return datetime.fromtimestamp(stat.st_mtime, tz=UTC)
