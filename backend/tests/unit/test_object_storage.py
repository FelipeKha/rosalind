from rosalind import object_storage


class _FakeS3:
    def __init__(self) -> None:
        self.calls: list[tuple[str, list[str]]] = []

    def delete_objects(
        self, Bucket: str, Delete: dict[str, list[dict[str, str]]]
    ) -> None:
        keys = [obj["Key"] for obj in Delete["Objects"]]
        self.calls.append((Bucket, keys))


def _stub_client(monkeypatch) -> _FakeS3:
    fake = _FakeS3()
    monkeypatch.setattr(object_storage, "_build_client", lambda: fake)
    monkeypatch.setattr(object_storage, "_client", None)
    return fake


def test_delete_objects_batches(monkeypatch) -> None:
    fake = _stub_client(monkeypatch)
    keys = [f"key-{i}" for i in range(2500)]

    object_storage.delete_objects("bucket", keys)

    assert len(fake.calls) == 3
    flattened = [key for _, batch in fake.calls for key in batch]
    assert flattened == keys


def test_delete_objects_skips_empty_keys(monkeypatch) -> None:
    fake = _stub_client(monkeypatch)

    object_storage.delete_objects("bucket", ["", "a", "", "b"])

    assert fake.calls == [("bucket", ["a", "b"])]


def test_delete_objects_no_keys_is_noop(monkeypatch) -> None:
    fake = _stub_client(monkeypatch)

    object_storage.delete_objects("bucket", [])

    assert fake.calls == []
