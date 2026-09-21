"""Domain errors raised during provider authentication."""


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
