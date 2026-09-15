import hashlib

from cli.ingestion import discovery


def test_discover_collects_files_and_metadata(tmp_path) -> None:
    (tmp_path / "Contacts").mkdir()
    (tmp_path / "Contacts" / "contacts.json").write_text('{"name": "John"}')
    (tmp_path / "archive_browser.html").write_text("<html></html>")
    (tmp_path / "noext").write_text("plain")

    files = discovery.discover(tmp_path)
    assert sorted(f.path for f in files) == [
        "Contacts/contacts.json",
        "archive_browser.html",
        "noext",
    ]

    by_path = {f.path: f for f in files}
    contacts = by_path["Contacts/contacts.json"]
    assert contacts.format == "json"
    assert contacts.size == len('{"name": "John"}')
    assert contacts.modified_at is not None
    assert contacts.sha256 == hashlib.sha256(b'{"name": "John"}').hexdigest()

    assert by_path["archive_browser.html"].format == "html"
    assert by_path["noext"].format is None


def test_discover_uses_posix_relative_paths(tmp_path) -> None:
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "file.txt").write_text("x")

    files = discovery.discover(tmp_path)
    assert [f.path for f in files] == ["sub/file.txt"]


def test_discover_skips_symlinks(tmp_path) -> None:
    (tmp_path / "real.txt").write_text("real")
    (tmp_path / "link.txt").symlink_to(tmp_path / "real.txt")

    files = discovery.discover(tmp_path)
    assert [f.path for f in files] == ["real.txt"]


def test_sha256_file_matches_hashlib(tmp_path) -> None:
    path = tmp_path / "f.bin"
    path.write_bytes(b"hello world")

    assert discovery.sha256_file(path) == hashlib.sha256(b"hello world").hexdigest()
