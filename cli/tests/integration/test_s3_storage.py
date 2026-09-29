import boto3
import pytest
from botocore.config import Config
from testcontainers.core.container import DockerContainer
from testcontainers.core.wait_strategies import LogMessageWaitStrategy

from cli.storage.s3 import S3ObjectStorage

ACCESS_KEY = "rosalind"
SECRET_KEY = "rosalind"
BUCKET = "rosalind"


@pytest.fixture(scope="module")
def s3_endpoint():
    try:
        container = (
            DockerContainer("chrislusf/seaweedfs:latest")
            .with_command("server -dir=/data -s3")
            .with_env("AWS_ACCESS_KEY_ID", ACCESS_KEY)
            .with_env("AWS_SECRET_ACCESS_KEY", SECRET_KEY)
            .with_exposed_ports(8333)
        )
        container.waiting_for(LogMessageWaitStrategy("Start Seaweed S3 API Server"))
        container.start()
    except Exception as exc:  # noqa: BLE001 - skip if Docker is unavailable
        pytest.skip(f"Docker unavailable: {exc}")
        return ""

    try:
        host = container.get_container_host_ip()
        port = container.get_exposed_port(8333)
        yield f"http://{host}:{port}"
    finally:
        container.stop()


def _client(endpoint: str):
    return boto3.client(
        "s3",
        endpoint_url=endpoint,
        aws_access_key_id=ACCESS_KEY,
        aws_secret_access_key=SECRET_KEY,
        region_name="us-east-1",
        config=Config(retries={"max_attempts": 5, "mode": "standard"}),
    )


def test_upload_file_stores_object(s3_endpoint: str, tmp_path) -> None:
    client = _client(s3_endpoint)

    local = tmp_path / "data.bin"
    local.write_bytes(b"hello seaweed")

    storage = S3ObjectStorage(client=client)
    storage.upload_file(local, BUCKET, "imports/imp-1/data.bin")

    obj = client.get_object(Bucket=BUCKET, Key="imports/imp-1/data.bin")
    assert obj["Body"].read() == b"hello seaweed"
