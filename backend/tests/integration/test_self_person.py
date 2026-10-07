import pytest

from rosalind.adapters import composition
from rosalind.adapters.outbound.persistence import models
from rosalind.adapters.outbound.persistence.unit_of_work import SqlAlchemyUnitOfWork
from rosalind.application.errors import SelfPersonError
from tests._account import ensure_account


def _insert_person_with_email(db_session, email: str) -> models.Person:
    person = models.Person()
    db_session.add(person)
    db_session.flush()
    db_session.add(
        models.PersonEmail(
            person_id=person.id,
            email=email,
            email_normalized=email.lower(),
            is_primary=True,
            is_verified=False,
        )
    )
    db_session.commit()
    return person


def test_set_self_person_succeeds(db_session, uow: SqlAlchemyUnitOfWork) -> None:
    account_id = ensure_account(uow).id
    person = _insert_person_with_email(db_session, "me@example.com")

    account = composition.account_service.set_self_person(uow, account_id, person.id)

    assert account.self_person_id == person.id
    assert uow.email_canonical.self_handles(account_id) == {"me@example.com"}


def test_set_self_person_requires_email(db_session, uow: SqlAlchemyUnitOfWork) -> None:
    account_id = ensure_account(uow).id
    person = models.Person()
    db_session.add(person)
    db_session.commit()

    with pytest.raises(SelfPersonError):
        composition.account_service.set_self_person(uow, account_id, person.id)
