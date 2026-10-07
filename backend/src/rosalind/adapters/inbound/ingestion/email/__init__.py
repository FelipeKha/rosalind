"""Email parse adapter."""

from rosalind.adapters.inbound.ingestion.email.parser import (
    PARSER_VERSION,
    parse_email,
)

__all__ = ["PARSER_VERSION", "parse_email"]
