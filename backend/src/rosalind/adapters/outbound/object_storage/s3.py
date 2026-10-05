"""S3-compatible object storage client for the backend.

The CLI owns the import upload data plane; the backend owns import deletion and
the email pipeline's record split, so it needs to remove raw objects, stream
archives back down, and write content-addressed split records.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import TYPE_CHECKING, BinaryIO, cast

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError

from rosalind import config

if TYPE_CHECKING:
    from mypy_boto3_s3.client import S3Client

_DELETE_BATCH_SIZE = 1000


def _build_client() -> S3Client:
    return cast(
        "S3Client",
        boto3.client(
            "s3",
            endpoint_url=config.settings.s3_endpoint,
            aws_access_key_id=config.settings.s3_access_key,
            aws_secret_access_key=config.settings.s3_secret_key,
            region_name=config.settings.s3_region,
            config=Config(retries={"max_attempts": 5, "mode": "standard"}),
        ),
    )


_client: S3Client | None = None


def _client_instance() -> S3Client:
    global _client

    if _client is None:
        _client = _build_client()
    return _client


class S3ObjectStorage:
    """``ObjectStorage`` implementation backed by S3-compatible storage."""

    def __init__(self, bucket: str | None = None) -> None:
        self.bucket = bucket if bucket is not None else config.settings.s3_bucket

    def delete_objects(self, keys: Sequence[str]) -> None:
        """Delete the given object keys from the bucket in batches."""
        keys = [key for key in keys if key]
        if not keys:
            return

        client = _client_instance()

        for start in range(0, len(keys), _DELETE_BATCH_SIZE):
            batch = keys[start : start + _DELETE_BATCH_SIZE]
            client.delete_objects(
                Bucket=self.bucket,
                Delete={"Objects": [{"Key": key} for key in batch]},
            )

    def download(self, key: str, dest: BinaryIO) -> None:
        """Stream the object at ``key`` into ``dest``."""
        _client_instance().download_fileobj(self.bucket, key, dest)

    def put(self, key: str, data: bytes) -> None:
        """Store ``data`` at ``key`` as a single atomic object."""
        _client_instance().put_object(Bucket=self.bucket, Key=key, Body=data)

    def exists(self, key: str) -> bool:
        """Return whether an object exists at ``key``."""
        try:
            _client_instance().head_object(Bucket=self.bucket, Key=key)
        except ClientError as exc:
            if exc.response.get("ResponseMetadata", {}).get("HTTPStatusCode") == 404:
                return False
            raise
        return True
