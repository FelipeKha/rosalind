"""Shared fixtures standing up the full import stack for e2e tests.

The stack under test is:

    CLI (subprocess) ──► backend (uvicorn in Docker) ──► PostgreSQL
                        └─► SeaweedFS (S3-compatible object storage)

PostgreSQL and the backend share a Docker network so the backend can reach the
database by container alias. SeaweedFS is reached directly from the host CLI
process, matching the production data-plane topology.
"""

from __future__ import annotations

import os
import subprocess
import time
from collections.abc import Iterator
from pathlib import Path

import boto3
import httpx
import pytest
from botocore.config import Config
from testcontainers.community.postgres import PostgresContainer
from testcontainers.core.container import DockerContainer
from testcontainers.core.image import DockerImage
from testcontainers.core.network import Network
from testcontainers.core.wait_strategies import LogMessageWaitStrategy

REPO_ROOT = Path(__file__).resolve().parents[1]
BACKEND_DIR = REPO_ROOT / "backend"
CLI_DIR = REPO_ROOT / "cli"
TAKEOUT_FIXTURE = REPO_ROOT / "e2e" / "fixtures" / "google" / "takeout"

POSTGRES_USER = "rosalind"
POSTGRES_PASSWORD = "rosalind"
POSTGRES_DB = "rosalind"

S3_ACCESS_KEY = "rosalind"
S3_SECRET_KEY = "rosalind"
S3_BUCKET = "rosalind"
S3_REGION = "us-east-1"

BACKEND_IMAGE = "rosalind-e2e"


@pytest.fixture(scope="session")
def network() -> Iterator[Network]:
    net = Network()
    try:
        net.create()
    except Exception as exc:  # noqa: BLE001 - skip if Docker is unavailable
        pytest.skip(f"Docker unavailable: {exc}")
        return
    try:
        yield net
    finally:
        net.remove()


@pytest.fixture(scope="session")
def postgres_container(network: Network) -> Iterator[PostgresContainer]:
    container = PostgresContainer(
        "postgres:18",
        driver="psycopg",
        username=POSTGRES_USER,
        password=POSTGRES_PASSWORD,
        dbname=POSTGRES_DB,
    )
    container.with_network(network).with_network_aliases("postgres")
    container.start()
    try:
        yield container
    finally:
        container.stop()


@pytest.fixture(scope="session")
def s3_endpoint(network: Network) -> Iterator[str]:
    try:
        container = (
            DockerContainer("chrislusf/seaweedfs:latest")
            .with_command("server -dir=/data -s3")
            .with_env("AWS_ACCESS_KEY_ID", S3_ACCESS_KEY)
            .with_env("AWS_SECRET_ACCESS_KEY", S3_SECRET_KEY)
            .with_network(network)
            .with_network_aliases("seaweedfs")
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


@pytest.fixture(scope="session")
def backend_base_url(
    network: Network,
    postgres_container: PostgresContainer,
    s3_endpoint: str,
) -> Iterator[str]:
    image = DockerImage(path=str(BACKEND_DIR), tag=BACKEND_IMAGE)
    image.build()

    database_url = (
        f"postgresql+psycopg://{POSTGRES_USER}:{POSTGRES_PASSWORD}"
        f"@postgres:5432/{POSTGRES_DB}"
    )
    container = DockerContainer(BACKEND_IMAGE)
    container.with_network(network)
    container.with_env("ROSALIND_DATABASE_URL", database_url)
    container.with_env("ROSALIND_S3_ENDPOINT", "http://seaweedfs:8333")
    container.with_env("ROSALIND_S3_ACCESS_KEY", S3_ACCESS_KEY)
    container.with_env("ROSALIND_S3_SECRET_KEY", S3_SECRET_KEY)
    container.with_env("ROSALIND_S3_REGION", S3_REGION)
    container.with_command(
        "sh -lc 'uv run alembic upgrade head && "
        "uv run uvicorn rosalind.api.app:app --host 0.0.0.0 --port 8000'"
    )
    container.with_exposed_ports(8000)
    container.start()

    host = container.get_container_host_ip()
    port = container.get_exposed_port(8000)
    base_url = f"http://{host}:{port}"
    try:
        _wait_for_health(base_url)
        yield base_url
    finally:
        container.stop()
        image.remove()


@pytest.fixture(scope="session")
def google_source(backend_base_url: str) -> dict:
    response = httpx.post(
        f"{backend_base_url}/sources",
        json={"provider": "google", "name": "google"},
    )
    assert response.status_code == 201, response.text
    return response.json()


@pytest.fixture(scope="session")
def takeout_fixture() -> Path:
    return TAKEOUT_FIXTURE


@pytest.fixture(scope="session")
def cli_env(backend_base_url: str, s3_endpoint: str) -> dict[str, str]:
    return {
        "ROSALIND_API_URL": backend_base_url,
        "ROSALIND_S3_ENDPOINT": s3_endpoint,
        "ROSALIND_S3_ACCESS_KEY": S3_ACCESS_KEY,
        "ROSALIND_S3_SECRET_KEY": S3_SECRET_KEY,
        "ROSALIND_S3_BUCKET": S3_BUCKET,
        "ROSALIND_S3_REGION": S3_REGION,
    }


@pytest.fixture(scope="session")
def s3_client(s3_endpoint: str):
    return boto3.client(
        "s3",
        endpoint_url=s3_endpoint,
        aws_access_key_id=S3_ACCESS_KEY,
        aws_secret_access_key=S3_SECRET_KEY,
        region_name=S3_REGION,
        config=Config(retries={"max_attempts": 5, "mode": "standard"}),
    )


@pytest.fixture(scope="session")
def run_cli(cli_env: dict[str, str]):
    def _run(path: Path) -> subprocess.CompletedProcess[str]:
        env = {**os.environ, **cli_env}
        return subprocess.run(
            [
                "uv",
                "run",
                "--directory",
                str(CLI_DIR),
                "rosalind",
                "import",
                "create",
                "--source",
                "google",
                "--type",
                "takeout",
                str(path),
            ],
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )

    return _run


@pytest.fixture(scope="session")
def run_rosalind(cli_env: dict[str, str]):
    def _run(args: list[str]) -> subprocess.CompletedProcess[str]:
        env = {**os.environ, **cli_env}
        return subprocess.run(
            ["uv", "run", "--directory", str(CLI_DIR), "rosalind", *args],
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )

    return _run


def _wait_for_health(base_url: str, timeout: float = 120.0) -> None:
    deadline = time.monotonic() + timeout
    last_error: Exception | None = None
    while time.monotonic() < deadline:
        try:
            response = httpx.get(f"{base_url}/health", timeout=2.0)
            if response.status_code == 200:
                return
        except httpx.HTTPError as exc:
            last_error = exc
        time.sleep(1.0)
    raise RuntimeError(f"backend did not become healthy: {last_error}")
