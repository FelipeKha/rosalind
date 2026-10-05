import json
import uuid

from fastapi.testclient import TestClient

from rosalind.adapters import composition

MBOX = (
    b"From alice@example.com Mon Sep 28 12:00:00 2026\n"
    b"Message-ID: <a@example.com>\n"
    b"Subject: hello\n"
    b"\n"
    b"body one\n"
    b"\n"
    b"From bob@example.com Mon Sep 28 12:01:00 2026\n"
    b"Message-ID: <b@example.com>\n"
    b"Subject: two\n"
    b"\n"
    b"body two\n"
    b"\n"
)


def _create_import(api_client: TestClient, *, complete: bool = True) -> str:
    name = f"google-{uuid.uuid4().hex[:8]}"
    response = api_client.post("/sources", json={"provider": "google", "name": name})
    assert response.status_code == 201
    response = api_client.post(
        "/imports", json={"source_name": name, "type": "takeout"}
    )
    assert response.status_code == 201
    import_id = response.json()["import_id"]
    if complete:
        response = api_client.post(
            f"/imports/{import_id}/complete",
            json={
                "files": [
                    {
                        "path": "Mail/All Mail.mbox",
                        "sha256": "a" * 64,
                        "size": len(MBOX),
                        "format": "mbox",
                    }
                ]
            },
        )
        assert response.status_code == 200
    return import_id


def _fake_storage(monkeypatch, existing: set[str] | None = None) -> dict[str, bytes]:
    puts: dict[str, bytes] = {}
    existing = existing or set()

    def download(key: str, dest: object) -> None:
        dest.write(MBOX)  # type: ignore[attr-defined]

    def put(key: str, data: bytes) -> None:
        puts[key] = data

    def exists(key: str) -> bool:
        return key in existing

    monkeypatch.setattr(composition.object_storage, "download", download)
    monkeypatch.setattr(composition.object_storage, "put", put)
    monkeypatch.setattr(composition.object_storage, "exists", exists)
    return puts


def _run(api_client: TestClient, import_id: str) -> list[dict]:
    with api_client.stream("POST", f"/imports/{import_id}/pipeline") as response:
        assert response.status_code == 200
        return [json.loads(line) for line in response.iter_lines() if line]


def test_pipeline_splits_mbox(api_client: TestClient, monkeypatch) -> None:
    import_id = _create_import(api_client)
    puts = _fake_storage(monkeypatch)

    events = _run(api_client, import_id)

    assert events[0]["stage"] == "starting"
    done = next(event for event in events if event["stage"] == "done")
    assert done["processed"] == 2
    assert done["created"] == 2
    assert done["failed"] == 0
    assert len(puts) == 2
    # Canonicalize runs after split; without a self person it reports an error.
    assert events[-1]["stage"] == "error"


def test_pipeline_is_idempotent(api_client: TestClient, monkeypatch) -> None:
    import_id = _create_import(api_client)
    _fake_storage(monkeypatch)

    first = _run(api_client, import_id)
    first_done = next(event for event in first if event["stage"] == "done")
    assert first_done["created"] == 2

    monkeypatch.setattr(
        composition.object_storage,
        "put",
        lambda key, data: (_ for _ in ()).throw(AssertionError("should not re-upload")),
    )
    monkeypatch.setattr(composition.object_storage, "exists", lambda key: True)

    second = _run(api_client, import_id)
    second_done = next(event for event in second if event["stage"] == "done")
    assert second_done["created"] == 0
    assert second_done["reused"] == 2


def test_pipeline_unknown_import_404(api_client: TestClient) -> None:
    response = api_client.post("/imports/00000000-0000-0000-0000-000000000000/pipeline")
    assert response.status_code == 404


def test_pipeline_incomplete_import_409(api_client: TestClient) -> None:
    import_id = _create_import(api_client, complete=False)
    response = api_client.post(f"/imports/{import_id}/pipeline")
    assert response.status_code == 409
