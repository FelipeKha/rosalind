from fastapi.testclient import TestClient

SHA256 = "a" * 64


def _create_import(client: TestClient) -> str:
    response = client.post("/imports/google/takeout")
    assert response.status_code == 201
    body = response.json()
    assert body["status"] == "uploading"
    assert body["storage_prefix"] == f"imports/{body['import_id']}"
    return body["import_id"]


def test_import_lifecycle(api_client: TestClient) -> None:
    import_id = _create_import(api_client)

    response = api_client.post(
        f"/imports/{import_id}/complete",
        json={
            "files": [
                {
                    "path": "Contacts/contacts.json",
                    "sha256": SHA256,
                    "size": 10,
                    "format": "json",
                }
            ]
        },
    )
    assert response.status_code == 200
    result = response.json()
    assert result["status"] == "completed"
    assert result["file_count"] == 1
    assert result["total_size"] == 10
    assert result["import_hash"] is not None

    detail = api_client.get(f"/imports/{import_id}")
    assert detail.status_code == 200
    files = detail.json()["files"]
    assert len(files) == 1
    assert files[0]["storage_key"] == f"imports/{import_id}/Contacts/contacts.json"


def test_complete_import_rejects_invalid_manifest(api_client: TestClient) -> None:
    import_id = _create_import(api_client)
    response = api_client.post(
        f"/imports/{import_id}/complete",
        json={"files": [{"path": "a.json", "sha256": "not-hex", "size": 1}]},
    )
    assert response.status_code == 422


def test_complete_import_unknown_id(api_client: TestClient) -> None:
    response = api_client.post(
        "/imports/00000000-0000-0000-0000-000000000000/complete",
        json={"files": [{"path": "a.json", "sha256": SHA256, "size": 1}]},
    )
    assert response.status_code == 404


def test_complete_import_twice_conflicts(api_client: TestClient) -> None:
    import_id = _create_import(api_client)
    payload = {"files": [{"path": "a.json", "sha256": SHA256, "size": 1}]}
    assert (
        api_client.post(f"/imports/{import_id}/complete", json=payload).status_code
        == 200
    )
    assert (
        api_client.post(f"/imports/{import_id}/complete", json=payload).status_code
        == 409
    )


def test_get_import_unknown_id(api_client: TestClient) -> None:
    response = api_client.get("/imports/00000000-0000-0000-0000-000000000000")
    assert response.status_code == 404
