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
