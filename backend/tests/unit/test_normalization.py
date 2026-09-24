from rosalind.application.canonicalization.email import normalize_email


def test_normalize_email_lowercases_and_strips() -> None:
    assert normalize_email("  Alex.Morgan@Example.COM ") == "alex.morgan@example.com"


def test_normalize_email_is_idempotent() -> None:
    assert normalize_email(normalize_email("Alex@Example.COM")) == "alex@example.com"


def test_normalize_email_lowercases_local_part() -> None:
    assert normalize_email("ALEX@example.com") == "alex@example.com"


def test_normalize_email_preserves_domain() -> None:
    assert normalize_email("alex@EXAMPLE.COM") == "alex@example.com"
