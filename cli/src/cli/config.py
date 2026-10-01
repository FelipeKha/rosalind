import os

DEFAULT_API_URL = "http://localhost:8000"
DEFAULT_S3_ENDPOINT = "http://localhost:8333"
DEFAULT_S3_BUCKET = "rosalind"
DEFAULT_S3_REGION = "us-east-1"
DEFAULT_S3_ACCESS_KEY = "rosalind"
DEFAULT_S3_SECRET_KEY = "rosalind"  # nosec B105 - local dev default matching docker-compose.

DEFAULT_KEYCLOAK_URL = "http://localhost:8080"
DEFAULT_KEYCLOAK_REALM = "rosalind"
DEFAULT_KEYCLOAK_CLIENT_ID = "rosalind-cli"


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


def keycloak_url() -> str:
    return os.environ.get("ROSALIND_KEYCLOAK_URL", DEFAULT_KEYCLOAK_URL)


def keycloak_realm() -> str:
    return os.environ.get("ROSALIND_KEYCLOAK_REALM", DEFAULT_KEYCLOAK_REALM)


def keycloak_client_id() -> str:
    return os.environ.get("ROSALIND_KEYCLOAK_CLIENT_ID", DEFAULT_KEYCLOAK_CLIENT_ID)
