import httpx

from cli import config

DEFAULT_TIMEOUT_SECONDS = 5.0


class ApiClientError(Exception):
    """Raised when the backend cannot be reached or returns an error."""


def get_health() -> dict[str, str]:
    try:
        response = httpx.get(
            f"{config.api_url()}/health",
            timeout=DEFAULT_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
    except httpx.HTTPError as exc:
        raise ApiClientError(f"unable to reach the Rosalind backend: {exc}") from exc

    return response.json()


def create_import(source: str, type_: str) -> dict[str, object]:
    try:
        response = httpx.post(
            f"{config.api_url()}/imports/{source}/{type_}",
            timeout=DEFAULT_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
    except httpx.HTTPError as exc:
        raise ApiClientError(f"unable to create import: {exc}") from exc

    return response.json()


def complete_import(import_id: str, manifest: dict[str, object]) -> dict[str, object]:
    try:
        response = httpx.post(
            f"{config.api_url()}/imports/{import_id}/complete",
            json=manifest,
            timeout=DEFAULT_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
    except httpx.HTTPError as exc:
        raise ApiClientError(f"unable to complete import: {exc}") from exc

    return response.json()


def list_imports() -> list[dict[str, object]]:
    try:
        response = httpx.get(
            f"{config.api_url()}/imports",
            timeout=DEFAULT_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
    except httpx.HTTPError as exc:
        raise ApiClientError(f"unable to list imports: {exc}") from exc

    return response.json()["imports"]


def get_import(import_id: str) -> dict[str, object]:
    try:
        response = httpx.get(
            f"{config.api_url()}/imports/{import_id}",
            timeout=DEFAULT_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
    except httpx.HTTPError as exc:
        raise ApiClientError(f"unable to get import: {exc}") from exc

    return response.json()


def delete_import(import_id: str) -> None:
    try:
        response = httpx.delete(
            f"{config.api_url()}/imports/{import_id}",
            timeout=DEFAULT_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
    except httpx.HTTPError as exc:
        raise ApiClientError(f"unable to delete import: {exc}") from exc


def connect_google() -> dict[str, object]:
    try:
        response = httpx.post(
            f"{config.api_url()}/auth/google/connect",
            timeout=DEFAULT_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
    except httpx.HTTPError as exc:
        raise ApiClientError(f"unable to start Google authorization: {exc}") from exc

    return response.json()


def google_auth_status(state: str) -> dict[str, object]:
    try:
        response = httpx.get(
            f"{config.api_url()}/auth/google/status",
            params={"state": state},
            timeout=DEFAULT_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
    except httpx.HTTPError as exc:
        raise ApiClientError(f"unable to check authorization status: {exc}") from exc

    return response.json()


def import_google_profile() -> dict[str, object]:
    try:
        response = httpx.post(
            f"{config.api_url()}/imports/google/profile",
            timeout=DEFAULT_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
    except httpx.HTTPError as exc:
        raise ApiClientError(f"unable to import Google profile: {exc}") from exc

    return response.json()
