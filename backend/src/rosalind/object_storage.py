"""S3-compatible object storage client for the backend.

The CLI owns the upload data plane; the backend owns import deletion and
therefore needs to remove raw objects from object storage when an import is
hard-deleted.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import TYPE_CHECKING, cast

import boto3
from botocore.config import Config

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


def delete_objects(bucket: str, keys: Sequence[str]) -> None:
    """Delete the given object keys from the bucket in batches."""
    global _client

    keys = [key for key in keys if key]
    if not keys:
        return

    if _client is None:
        _client = _build_client()

    for start in range(0, len(keys), _DELETE_BATCH_SIZE):
        batch = keys[start : start + _DELETE_BATCH_SIZE]
        _client.delete_objects(
            Bucket=bucket,
            Delete={"Objects": [{"Key": key} for key in batch]},
        )
