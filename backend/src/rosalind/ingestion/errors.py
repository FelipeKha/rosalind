"""Domain errors raised during import lifecycle handling."""


class IngestionError(Exception):
    """Base class for import lifecycle errors."""


class ImportNotFoundError(IngestionError):
    """Raised when an import does not exist."""


class InvalidImportStateError(IngestionError):
    """Raised when an import is in an unexpected state."""


class InvalidManifestError(IngestionError):
    """Raised when a completion manifest is malformed."""
