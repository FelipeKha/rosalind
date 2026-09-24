"""Provider-independent source identity references.

Source concepts are deliberately separate from any single domain model (person,
email, calendar, ...): they describe *where an assertion came from*, and are
shared by every model that ingests provider data.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class SourceRef:
    """An external identity within a specific source account.

    Not globally unique: the same ``(source_type, external_id)`` may refer to
    different people across different source accounts. The canonical identity is
    ``(source_account_id, source_type, external_id)`` in ``core.source_identity``.
    """

    source_type: str
    external_id: str
