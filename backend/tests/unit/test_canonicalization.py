import uuid
from datetime import UTC, datetime

import pytest

from rosalind.application.canonicalization.person import (
    CanonicalizationService,
    _date_sort_key,
    _name_sort_key,
    _select_primary,
)
from rosalind.application.errors import EntityResolutionConflictError
from rosalind.domain.person import DateObservation, NameObservation, PersonObservation
from rosalind.domain.source import SourceAccount, SourceRecord, SourceRef


def _id() -> uuid.UUID:
    return uuid.uuid4()


def test_select_primary_prefers_source_primary() -> None:
    a, b = _id(), _id()
    assert _select_primary([(a, False, "a"), (b, True, "b")]) == b


def test_select_primary_falls_back_to_sort_order() -> None:
    a, b = _id(), _id()
    assert _select_primary([(a, None, "zeta"), (b, None, "alpha")]) == b


def test_select_primary_empty_is_none() -> None:
    assert _select_primary([]) is None


def test_name_sort_key_prefers_display_name() -> None:
    obs = NameObservation("Alex", "A", "Morgan", None, None, None, "$.names[0]")
    assert _name_sort_key(obs) == "Alex"


def test_date_sort_key_pads_components() -> None:
    obs = DateObservation("birthday", 1988, 4, 17, None, None, None, "$.birthdays[0]")
    assert _date_sort_key(obs) == "1988-04-17"


def test_canonicalize_raises_on_identity_conflict() -> None:
    class FakeRepo:
        def find_person_ids(self, *, source_account_id, refs):
            return {_id(), _id()}

    class FakeUow:
        def __init__(self, repo) -> None:
            self.person_canonical = repo

    service = CanonicalizationService()
    uow = FakeUow(FakeRepo())
    account = SourceAccount(_id(), "google", None, None, None, datetime.now(UTC))
    record = SourceRecord(_id(), account.id, "person", "people/x", {}, "sha256")
    observation = PersonObservation(
        source_identities=(SourceRef("PROFILE", "1"),),
        names=(),
        emails=(),
        dates=(),
        genders=(),
        locales=(),
    )

    with pytest.raises(EntityResolutionConflictError):
        service.canonicalize(uow, account, record, observation)  # type: ignore[arg-type]
