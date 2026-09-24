from rosalind.adapters.outbound.object_storage import s3


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
    monkeypatch.setattr(s3, "_build_client", lambda: fake)
    monkeypatch.setattr(s3, "_client", None)
    return fake


def test_delete_objects_batches(monkeypatch) -> None:
    fake = _stub_client(monkeypatch)
    storage = s3.S3ObjectStorage(bucket="bucket")
    keys = [f"key-{i}" for i in range(2500)]

    storage.delete_objects(keys)

    assert len(fake.calls) == 3
    flattened = [key for _, batch in fake.calls for key in batch]
    assert flattened == keys


def test_delete_objects_skips_empty_keys(monkeypatch) -> None:
    fake = _stub_client(monkeypatch)
    storage = s3.S3ObjectStorage(bucket="bucket")

    storage.delete_objects(["", "a", "", "b"])

    assert fake.calls == [("bucket", ["a", "b"])]


def test_delete_objects_no_keys_is_noop(monkeypatch) -> None:
    fake = _stub_client(monkeypatch)
    storage = s3.S3ObjectStorage(bucket="bucket")

    storage.delete_objects([])

    assert fake.calls == []


def test_bucket_defaults_to_config(monkeypatch) -> None:
    monkeypatch.setattr(s3.config.settings, "s3_bucket", "from-config")

    assert s3.S3ObjectStorage().bucket == "from-config"
