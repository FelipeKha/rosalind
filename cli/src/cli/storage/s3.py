"""S3-compatible object storage implementation backed by boto3."""

from pathlib import Path
from typing import cast

import boto3
from boto3.s3.transfer import TransferConfig
from botocore.config import Config
from mypy_boto3_s3.client import S3Client

from cli import config

MULTIPART_THRESHOLD = 64 * 1024 * 1024
MULTIPART_CHUNK_SIZE = 16 * 1024 * 1024


class S3ObjectStorage:
    def __init__(self, client: S3Client | None = None) -> None:
        self._client = client or self._build_client()

    @staticmethod
    def _build_client() -> S3Client:
        return cast(
            S3Client,
            boto3.client(
                "s3",
                endpoint_url=config.s3_endpoint(),
                aws_access_key_id=config.s3_access_key(),
                aws_secret_access_key=config.s3_secret_key(),
                region_name=config.s3_region(),
                config=Config(retries={"max_attempts": 5, "mode": "standard"}),
            ),
        )

    def upload_file(self, local_path: Path, bucket: str, object_key: str) -> None:
        self._client.upload_file(
            str(local_path),
            bucket,
            object_key,
            Config=TransferConfig(
                multipart_threshold=MULTIPART_THRESHOLD,
                multipart_chunksize=MULTIPART_CHUNK_SIZE,
            ),
        )
