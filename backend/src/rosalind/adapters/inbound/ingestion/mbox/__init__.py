"""mbox record-split adapter."""

from rosalind.adapters.inbound.ingestion.mbox.mbox import (
    SplitMessage,
    iter_messages,
)

__all__ = ["SplitMessage", "iter_messages"]
