"""Thin HTTP transport shared by all CLI resource clients.

Commands never touch ``httpx`` directly; they go through the resource modules
in this package, which build on ``ApiClient``.
"""

from __future__ import annotations

from collections.abc import Iterator
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
        self._explicit_base_url = base_url.rstrip("/") if base_url else None
        self._timeout = timeout

    @property
    def _base_url(self) -> str:
        """Backend base URL, resolved from config at request time.

        Resolved lazily so a profile selected on the command line (after import)
        is honoured, and a malformed config surfaces as a clean CLI error.
        """
        return self._explicit_base_url or config.api_url().rstrip("/")

    def get(
        self,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        timeout: float | None = None,
    ) -> Any:
        return self._request("GET", path, params=params, timeout=timeout)

    def post(self, path: str, *, json: Any = None, timeout: float | None = None) -> Any:
        return self._request("POST", path, json=json, timeout=timeout)

    def delete(self, path: str, *, timeout: float | None = None) -> Any:
        return self._request("DELETE", path, timeout=timeout)

    def stream_post(self, path: str, *, json: Any = None) -> Iterator[str]:
        """POST and stream newline-delimited lines (used by long-running commands).

        The access token is fetched up front and refreshed once if the server
        answers 401 before any body is streamed.
        """
        from cli.client import auth

        for attempt in range(2):
            token = auth.get_access_token(force_refresh=attempt == 1)
            headers: dict[str, str] = {}
            if token:
                headers["Authorization"] = f"Bearer {token}"

            try:
                with httpx.stream(
                    "POST",
                    f"{self._base_url}{path}",
                    json=json,
                    headers=headers,
                    timeout=None,  # nosec B113 - indexing may stream for a very long time
                ) as response:
                    if (
                        response.status_code == 401
                        and token is not None
                        and attempt == 0
                    ):
                        continue
                    if response.is_error:
                        # Buffer the body before raising so the error detail can
                        # still be read once the streaming context closes.
                        response.read()
                    response.raise_for_status()
                    for line in response.iter_lines():
                        if line:
                            yield line
                    return
            except httpx.HTTPStatusError as exc:
                raise ApiClientError(_error_detail(exc.response)) from exc
            except httpx.HTTPError as exc:
                raise ApiClientError(
                    f"unable to reach the Rosalind backend: {exc}"
                ) from exc

    def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json: Any = None,
        timeout: float | None = None,
    ) -> Any:
        return self._request_with_auth(
            method,
            path,
            params=params,
            json=json,
            timeout=timeout,
            retried=False,
        )

    def _request_with_auth(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None,
        json: Any,
        timeout: float | None,
        retried: bool,
    ) -> Any:
        from cli.client import auth

        headers: dict[str, str] = {}
        token = auth.get_access_token(force_refresh=retried)
        if token:
            headers["Authorization"] = f"Bearer {token}"

        try:
            response = httpx.request(
                method,
                f"{self._base_url}{path}",
                params=params,
                json=json,
                headers=headers,
                timeout=self._timeout if timeout is None else timeout,
            )
            if response.status_code == 401 and not retried and token is not None:
                return self._request_with_auth(
                    method,
                    path,
                    params=params,
                    json=json,
                    timeout=timeout,
                    retried=True,
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
    except ValueError, httpx.ResponseNotRead:
        return f"request failed ({response.status_code})"
    if isinstance(detail, str):
        return detail
    return f"request failed ({response.status_code})"


api = ApiClient()


def get_health() -> dict[str, str]:
    return api.get("/health")
