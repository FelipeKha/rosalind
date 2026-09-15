"""Storage abstraction shared by ingestion components."""

from pathlib import Path
from typing import Protocol


class ObjectStorage(Protocol):
    def upload_file(self, local_path: Path, bucket: str, object_key: str) -> None:
        """Upload a local file to object storage at the given key."""
        ...
