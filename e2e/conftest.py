"""Shared fixtures standing up the full import stack for e2e tests.

The stack under test is:

    CLI (subprocess) ──► backend (uvicorn in Docker) ──► PostgreSQL
                        └─► SeaweedFS (S3-compatible object storage)

PostgreSQL and the backend share a Docker network so the backend can reach the
database by container alias. SeaweedFS is reached directly from the host CLI
process, matching the production data-plane topology.

The email-RAG suite (``pytest -m rag``) additionally starts a TEI embedder
container serving BGE-M3 and points the backend at it, so the offline embed
stage and the online semantic branch run against the real model.
"""

from __future__ import annotations

import os
import re
import subprocess
import tempfile
import time
import uuid
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

import boto3
import docker
import httpx
import psycopg
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
SYNTHETIC_MBOX = TAKEOUT_FIXTURE / "Mail" / "rosalind_synthetic_emails.mbox"

POSTGRES_USER = "rosalind"
POSTGRES_PASSWORD = "rosalind"
POSTGRES_DB = "rosalind"

S3_ACCESS_KEY = "rosalind"
S3_SECRET_KEY = "rosalind"
S3_BUCKET = "rosalind"
S3_REGION = "us-east-1"

BACKEND_IMAGE = "rosalind-e2e"

SELF_EMAIL = "felipe@example.test"

TEI_IMAGE = os.environ.get(
    "ROSALIND_E2E_TEI_IMAGE",
    "ghcr.io/huggingface/text-embeddings-inference:cpu-1.6",
)
TEI_MODEL = os.environ.get("ROSALIND_E2E_TEI_MODEL", "BAAI/bge-m3")
TEI_NETWORK_URL = "http://tei-embedder:80"
# TEI publishes amd64 images only; force amd64 so the container also runs on
# arm64 hosts (Rosetta/QEMU emulation under Docker Desktop).
TEI_PLATFORM = os.environ.get("ROSALIND_E2E_TEI_PLATFORM", "linux/amd64")

TOKENIZER_SHA256 = "21106b6d7dab2952c1d496fb21d5dc9db75c28ed361a05f5020bbba27810dd08"

IMPORT_ID_RE = re.compile(r"ID:\s+([0-9a-f-]{36})")

ANONYMOUS_ISSUER = "local"
ANONYMOUS_SUBJECT = "anonymous"


def _import_id_from_stdout(stdout: str) -> str:
    match = IMPORT_ID_RE.search(stdout)
    assert match, f"import_id not found in CLI output: {stdout!r}"
    return match.group(1)


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
        "paradedb/paradedb:0.26.0-pg18",
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


def _start_backend_container(
    network: Network,
    postgres_container: PostgresContainer,
    s3_endpoint: str,
    *,
    extra_env: dict[str, str] | None = None,
) -> tuple[str, DockerContainer, DockerImage]:
    image = DockerImage(path=str(BACKEND_DIR), tag=BACKEND_IMAGE)
    image.build()

    database_url = (
        f"postgresql+psycopg://{POSTGRES_USER}:{POSTGRES_PASSWORD}"
        f"@postgres:5432/{POSTGRES_DB}"
    )
    env = {
        "ROSALIND_DATABASE_URL": database_url,
        "ROSALIND_S3_ENDPOINT": "http://seaweedfs:8333",
        "ROSALIND_S3_ACCESS_KEY": S3_ACCESS_KEY,
        "ROSALIND_S3_SECRET_KEY": S3_SECRET_KEY,
        "ROSALIND_S3_REGION": S3_REGION,
        "ROSALIND_AUTH_ENABLED": "false",
    }
    if extra_env:
        env.update(extra_env)

    container = DockerContainer(BACKEND_IMAGE)
    container.with_network(network)
    for key, value in env.items():
        container.with_env(key, value)
    container.with_command(
        "sh -lc 'uv run alembic upgrade head && "
        "uv run uvicorn rosalind.adapters.inbound.http.app:app --host 0.0.0.0 --port 8000'"
    )
    container.with_exposed_ports(8000)
    container.start()

    host = container.get_container_host_ip()
    port = container.get_exposed_port(8000)
    base_url = f"http://{host}:{port}"
    _wait_for_health(base_url)
    return base_url, container, image


@pytest.fixture(scope="session")
def backend_base_url(
    network: Network,
    postgres_container: PostgresContainer,
    s3_endpoint: str,
) -> Iterator[str]:
    base_url, container, image = _start_backend_container(
        network, postgres_container, s3_endpoint
    )
    try:
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
    return _cli_env(backend_base_url, s3_endpoint)


def _cli_env(backend_base_url: str, s3_endpoint: str) -> dict[str, str]:
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


# ---------------------------------------------------------------------------
# Email-RAG stack
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session")
def tei_embedder(network: Network) -> Iterator[str]:
    """A TEI container serving BGE-M3, reachable by the backend as
    ``tei-embedder``. Yields the host-mapped ``/embed`` URL for contract checks."""
    try:
        container = (
            DockerContainer(TEI_IMAGE, platform=TEI_PLATFORM)
            .with_command(f"--model-id {TEI_MODEL} --port 80")
            .with_network(network)
            .with_network_aliases("tei-embedder")
            .with_exposed_ports(80)
        )
        _pull_image(container, TEI_IMAGE, TEI_PLATFORM)
        container.start()
    except Exception as exc:  # noqa: BLE001 - skip if the model/image is unavailable
        pytest.skip(f"TEI embedder unavailable: {exc}")
        return ""

    try:
        host = container.get_container_host_ip()
        port = container.get_exposed_port(80)
        url = f"http://{host}:{port}"
        _wait_for_tei(url)
        yield url
    finally:
        container.stop()


def _pull_image(container: DockerContainer, image: str, platform: str) -> None:
    """Pre-pull ``image`` for ``platform`` (testcontainers pulls host-platform)."""
    client = container.get_docker_client()
    try:
        client.client.images.get(image)
    except docker.errors.ImageNotFound:
        client.client.images.pull(image, platform=platform)


@pytest.fixture(scope="session")
def rag_backend_base_url(
    network: Network,
    postgres_container: PostgresContainer,
    s3_endpoint: str,
    tei_embedder: str,
) -> Iterator[str]:
    base_url, container, image = _start_backend_container(
        network,
        postgres_container,
        s3_endpoint,
        extra_env={
            "ROSALIND_EMBEDDER_URL": TEI_NETWORK_URL,
            "ROSALIND_ALLOW_REMOTE_EMBEDDING": "true",
            "ROSALIND_CHUNK_TOKENIZER_PATH": "/app/assets/bge-m3/tokenizer.json",
            "ROSALIND_CHUNK_TOKENIZER_SHA256": TOKENIZER_SHA256,
        },
    )
    try:
        yield base_url
    finally:
        container.stop()
        image.remove()


@pytest.fixture(scope="session")
def rag_pg_conn(postgres_container: PostgresContainer) -> Iterator[psycopg.Connection]:
    url = postgres_container.get_connection_url().replace("+psycopg", "")
    conn = psycopg.connect(url)
    try:
        yield conn
    finally:
        conn.close()


@pytest.fixture(scope="session")
def rag_self_person(
    rag_backend_base_url: str, rag_pg_conn: psycopg.Connection
) -> dict:
    """Seed the anonymous account's self person (test setup, not under test)."""
    with rag_pg_conn.cursor() as cur:
        cur.execute(
            "SELECT account_id FROM account_identity WHERE issuer = %s AND subject = %s",
            (ANONYMOUS_ISSUER, ANONYMOUS_SUBJECT),
        )
        row = cur.fetchone()
        if row is None:
            account_id = str(uuid.uuid4())
            cur.execute(
                "INSERT INTO account (id, created_at, updated_at) VALUES (%s, now(), now())",
                (account_id,),
            )
            cur.execute(
                "INSERT INTO account_identity "
                "(id, account_id, issuer, subject, created_at, last_seen_at) "
                "VALUES (%s, %s, %s, %s, now(), now())",
                (str(uuid.uuid4()), account_id, ANONYMOUS_ISSUER, ANONYMOUS_SUBJECT),
            )
        else:
            account_id = str(row[0])

        person_id = str(uuid.uuid4())
        cur.execute(
            "INSERT INTO core.person (id, created_at, updated_at) VALUES (%s, now(), now())",
            (person_id,),
        )
        cur.execute(
            "INSERT INTO core.person_email "
            "(id, person_id, email, email_normalized, is_primary, is_verified) "
            "VALUES (%s, %s, %s, %s, true, true)",
            (str(uuid.uuid4()), person_id, SELF_EMAIL, SELF_EMAIL.lower()),
        )
        cur.execute(
            "UPDATE account SET self_person_id = %s WHERE id = %s",
            (person_id, account_id),
        )
    rag_pg_conn.commit()
    return {"account_id": account_id, "person_id": person_id, "email": SELF_EMAIL}


@pytest.fixture(scope="session")
def rag_cli_env(rag_backend_base_url: str, s3_endpoint: str) -> dict[str, str]:
    return _cli_env(rag_backend_base_url, s3_endpoint)


@pytest.fixture(scope="session")
def rag_run_rosalind(rag_cli_env: dict[str, str]):
    def _run(args: list[str]) -> subprocess.CompletedProcess[str]:
        env = {**os.environ, **rag_cli_env}
        return subprocess.run(
            ["uv", "run", "--directory", str(CLI_DIR), "rosalind", *args],
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )

    return _run


@dataclass(frozen=True)
class RagCorpus:
    base_url: str
    import_id: str
    source_id: str
    conn: psycopg.Connection
    self_person: dict


@pytest.fixture(scope="session")
def rag_corpus(
    rag_backend_base_url: str,
    rag_pg_conn: psycopg.Connection,
    rag_self_person: dict,
    rag_cli_env: dict[str, str],
) -> Iterator[RagCorpus]:
    """Import the synthetic MBOX and run the full offline pipeline."""
    source_resp = httpx.post(
        f"{rag_backend_base_url}/sources",
        json={"provider": "google", "name": "google"},
    )
    assert source_resp.status_code == 201, source_resp.text
    source_id = source_resp.json()["source_id"]

    with tempfile.TemporaryDirectory() as tmp:
        staged = Path(tmp) / "Mail"
        staged.mkdir()
        (staged / "rosalind_synthetic_emails.mbox").write_bytes(
            SYNTHETIC_MBOX.read_bytes()
        )

        env = {**os.environ, **rag_cli_env}
        imported = subprocess.run(
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
                str(Path(tmp)),
            ],
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )
        assert imported.returncode == 0, imported.stderr
        import_id = _import_id_from_stdout(imported.stdout)

        pipelined = subprocess.run(
            [
                "uv",
                "run",
                "--directory",
                str(CLI_DIR),
                "rosalind",
                "pipeline",
                "run",
                import_id,
            ],
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )
        assert pipelined.returncode == 0, pipelined.stdout + pipelined.stderr

    yield RagCorpus(
        base_url=rag_backend_base_url,
        import_id=import_id,
        source_id=source_id,
        conn=rag_pg_conn,
        self_person=rag_self_person,
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


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


def _wait_for_tei(url: str, timeout: float = 900.0) -> None:
    deadline = time.monotonic() + timeout
    last_error: str | None = None
    while time.monotonic() < deadline:
        try:
            response = httpx.post(
                f"{url}/embed",
                json={"inputs": ["ping"], "normalize": True},
                timeout=60.0,
            )
            if response.status_code == 200:
                return
            last_error = f"HTTP {response.status_code}"
        except httpx.HTTPError as exc:
            last_error = str(exc)
        time.sleep(3.0)
    raise RuntimeError(f"TEI embedder did not become ready: {last_error}")
