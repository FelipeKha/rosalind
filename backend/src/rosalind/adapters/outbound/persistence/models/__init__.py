"""SQLAlchemy persistence models.

Importing this package registers every model on ``Base.metadata`` so that
``create_all`` and Alembic autogenerate see the complete schema.
"""

from rosalind.adapters.outbound.persistence.models.base import Base, utcnow
from rosalind.adapters.outbound.persistence.models.imports import Import, ImportFile
from rosalind.adapters.outbound.persistence.models.person import (
    Person,
    PersonDate,
    PersonDateAssertion,
    PersonEmail,
    PersonEmailAssertion,
    PersonGender,
    PersonGenderAssertion,
    PersonLocale,
    PersonLocaleAssertion,
    PersonName,
    PersonNameAssertion,
    SourceAssertion,
    SourceIdentity,
)
from rosalind.adapters.outbound.persistence.models.source import (
    OAuthAuthRequest,
    OAuthCredential,
    SourceAccount,
    SourceRecord,
)

__all__ = [
    "Base",
    "Import",
    "ImportFile",
    "OAuthAuthRequest",
    "OAuthCredential",
    "Person",
    "PersonDate",
    "PersonDateAssertion",
    "PersonEmail",
    "PersonEmailAssertion",
    "PersonGender",
    "PersonGenderAssertion",
    "PersonLocale",
    "PersonLocaleAssertion",
    "PersonName",
    "PersonNameAssertion",
    "SourceAccount",
    "SourceAssertion",
    "SourceIdentity",
    "SourceRecord",
    "utcnow",
]
