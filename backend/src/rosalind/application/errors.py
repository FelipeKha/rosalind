"""Application and domain errors.

Colocated in the application layer so adapters can raise and catch them without
the application depending on adapter internals.
"""


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


class AuthError(Exception):
    """Base class for authentication errors."""


class InvalidStateError(AuthError):
    """Raised when an OAuth state is unknown or expired."""


class TokenNotFoundError(AuthError):
    """Raised when no credentials are stored for a provider account."""


class SourceNotFoundError(AuthError):
    """Raised when a source account does not exist by id or name."""


class ProviderError(AuthError):
    """Raised when the provider rejects a token exchange or API request."""
