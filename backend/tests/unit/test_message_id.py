from rosalind.domain.email import normalize_message_id, parse_message_ids


def test_normalize_message_id_strips_angle_brackets() -> None:
    assert (
        normalize_message_id("<CAF7x9=roof-2291@mail.gmail.com>")
        == "CAF7x9=roof-2291@mail.gmail.com"
    )


def test_normalize_message_id_strips_whitespace() -> None:
    assert normalize_message_id("  <a@example.com>  ") == "a@example.com"


def test_normalize_message_id_leaves_bare_ids_untouched() -> None:
    assert normalize_message_id("a@example.com") == "a@example.com"


def test_normalize_message_id_is_idempotent() -> None:
    value = "<CAF7x9=roof-2291@mail.gmail.com>"
    assert normalize_message_id(normalize_message_id(value)) == normalize_message_id(
        value
    )


def test_parse_message_ids_splits_references() -> None:
    assert parse_message_ids(
        "<orig-001@mail.gmail.com>  <orig-002@mail.gmail.com>"
    ) == (
        "orig-001@mail.gmail.com",
        "orig-002@mail.gmail.com",
    )


def test_parse_message_ids_empty() -> None:
    assert parse_message_ids("") == ()
