"""Thin HTTP transport shared by all CLI resource clients.

Commands never touch ``httpx`` directly; they go through the resource modules
in this package, which build on ``ApiClient``.
"""

from __future__ import annotations

from typing import Any

import httpx

from cli import config

DEFAULT_TIMEOUT_SECONDS = 5.0


class ApiClientError(Exception):
    """Raised when the backend cannot be reached or returns an error."""


class ApiClient:
    def __init__(
        self,
        base_url: str | None = None,
        timeout: float = DEFAULT_TIMEOUT_SECONDS,
    ) -> None:
        self._base_url = (base_url or config.api_url()).rstrip("/")
        self._timeout = timeout

    def get(self, path: str, *, params: dict[str, Any] | None = None) -> Any:
        return self._request("GET", path, params=params)

    def post(self, path: str, *, json: Any = None) -> Any:
        return self._request("POST", path, json=json)

    def delete(self, path: str) -> Any:
        return self._request("DELETE", path)

    def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json: Any = None,
    ) -> Any:
        try:
            response = httpx.request(
                method,
                f"{self._base_url}{path}",
                params=params,
                json=json,
                timeout=self._timeout,
            )
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise ApiClientError(_error_detail(exc.response)) from exc
        except httpx.HTTPError as exc:
            raise ApiClientError(
                f"unable to reach the Rosalind backend: {exc}"
            ) from exc

        if response.status_code == 204:
            return None
        return response.json()


def _error_detail(response: httpx.Response) -> str:
    try:
        detail = response.json().get("detail")
    except ValueError:
        return f"request failed ({response.status_code})"
    if isinstance(detail, str):
        return detail
    return f"request failed ({response.status_code})"


api = ApiClient()


def get_health() -> dict[str, str]:
    return api.get("/health")
