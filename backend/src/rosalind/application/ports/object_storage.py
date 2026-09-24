"""Port (interface) for object storage.

Concrete implementations live in ``adapters.outbound`` (e.g. ``object_storage``).
Application services depend on this Protocol, never on a specific storage SDK.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol


class ObjectStorage(Protocol):
    """Bulk object storage used for raw provider files.

    ``bucket`` is exposed so the API can tell a client where to upload raw
    objects without the client or the application layer depending on storage
    configuration.
    """

    bucket: str

    def delete_objects(self, keys: Sequence[str]) -> None: ...
