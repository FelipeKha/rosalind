"""End-to-end tests for the CLI `import google` command."""

import hashlib
import re
import subprocess
from collections.abc import Callable
from pathlib import Path

import httpx

IMPORT_ID_RE = re.compile(r"ID:\s+([0-9a-f-]{36})")


def _fixture_files(root: Path) -> dict[str, bytes]:
    files: dict[str, bytes] = {}
    for entry in sorted(root.rglob("*")):
        if entry.is_file():
            files[entry.relative_to(root).as_posix()] = entry.read_bytes()
    return files


def _import_id_from_stdout(stdout: str) -> str:
    match = IMPORT_ID_RE.search(stdout)
    assert match, f"import_id not found in CLI output: {stdout!r}"
    return match.group(1)


def _assert_import_completed(
    backend_base_url: str, import_id: str, expected_files: dict[str, bytes]
) -> None:
    response = httpx.get(f"{backend_base_url}/imports/{import_id}")
    assert response.status_code == 200
    body = response.json()

    assert body["status"] == "completed"
    assert body["file_count"] == len(expected_files)
    assert body["total_size"] == sum(len(data) for data in expected_files.values())
    assert body["import_hash"] is not None

    by_path = {f["path"]: f for f in body["files"]}
    for path, data in expected_files.items():
        entry = by_path[path]
        assert entry["sha256"] == hashlib.sha256(data).hexdigest()
        assert entry["storage_key"] == f"imports/{import_id}/{path}"


def _assert_objects_uploaded(
    s3_client, import_id: str, expected_files: dict[str, bytes]
) -> None:
    for path, data in expected_files.items():
        obj = s3_client.get_object(Bucket="rosalind", Key=f"imports/{import_id}/{path}")
        assert obj["Body"].read() == data


def test_import_google_end_to_end(
    takeout_fixture: Path,
    backend_base_url: str,
    s3_client,
    run_cli: Callable[[Path], subprocess.CompletedProcess[str]],
) -> None:
    expected_files = _fixture_files(takeout_fixture)

    result = run_cli(takeout_fixture)
    assert result.returncode == 0, result.stderr
    assert "Import completed" in result.stdout
    import_id = _import_id_from_stdout(result.stdout)

    _assert_import_completed(backend_base_url, import_id, expected_files)
    _assert_objects_uploaded(s3_client, import_id, expected_files)


def test_reimport_is_a_distinct_observation(
    takeout_fixture: Path,
    backend_base_url: str,
    s3_client,
    run_cli: Callable[[Path], subprocess.CompletedProcess[str]],
) -> None:
    expected_files = _fixture_files(takeout_fixture)

    first = run_cli(takeout_fixture)
    assert first.returncode == 0, first.stderr
    first_id = _import_id_from_stdout(first.stdout)

    second = run_cli(takeout_fixture)
    assert second.returncode == 0, second.stderr
    second_id = _import_id_from_stdout(second.stdout)

    assert first_id != second_id

    _assert_import_completed(backend_base_url, first_id, expected_files)
    _assert_import_completed(backend_base_url, second_id, expected_files)
    _assert_objects_uploaded(s3_client, first_id, expected_files)
    _assert_objects_uploaded(s3_client, second_id, expected_files)


def test_delete_import_end_to_end(
    takeout_fixture: Path,
    backend_base_url: str,
    s3_client,
    run_cli: Callable[[Path], subprocess.CompletedProcess[str]],
    run_rosalind: Callable[[list[str]], subprocess.CompletedProcess[str]],
) -> None:
    expected_files = _fixture_files(takeout_fixture)

    result = run_cli(takeout_fixture)
    assert result.returncode == 0, result.stderr
    import_id = _import_id_from_stdout(result.stdout)

    deleted = run_rosalind(["import", "delete", import_id, "--yes"])
    assert deleted.returncode == 0, deleted.stderr

    response = httpx.get(f"{backend_base_url}/imports/{import_id}")
    assert response.status_code == 404

    listing = s3_client.list_objects_v2(
        Bucket="rosalind", Prefix=f"imports/{import_id}/"
    )
    assert listing.get("KeyCount") == 0
