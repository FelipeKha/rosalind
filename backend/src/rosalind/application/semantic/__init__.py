"""Confidentiality (semantic) enforcement application layer.

Pure, framework-free values the online path carries: the semantic set that
applies to an agent and the treatment for each protected statement. Concrete
loaders, verifiers and overlay repositories live in adapters.

This package must not import SQLAlchemy, FastAPI, provider SDKs, or settings.
"""

from rosalind.application.semantic.models import (
    SemanticScope,
    SemanticStatement,
    Treatment,
)

__all__ = ["SemanticScope", "SemanticStatement", "Treatment"]
