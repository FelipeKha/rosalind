import json

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
    response = api_client.post("/imports", json={"source_name": "none", "via": "file"})
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


def _run(
    api_client: TestClient,
    import_id: str,
    *,
    stage: str | None = None,
    self_email: str | None = None,
) -> list[dict]:
    path = f"/imports/{import_id}/index"
    if stage:
        path = f"{path}?stage={stage}"
    body = {"self_email": self_email} if self_email else None
    with api_client.stream("POST", path, json=body) as response:
        assert response.status_code == 200
        return [json.loads(line) for line in response.iter_lines() if line]


def test_index_splits_mbox(api_client: TestClient, monkeypatch) -> None:
    import_id = _create_import(api_client)
    puts = _fake_storage(monkeypatch)

    events = _run(api_client, import_id)

    assert events[0]["stage"] == "split"
    assert events[0]["phase"] == "start"
    done = next(
        event
        for event in events
        if event["stage"] == "split" and event["phase"] == "done"
    )
    assert done["processed"] == 2
    assert done["created"] == 2
    assert done["failed"] == 0
    assert len(puts) == 2
    # Canonicalize runs after split; without a self person it reports an error.
    assert events[-1]["stage"] == "canonicalize"
    assert events[-1]["phase"] == "error"


def test_index_is_idempotent(api_client: TestClient, monkeypatch) -> None:
    import_id = _create_import(api_client)
    _fake_storage(monkeypatch)

    first = _run(api_client, import_id)
    first_done = next(
        event
        for event in first
        if event["stage"] == "split" and event["phase"] == "done"
    )
    assert first_done["created"] == 2

    monkeypatch.setattr(
        composition.object_storage,
        "put",
        lambda key, data: (_ for _ in ()).throw(AssertionError("should not re-upload")),
    )
    monkeypatch.setattr(composition.object_storage, "exists", lambda key: True)

    second = _run(api_client, import_id)
    second_done = next(
        event
        for event in second
        if event["stage"] == "split" and event["phase"] == "done"
    )
    assert second_done["created"] == 0
    assert second_done["reused"] == 2


def test_index_with_self_email_canonicalizes(
    api_client: TestClient, monkeypatch
) -> None:
    import_id = _create_import(api_client)
    _fake_storage(monkeypatch)

    # First run splits the mbox; canonicalize then fails without a self identity.
    _run(api_client, import_id)

    events = _run(
        api_client,
        import_id,
        stage="canonicalize",
        self_email="alice@example.com",
    )

    # With a self email the canonicalize stage runs to completion instead of
    # erroring on a missing self person.
    assert not any(event["phase"] == "error" for event in events)
    done = next(
        event
        for event in events
        if event["stage"] == "canonicalize" and event["phase"] == "done"
    )
    assert done["processed"] == 2
    # The per-run email is never echoed back in the event stream.
    assert "alice@example.com" not in json.dumps(events)


def test_index_invalid_self_email_422(api_client: TestClient) -> None:
    import_id = _create_import(api_client)
    response = api_client.post(
        f"/imports/{import_id}/index", json={"self_email": "not-an-email"}
    )
    assert response.status_code == 422


def test_index_unknown_import_404(api_client: TestClient) -> None:
    response = api_client.post("/imports/00000000-0000-0000-0000-000000000000/index")
    assert response.status_code == 404


def test_index_incomplete_import_409(api_client: TestClient) -> None:
    import_id = _create_import(api_client, complete=False)
    response = api_client.post(f"/imports/{import_id}/index")
    assert response.status_code == 409
