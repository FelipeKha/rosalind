"""Domain errors raised during import lifecycle handling."""


class IngestionError(Exception):
    """Base class for import lifecycle errors."""


class ImportNotFoundError(IngestionError):
    """Raised when an import does not exist."""


class InvalidImportStateError(IngestionError):
    """Raised when an import is in an unexpected state."""


class InvalidManifestError(IngestionError):
    """Raised when a completion manifest is malformed."""


class InvalidPayloadError(IngestionError):
    """Raised when a provider payload cannot be mapped to a source record."""


class EntityResolutionConflictError(IngestionError):
    """Raised when source identities resolve to more than one canonical person."""
