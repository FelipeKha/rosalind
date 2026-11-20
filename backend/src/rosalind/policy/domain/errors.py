"""Domain errors for the policy service."""

from __future__ import annotations


class PolicyError(Exception):
    """Base class for policy service failures."""


class ParserError(PolicyError):
    """The prompt parser could not produce a valid extraction."""


class ModelNotAllowedError(PolicyError):
    """The requested model is unknown, disabled, or not local."""


class DraftNotFoundError(PolicyError):
    """The draft does not exist or is not owned by the account."""


class PolicyNotFoundError(PolicyError):
    """The policy does not exist or is not owned by the account."""


class ConstraintNotReadyError(PolicyError):
    """A constraint was confirmed before it was ready."""


class UnsupportedConstraintError(PolicyError):
    """A constraint cannot be represented by the Phase 1 policy model."""
