"""Shared fixtures standing up the full import stack for e2e tests.

The stack under test is:

    CLI (subprocess) ──► backend ──► PostgreSQL
                        └─► SeaweedFS (S3-compatible object storage)

PostgreSQL and SeaweedFS run as testcontainers reachable from the host. The
non-RAG suite runs the backend as a Docker image; the email-RAG suite
(``pytest -m rag``) runs the backend as a native host process so BGE-M3 runs
in-process via FlagEmbedding on Apple's MPS backend, exercising the same
embedding path as local development.
"""

from __future__ import annotations

import base64
import json
import os
import re
import secrets
import signal
import socket
import subprocess
import tempfile
import time
import uuid
from collections.abc import Iterator
from contextlib import suppress
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import TextIO

import boto3
import httpx
import psycopg
import pytest
from botocore.config import Config
from psycopg import sql
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

KEYCLOAK_IMAGE = "quay.io/keycloak/keycloak:26.7.4"
KEYCLOAK_ADMIN_USER = "admin"
KEYCLOAK_ADMIN_PASSWORD = "admin"  # nosec B105 - test-only bootstrap credential
KEYCLOAK_REALM = "rosalind"
KEYCLOAK_CLIENT_ID = "rosalind-cli"
KEYCLOAK_INTERNAL_URL = "http://keycloak:8080"
KEYCLOAK_REALM_FILE = REPO_ROOT / "keycloak" / "rosalind-realm.json"

SPLIT_DB_PREFIX = "rosalind_split_"
SPLIT_BUCKET_PREFIX = "rosalind-split-"

# The RAG suite runs the backend natively with FlagEmbedding on MPS (Apple
# Silicon). The device can be overridden (e.g. "cpu") for non-Mac hosts.
RAG_EMBEDDER_DEVICE = os.environ.get("ROSALIND_E2E_EMBEDDER_DEVICE", "mps")

TOKENIZER_SHA256 = "21106b6d7dab2952c1d496fb21d5dc9db75c28ed361a05f5020bbba27810dd08"  # gitleaks:allow

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
        container.waiting_for(
            LogMessageWaitStrategy("Start Seaweed S3 API Server")
        )
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
def backend_image() -> Iterator[DockerImage]:
    image = DockerImage(path=str(BACKEND_DIR), tag=BACKEND_IMAGE)
    image.build()
    try:
        yield image
    finally:
        image.remove()


def _start_backend_container(
    network: Network,
    image: DockerImage,
    *,
    database_url: str,
    s3_bucket: str = S3_BUCKET,
    extra_env: dict[str, str] | None = None,
) -> tuple[str, DockerContainer]:
    env = {
        "ROSALIND_DATABASE_URL": database_url,
        "ROSALIND_S3_ENDPOINT": "http://seaweedfs:8333",
        "ROSALIND_S3_ACCESS_KEY": S3_ACCESS_KEY,
        "ROSALIND_S3_SECRET_KEY": S3_SECRET_KEY,
        "ROSALIND_S3_BUCKET": s3_bucket,
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
    return base_url, container


@pytest.fixture(scope="session")
def backend_base_url(
    network: Network,
    backend_image: DockerImage,
    postgres_container: PostgresContainer,
    s3_endpoint: str,
) -> Iterator[str]:
    database_url = (
        f"postgresql+psycopg://{POSTGRES_USER}:{POSTGRES_PASSWORD}"
        f"@postgres:5432/{POSTGRES_DB}"
    )
    base_url, container = _start_backend_container(
        network, backend_image, database_url=database_url
    )
    try:
        yield base_url
    finally:
        container.stop()


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


def _cli_env(
    backend_base_url: str,
    s3_endpoint: str,
    *,
    bucket: str = S3_BUCKET,
    extra: dict[str, str] | None = None,
) -> dict[str, str]:
    env = {
        "ROSALIND_API_URL": backend_base_url,
        "ROSALIND_S3_ENDPOINT": s3_endpoint,
        "ROSALIND_S3_ACCESS_KEY": S3_ACCESS_KEY,
        "ROSALIND_S3_SECRET_KEY": S3_SECRET_KEY,
        "ROSALIND_S3_BUCKET": bucket,
        "ROSALIND_S3_REGION": S3_REGION,
    }
    if extra:
        env.update(extra)
    return env


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
                "--via",
                "file",
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
# Keycloak-backed index-split stack
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class KeycloakStack:
    internal_url: str
    host_url: str


@dataclass(frozen=True)
class SplitDatabase:
    name: str
    backend_url: str
    host_url: str


@dataclass(frozen=True)
class SplitAccount:
    subject: str
    issuer: str
    email: str
    access_token: str
    cli_env: dict[str, str]


def _wait_for_keycloak(base_url: str, timeout: float = 180.0) -> None:
    deadline = time.monotonic() + timeout
    last_error: Exception | None = None
    url = f"{base_url}/realms/{KEYCLOAK_REALM}/.well-known/openid-configuration"
    while time.monotonic() < deadline:
        try:
            response = httpx.get(url, timeout=2.0)
            if response.status_code == 200:
                return
        except httpx.HTTPError as exc:
            last_error = exc
        time.sleep(1.0)
    raise RuntimeError(f"Keycloak did not become ready: {last_error}")


def _disable_keycloak_ssl(container: DockerContainer) -> None:
    """Allow plain HTTP to the ephemeral test Keycloak (both auth realms)."""
    kcadm = "/opt/keycloak/bin/kcadm.sh"
    for realm in ("master", KEYCLOAK_REALM):
        result = container.get_wrapped_container().exec_run(
            [
                kcadm,
                "update",
                f"realms/{realm}",
                "-s",
                "sslRequired=none",
                "--no-config",
                "--server",
                "http://localhost:8080",
                "--realm",
                "master",
                "--user",
                KEYCLOAK_ADMIN_USER,
                "--password",
                KEYCLOAK_ADMIN_PASSWORD,
            ]
        )
        if result.exit_code != 0:
            raise RuntimeError(
                f"failed to disable SSL on Keycloak realm {realm}: "
                f"{result.output.decode(errors='replace')}"
            )


@pytest.fixture(scope="session")
def keycloak_stack(network: Network) -> Iterator[KeycloakStack]:
    if not KEYCLOAK_REALM_FILE.is_file():
        pytest.fail(f"missing Keycloak realm file: {KEYCLOAK_REALM_FILE}")

    try:
        container = (
            DockerContainer(KEYCLOAK_IMAGE)
            .with_command("start-dev --import-realm")
            .with_env("KC_BOOTSTRAP_ADMIN_USERNAME", KEYCLOAK_ADMIN_USER)
            .with_env("KC_BOOTSTRAP_ADMIN_PASSWORD", KEYCLOAK_ADMIN_PASSWORD)
            .with_env("KC_HEALTH_ENABLED", "true")
            .with_env("KC_HOSTNAME", KEYCLOAK_INTERNAL_URL)
            .with_env("KC_HOSTNAME_STRICT", "false")
            .with_env("KC_HTTP_ENABLED", "true")
            .with_network(network)
            .with_network_aliases("keycloak")
            .with_volume_mapping(
                str(KEYCLOAK_REALM_FILE),
                "/opt/keycloak/data/import/rosalind-realm.json",
            )
            .with_exposed_ports(8080)
        )
        container.start()
    except Exception as exc:  # noqa: BLE001 - skip if Docker is unavailable
        pytest.skip(f"Docker unavailable: {exc}")
        return

    try:
        host = container.get_container_host_ip()
        port = container.get_exposed_port(8080)
        host_url = f"http://{host}:{port}"
        _wait_for_keycloak(host_url)
        _disable_keycloak_ssl(container)
        yield KeycloakStack(
            internal_url=KEYCLOAK_INTERNAL_URL,
            host_url=host_url,
        )
    finally:
        container.stop()


def _keycloak_admin_token(host_url: str) -> str:
    response = httpx.post(
        f"{host_url}/realms/master/protocol/openid-connect/token",
        data={
            "client_id": "admin-cli",
            "grant_type": "password",
            "username": KEYCLOAK_ADMIN_USER,
            "password": KEYCLOAK_ADMIN_PASSWORD,
        },
        timeout=30.0,
    )
    assert response.status_code == 200, response.text
    return response.json()["access_token"]


def _create_keycloak_user(host_url: str, email: str, password: str) -> str:
    admin_token = _keycloak_admin_token(host_url)
    response = httpx.post(
        f"{host_url}/admin/realms/{KEYCLOAK_REALM}/users",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={
            "username": email,
            "email": email,
            "firstName": "Split",
            "lastName": "E2E",
            "enabled": True,
            "emailVerified": True,
            "credentials": [
                {"type": "password", "value": password, "temporary": False}
            ],
        },
        timeout=30.0,
    )
    assert response.status_code == 201, response.text
    location = response.headers.get("Location")
    assert location, f"Keycloak did not return a user Location header: {response.text}"
    return location.rstrip("/").rsplit("/", 1)[-1]


def _keycloak_user_token(host_url: str, email: str, password: str) -> dict:
    response = httpx.post(
        f"{host_url}/realms/{KEYCLOAK_REALM}/protocol/openid-connect/token",
        data={
            "client_id": KEYCLOAK_CLIENT_ID,
            "grant_type": "password",
            "username": email,
            "password": password,
            "scope": "openid email profile rosalind-audience",
        },
        timeout=30.0,
    )
    assert response.status_code == 200, response.text
    return response.json()


def _jwt_claims(token: str) -> dict:
    payload = token.split(".")[1]
    payload += "=" * (-len(payload) % 4)
    return json.loads(base64.urlsafe_b64decode(payload))


@pytest.fixture(scope="session")
def split_database(
    postgres_container: PostgresContainer,
) -> Iterator[SplitDatabase]:
    name = f"{SPLIT_DB_PREFIX}{uuid.uuid4().hex[:8]}"
    admin_url = postgres_container.get_connection_url().replace("+psycopg", "")

    conn = psycopg.connect(admin_url, autocommit=True)
    try:
        with conn.cursor() as cur:
            cur.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))
    finally:
        conn.close()

    backend_url = (
        f"postgresql+psycopg://{POSTGRES_USER}:{POSTGRES_PASSWORD}@postgres:5432/{name}"
    )
    host_url = admin_url.rsplit("/", 1)[0] + "/" + name
    try:
        yield SplitDatabase(name=name, backend_url=backend_url, host_url=host_url)
    finally:
        conn = psycopg.connect(admin_url, autocommit=True)
        try:
            with conn.cursor() as cur:
                cur.execute(
                    sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(
                        sql.Identifier(name)
                    )
                )
        finally:
            conn.close()


@pytest.fixture(scope="session")
def split_bucket(s3_client) -> Iterator[str]:
    name = f"{SPLIT_BUCKET_PREFIX}{uuid.uuid4().hex[:12]}"
    s3_client.create_bucket(Bucket=name)
    try:
        yield name
    finally:
        with suppress(Exception):
            paginator = s3_client.get_paginator("list_objects_v2")
            for page in paginator.paginate(Bucket=name):
                objects = [{"Key": item["Key"]} for item in page.get("Contents", [])]
                if objects:
                    s3_client.delete_objects(Bucket=name, Delete={"Objects": objects})
            s3_client.delete_bucket(Bucket=name)


@pytest.fixture(scope="session")
def split_backend_base_url(
    network: Network,
    backend_image: DockerImage,
    split_database: SplitDatabase,
    split_bucket: str,
    s3_endpoint: str,
    keycloak_stack: KeycloakStack,
) -> Iterator[str]:
    base_url, container = _start_backend_container(
        network,
        backend_image,
        database_url=split_database.backend_url,
        s3_bucket=split_bucket,
        extra_env={
            "ROSALIND_AUTH_ENABLED": "true",
            "ROSALIND_KEYCLOAK_URL": keycloak_stack.internal_url,
            "ROSALIND_KEYCLOAK_REALM": KEYCLOAK_REALM,
            "ROSALIND_KEYCLOAK_AUDIENCE": KEYCLOAK_REALM,
        },
    )
    try:
        yield base_url
    finally:
        container.stop()


@pytest.fixture(scope="session")
def split_pg_conn(
    split_database: SplitDatabase,
) -> Iterator[psycopg.Connection]:
    conn = psycopg.connect(split_database.host_url)
    try:
        yield conn
    finally:
        conn.close()


@pytest.fixture(scope="session")
def split_account(
    keycloak_stack: KeycloakStack,
    split_backend_base_url: str,
    split_bucket: str,
    s3_endpoint: str,
) -> Iterator[SplitAccount]:
    email = f"split-e2e-{uuid.uuid4().hex[:12]}@example.test"
    password = secrets.token_urlsafe(24)
    user_id = _create_keycloak_user(keycloak_stack.host_url, email, password)
    token_response = _keycloak_user_token(keycloak_stack.host_url, email, password)

    access_token = token_response["access_token"]
    claims = _jwt_claims(access_token)
    issuer = f"{keycloak_stack.internal_url}/realms/{KEYCLOAK_REALM}"
    assert claims["iss"] == issuer, claims
    assert claims["sub"] == user_id, claims
    audience = claims.get("aud")
    audiences = audience if isinstance(audience, list) else [audience]
    assert KEYCLOAK_REALM in audiences, claims

    config_dir = tempfile.TemporaryDirectory(prefix="rosalind-split-cli-")
    bootstrap = Path(config_dir.name) / "credentials.json"
    expires_in = int(token_response.get("expires_in") or 300)
    bootstrap.write_text(
        json.dumps(
            {
                "access_token": access_token,
                "refresh_token": token_response.get("refresh_token"),
                "expires_at": (
                    datetime.now(UTC) + timedelta(seconds=expires_in)
                ).isoformat(),
                "token_type": token_response.get("token_type", "Bearer"),
            }
        )
    )
    os.chmod(bootstrap, 0o600)

    env = _cli_env(
        split_backend_base_url,
        s3_endpoint,
        bucket=split_bucket,
        extra={
            "ROSALIND_CONFIG_DIR": config_dir.name,
            "ROSALIND_KEYCLOAK_URL": keycloak_stack.host_url,
            "ROSALIND_KEYCLOAK_REALM": KEYCLOAK_REALM,
            "ROSALIND_KEYCLOAK_CLIENT_ID": KEYCLOAK_CLIENT_ID,
        },
    )
    try:
        yield SplitAccount(
            subject=claims["sub"],
            issuer=issuer,
            email=email,
            access_token=access_token,
            cli_env=env,
        )
    finally:
        config_dir.cleanup()


@pytest.fixture(scope="session")
def split_run_rosalind(split_account: SplitAccount):
    def _run(args: list[str]) -> subprocess.CompletedProcess[str]:
        env = {**os.environ, **split_account.cli_env}
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
def rag_backend_base_url(
    postgres_container: PostgresContainer,
    s3_endpoint: str,
) -> Iterator[str]:
    """A native backend process embedding in-process via FlagEmbedding on MPS.

    Runs the backend with ``uv run`` against the same host-reachable Postgres and
    SeaweedFS the CLI uses, so the embed stage and online semantic branch run on
    the Mac's GPU rather than an emulated CPU server.
    """
    if not _flagembedding_available():
        pytest.skip(
            "FlagEmbedding is not installed in the backend env; "
            "run `just backend-install-ml` to enable in-process embedding"
        )
    base_url, proc, log_file = _start_native_backend(
        postgres_container, s3_endpoint
    )
    try:
        yield base_url
    finally:
        try:
            os.killpg(proc.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
        proc.wait(timeout=30)
        log_file.close()


def _flagembedding_available() -> bool:
    result = subprocess.run(
        [
            "uv",
            "run",
            "--directory",
            str(BACKEND_DIR),
            "python",
            "-c",
            "import importlib.util; "
            "raise SystemExit(0 if importlib.util.find_spec('FlagEmbedding') else 1)",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    return result.returncode == 0


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def _backend_env(
    postgres_container: PostgresContainer, s3_endpoint: str
) -> dict[str, str]:
    return {
        **os.environ,
        "ROSALIND_DATABASE_URL": postgres_container.get_connection_url(),
        "ROSALIND_S3_ENDPOINT": s3_endpoint,
        "ROSALIND_S3_ACCESS_KEY": S3_ACCESS_KEY,
        "ROSALIND_S3_SECRET_KEY": S3_SECRET_KEY,
        "ROSALIND_S3_REGION": S3_REGION,
        "ROSALIND_AUTH_ENABLED": "false",
        "ROSALIND_EMBEDDER_BACKEND": "flagembedding",
        "ROSALIND_EMBEDDER_DEVICE": RAG_EMBEDDER_DEVICE,
        "ROSALIND_SEARCH_RERANKER": "bge-reranker-v2-m3/v1",
        "ROSALIND_SEARCH_RERANKER_BACKEND": "flagembedding",
        "ROSALIND_SEARCH_RERANKER_MODEL": "BAAI/bge-reranker-v2-m3",
        "ROSALIND_SEARCH_RERANKER_DEVICE": RAG_EMBEDDER_DEVICE,
        "ROSALIND_CHUNK_TOKENIZER_PATH": str(
            BACKEND_DIR / "assets" / "bge-m3" / "tokenizer.json"
        ),
        "ROSALIND_CHUNK_TOKENIZER_SHA256": TOKENIZER_SHA256,
    }


def _start_native_backend(
    postgres_container: PostgresContainer, s3_endpoint: str
) -> tuple[str, subprocess.Popen, TextIO]:
    env = _backend_env(postgres_container, s3_endpoint)

    migrated = subprocess.run(
        [
            "uv",
            "run",
            "--directory",
            str(BACKEND_DIR),
            "alembic",
            "upgrade",
            "head",
        ],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert migrated.returncode == 0, migrated.stdout + migrated.stderr

    port = _free_port()
    log_file = tempfile.NamedTemporaryFile(
        mode="w", prefix="rosalind-rag-backend-", suffix=".log", delete=False
    )
    log_path = Path(log_file.name)
    proc = subprocess.Popen(
        [
            "uv",
            "run",
            "--directory",
            str(BACKEND_DIR),
            "uvicorn",
            "rosalind.adapters.inbound.http.app:app",
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
        ],
        env=env,
        stdout=log_file,
        stderr=subprocess.STDOUT,
        start_new_session=True,
    )
    base_url = f"http://127.0.0.1:{port}"
    try:
        _wait_for_health(base_url)
    except Exception:
        log_file.flush()
        log_file.close()
        raise RuntimeError(
            f"native backend failed to start; log:\n{log_path.read_text()}"
        )
    return base_url, proc, log_file


@pytest.fixture(scope="session")
def rag_pg_conn(
    postgres_container: PostgresContainer,
) -> Iterator[psycopg.Connection]:
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
                (
                    str(uuid.uuid4()),
                    account_id,
                    ANONYMOUS_ISSUER,
                    ANONYMOUS_SUBJECT,
                ),
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
    return {
        "account_id": account_id,
        "person_id": person_id,
        "email": SELF_EMAIL,
    }


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
                "--via",
                "file",
                str(staged / "rosalind_synthetic_emails.mbox"),
            ],
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )
        assert imported.returncode == 0, imported.stderr
        import_id = _import_id_from_stdout(imported.stdout)

        indexed = subprocess.run(
            [
                "uv",
                "run",
                "--directory",
                str(CLI_DIR),
                "rosalind",
                "index",
                import_id,
                "--self-email",
                SELF_EMAIL,
            ],
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )
        assert indexed.returncode == 0, indexed.stdout + indexed.stderr

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
