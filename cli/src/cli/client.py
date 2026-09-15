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
