"""Port (interface) for object storage.

Concrete implementations live in ``adapters.outbound`` (e.g. ``object_storage``).
Application services depend on this Protocol, never on a specific storage SDK.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import BinaryIO, Protocol


class ObjectStorage(Protocol):
    """Bulk object storage used for raw provider files and split records.

    ``bucket`` is exposed so the API can tell a client where to upload raw
    objects without the client or the application layer depending on storage
    configuration.
    """

    bucket: str

    def delete_objects(self, keys: Sequence[str]) -> None: ...

    def download(self, key: str, dest: BinaryIO) -> None:
        """Stream the object at ``key`` into the open ``dest`` file object."""

    def put(self, key: str, data: bytes) -> None:
        """Store ``data`` at ``key`` atomically.

        The write is content-addressed by the caller, so a re-put of the same
        key is a byte-identical no-op and readers never observe a partial object.
        """

    def exists(self, key: str) -> bool:
        """Return whether an object exists at ``key``."""
