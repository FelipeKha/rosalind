import os

DEFAULT_API_URL = "http://localhost:8000"
DEFAULT_S3_ENDPOINT = "http://localhost:8333"
DEFAULT_S3_BUCKET = "rosalind"
DEFAULT_S3_REGION = "us-east-1"
DEFAULT_S3_ACCESS_KEY = "rosalind"
DEFAULT_S3_SECRET_KEY = "rosalind"  # nosec B105 - local dev default matching docker-compose.


def api_url() -> str:
    return os.environ.get("ROSALIND_API_URL", DEFAULT_API_URL)


def s3_endpoint() -> str:
    return os.environ.get("ROSALIND_S3_ENDPOINT", DEFAULT_S3_ENDPOINT)


def s3_access_key() -> str:
    return os.environ.get("ROSALIND_S3_ACCESS_KEY", DEFAULT_S3_ACCESS_KEY)


def s3_secret_key() -> str:
    return os.environ.get("ROSALIND_S3_SECRET_KEY", DEFAULT_S3_SECRET_KEY)


def s3_bucket() -> str:
    return os.environ.get("ROSALIND_S3_BUCKET", DEFAULT_S3_BUCKET)


def s3_region() -> str:
    return os.environ.get("ROSALIND_S3_REGION", DEFAULT_S3_REGION)
