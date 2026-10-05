from rosalind.adapters.outbound.enrichment.attachments import extract_blob
from rosalind.domain.email import AttachmentStatus


def test_extracts_plain_text() -> None:
    result = extract_blob(
        blob_sha256="a" * 64,
        data=b"hello world",
        detected_mime="text/plain",
        declared_mime=None,
        filename="note.txt",
        max_output_chars=1000,
    )
    assert result.status is AttachmentStatus.DONE
    assert result.text == "hello world"
    assert result.method == "text"


def test_strips_nul_from_text() -> None:
    result = extract_blob(
        blob_sha256="a" * 64,
        data=b"a\x00b\x01c",
        detected_mime="text/plain",
        declared_mime=None,
        filename=None,
        max_output_chars=1000,
    )
    assert result.status is AttachmentStatus.DONE
    assert result.text == "abc"


def test_unsupported_when_no_extractable_type() -> None:
    result = extract_blob(
        blob_sha256="a" * 64,
        data=b"\x00\x01\x02",
        detected_mime="application/octet-stream",
        declared_mime=None,
        filename="blob.bin",
        max_output_chars=1000,
    )
    assert result.status is AttachmentStatus.UNSUPPORTED


def test_legacy_doc_is_unsupported() -> None:
    result = extract_blob(
        blob_sha256="a" * 64,
        data=b"x",
        detected_mime=None,
        declared_mime="application/msword",
        filename="old.doc",
        max_output_chars=1000,
    )
    assert result.status is AttachmentStatus.UNSUPPORTED


def test_corrupt_pdf_never_raises() -> None:
    result = extract_blob(
        blob_sha256="a" * 64,
        data=b"this is not a pdf",
        detected_mime="application/pdf",
        declared_mime=None,
        filename="bad.pdf",
        max_output_chars=1000,
    )
    assert result.status in (
        AttachmentStatus.FAILED,
        AttachmentStatus.EMPTY,
        AttachmentStatus.ENCRYPTED,
    )


def test_empty_text_is_empty_status() -> None:
    result = extract_blob(
        blob_sha256="a" * 64,
        data=b"   \n  ",
        detected_mime="text/plain",
        declared_mime=None,
        filename=None,
        max_output_chars=1000,
    )
    assert result.status is AttachmentStatus.EMPTY


def test_output_is_truncated_with_flag() -> None:
    result = extract_blob(
        blob_sha256="a" * 64,
        data=b"line one\nline two\nline three",
        detected_mime="text/plain",
        declared_mime=None,
        filename=None,
        max_output_chars=12,
    )
    assert result.truncated is True
    assert len(result.text or "") <= 12
