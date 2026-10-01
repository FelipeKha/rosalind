from rosalind.application.canonicalization.email import normalize_email
from rosalind.application.canonicalization.name import normalize_name
from rosalind.application.canonicalization.phone import normalize_phone


def test_normalize_email_lowercases_and_strips() -> None:
    assert normalize_email("  Alex.Morgan@Example.COM ") == "alex.morgan@example.com"


def test_normalize_email_is_idempotent() -> None:
    assert normalize_email(normalize_email("Alex@Example.COM")) == "alex@example.com"


def test_normalize_email_lowercases_local_part() -> None:
    assert normalize_email("ALEX@example.com") == "alex@example.com"


def test_normalize_email_preserves_domain() -> None:
    assert normalize_email("alex@EXAMPLE.COM") == "alex@example.com"


def test_normalize_name_lowercases_and_strips() -> None:
    assert normalize_name("  Jane Smith ") == "jane smith"


def test_normalize_phone_keeps_leading_plus_and_digits() -> None:
    assert normalize_phone("+1 (415) 555-2671") == "+14155552671"


def test_normalize_phone_strips_formatting() -> None:
    assert normalize_phone("(415) 555-2671") == "4155552671"
