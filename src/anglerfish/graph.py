"""Thin Microsoft Graph HTTP client wrapper."""

from __future__ import annotations

from email.utils import parsedate_to_datetime
import time
from datetime import datetime, timezone
from typing import Any

import requests
from requests import Response

from .config import GRAPH_BASE_URL
from .exceptions import GraphApiError


class GraphClient:
    """Simple Graph API client with retries for rate limiting."""

    def __init__(
        self,
        access_token: str,
        *,
        base_url: str = GRAPH_BASE_URL,
        retries: int = 3,
        timeout: int = 30,
        session: requests.Session | None = None,
    ):
        self.base_url = base_url.rstrip("/")
        self.retries = max(retries, 1)
        self.timeout = timeout
        self.session = session or requests.Session()
        self.session.headers.update(
            {
                "Authorization": f"Bearer {access_token}",
                "Accept": "application/json",
            }
        )

    def get(self, path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        return self._request("GET", path, params=params)

    def post(
        self,
        path: str,
        json: dict[str, Any] | None = None,
        *,
        retry_safe: bool = False,
    ) -> dict[str, Any]:
        return self._request("POST", path, json=json, retry_safe=retry_safe)

    def put(
        self,
        path: str,
        data: bytes,
        content_type: str = "application/octet-stream",
        *,
        retry_safe: bool = False,
    ) -> dict[str, Any]:
        return self._request(
            "PUT",
            path,
            data=data,
            headers={"Content-Type": content_type},
            retry_safe=retry_safe,
        )

    def delete(self, path: str) -> None:
        """Issue a DELETE request. Expects 204 No Content on success."""
        self._request("DELETE", path)

    def _request(self, method: str, path: str, *, retry_safe: bool = False, **kwargs: Any) -> dict[str, Any]:
        normalized_method = method.strip().upper()
        request_path = path if path.startswith("/") else f"/{path}"
        url = f"{self.base_url}{request_path}"
        can_retry = retry_safe or normalized_method in {"GET", "DELETE"}

        for attempt in range(self.retries):
            try:
                response = self.session.request(normalized_method, url, timeout=self.timeout, **kwargs)
            except requests.RequestException as exc:
                if can_retry and attempt < self.retries - 1:
                    time.sleep(_compute_backoff(attempt))
                    continue
                raise GraphApiError(
                    f"Network error while calling Graph API: {exc}",
                    method=normalized_method,
                    path=request_path,
                ) from exc

            if response.status_code == 429 and can_retry and attempt < self.retries - 1:
                retry_after = _parse_retry_after(response.headers.get("Retry-After"))
                time.sleep(retry_after)
                continue

            if 500 <= response.status_code <= 599 and can_retry and attempt < self.retries - 1:
                time.sleep(_compute_backoff(attempt))
                continue

            if not response.ok:
                error_message, request_id, client_request_id = _extract_error_details(response)
                raise GraphApiError(
                    error_message,
                    status_code=response.status_code,
                    method=normalized_method,
                    path=request_path,
                    request_id=request_id,
                    client_request_id=client_request_id,
                )

            return _parse_json_response(response)

        raise GraphApiError("Request failed after retries.", status_code=0, method=normalized_method, path=request_path)


def _parse_retry_after(value: str | None) -> int:
    if not value:
        return 1

    try:
        parsed = int(value)
    except ValueError:
        try:
            retry_at = parsedate_to_datetime(value)
            now = datetime.now(timezone.utc)
            delay = int((retry_at - now).total_seconds())
            return max(delay, 1)
        except (TypeError, ValueError):
            return 1

    return max(parsed, 1)


def _compute_backoff(attempt: int, *, max_seconds: int = 8) -> int:
    return min(2**attempt, max_seconds)


def _extract_error_details(response: Response) -> tuple[str, str, str]:
    request_id = _first_non_empty(
        response.headers.get("request-id"),
        response.headers.get("x-ms-request-id"),
    )
    client_request_id = _first_non_empty(response.headers.get("client-request-id"))
    default_message = response.text or f"HTTP {response.status_code}"

    try:
        payload = response.json()
    except ValueError:
        return default_message, request_id, client_request_id

    if isinstance(payload, dict):
        error = payload.get("error")
        if isinstance(error, dict):
            code = error.get("code", "Unknown")
            message = error.get("message", default_message)
            inner = error.get("innerError")
            if isinstance(inner, dict):
                request_id = _first_non_empty(request_id, inner.get("request-id"))
                client_request_id = _first_non_empty(client_request_id, inner.get("client-request-id"))
            return f"{code}: {message}", request_id, client_request_id

    return default_message, request_id, client_request_id


def _first_non_empty(*values: object) -> str:
    for value in values:
        candidate = str(value or "").strip()
        if candidate:
            return candidate
    return ""


def _parse_json_response(response: Response) -> dict[str, Any]:
    if response.status_code == 204 or not response.content:
        return {}

    try:
        payload = response.json()
    except ValueError:
        return {}

    if isinstance(payload, dict):
        return payload

    return {"value": payload}
