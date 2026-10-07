from rosalind.adapters.inbound.ingestion.mbox import iter_messages

MBOX_TWO = (
    "From alice@example.com Mon Sep 28 12:00:00 2026\n"
    "Message-ID: <a@example.com>\n"
    "From: alice@example.com\n"
    "To: bob@example.com\n"
    "Subject: hello\n"
    "\n"
    "Body of the first message.\n"
    "\n"
    "From bob@example.com Mon Sep 28 12:01:00 2026\n"
    "Message-ID: <b@example.com>\n"
    "From: bob@example.com\n"
    "To: alice@example.com\n"
    "Subject: re: hello\n"
    "\n"
    "Body of the second message.\n"
    "\n"
)


def _write(path, content: str) -> None:
    path.write_bytes(content.encode())


def test_iter_messages_splits_into_messages(tmp_path) -> None:
    path = tmp_path / "mail.mbox"
    _write(path, MBOX_TWO)

    messages = list(iter_messages(path))

    assert len(messages) == 2
    assert messages[0].message_id == "a@example.com"
    assert b"Body of the first message." in messages[0].raw
    assert messages[1].message_id == "b@example.com"
    assert b"Body of the second message." in messages[1].raw


def test_iter_messages_preserves_from_quoted_lines(tmp_path) -> None:
    content = (
        "From alice@example.com Mon Sep 28 12:00:00 2026\n"
        "Message-ID: <a@example.com>\n"
        "Subject: hello\n"
        "\n"
        "line one\n"
        ">From quoted\n"
        "\n"
    )
    path = tmp_path / "mail.mbox"
    _write(path, content)

    (message,) = list(iter_messages(path))

    assert b">From quoted" in message.raw


def test_iter_messages_missing_message_id_is_none(tmp_path) -> None:
    content = (
        "From alice@example.com Mon Sep 28 12:00:00 2026\n"
        "Subject: no message id\n"
        "\n"
        "body\n"
        "\n"
    )
    path = tmp_path / "mail.mbox"
    _write(path, content)

    (message,) = list(iter_messages(path))

    assert message.message_id is None


def test_iter_messages_empty_archive_yields_nothing(tmp_path) -> None:
    path = tmp_path / "empty.mbox"
    _write(path, "")

    assert list(iter_messages(path)) == []
