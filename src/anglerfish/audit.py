"""Office 365 Management Activity API client."""

from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlparse

import requests

from .config import MANAGEMENT_API_BASE_URL
from .exceptions import AuditApiError

# Maximum time window the API allows per request.
_MAX_WINDOW_HOURS = 24
# Time format the API expects.
_TIME_FORMAT = "%Y-%m-%dT%H:%M:%S"

# Outlook-only content feed for canary monitoring.
CONTENT_TYPES = ("Audit.Exchange",)


class AuditClient:
    """Thin REST client wrapping the Office 365 Management Activity API."""

    def __init__(
        self,
        access_token: str,
        tenant_id: str,
        *,
        base_url: str = MANAGEMENT_API_BASE_URL,
        retries: int = 3,
        timeout: int = 30,
        session: requests.Session | None = None,
    ):
        self.base_url = base_url.rstrip("/")
        self.tenant_id = tenant_id
        self.retries = max(retries, 1)
        self.timeout = timeout
        self.session = session or requests.Session()
        self.session.headers.update(
            {
                "Authorization": f"Bearer {access_token}",
                "Accept": "application/json",
            }
        )

    # ------------------------------------------------------------------
    # Subscriptions
    # ------------------------------------------------------------------

    def ensure_subscriptions(self, content_types: list[str] | None = None) -> list[dict]:
        """Ensure subscriptions are active for the given content types.

        Lists current subscriptions, starts any that are not active.
        Returns the list of active subscription dicts.
        """
        types = content_types or list(CONTENT_TYPES)

        # List current subscriptions.
        current = self._get(f"/{self.tenant_id}/activity/feed/subscriptions/list")
        if not isinstance(current, list):
            current = current.get("value", []) if isinstance(current, dict) else []

        active_types: set[str] = set()
        results: list[dict] = []
        for sub in current:
            if isinstance(sub, dict) and sub.get("status") == "enabled":
                active_types.add(sub.get("contentType", ""))
                results.append(sub)

        for ct in types:
            if ct not in active_types:
                sub = self._post(
                    f"/{self.tenant_id}/activity/feed/subscriptions/start",
                    params={"contentType": ct},
                )
                results.append(sub)

        return results

    # ------------------------------------------------------------------
    # Content listing
    # ------------------------------------------------------------------

    def list_content(
        self,
        content_type: str,
        start_time: datetime,
        end_time: datetime,
    ) -> list[dict]:
        """List available content blobs for a content type and time window.

        Follows ``NextPageUri`` pagination automatically.
        Returns a list of content blob metadata dicts.
        """
        start_str = start_time.astimezone(timezone.utc).strftime(_TIME_FORMAT)
        end_str = end_time.astimezone(timezone.utc).strftime(_TIME_FORMAT)

        blobs: list[dict] = []
        url: str | None = None
        path = f"/{self.tenant_id}/activity/feed/subscriptions/content"
        params: dict[str, str] = {
            "contentType": content_type,
            "startTime": start_str,
            "endTime": end_str,
        }

        while True:
            if url:
                # Pagination: follow NextPageUri (absolute URL).
                _validate_management_api_url(url, base_url=self.base_url)
                result, headers = self._get_with_headers(url, absolute=True)
            else:
                result, headers = self._get_with_headers(path, params=params)

            if isinstance(result, list):
                blobs.extend(result)
            elif isinstance(result, dict):
                blobs.extend(result.get("value", []))

            next_page = headers.get("NextPageUri") or headers.get("nextpageuri")
            if not next_page:
                break
            _validate_management_api_url(next_page, base_url=self.base_url)
            url = next_page

        return blobs

    # ------------------------------------------------------------------
    # Content fetching
    # ------------------------------------------------------------------

    def fetch_content(self, content_uri: str) -> list[dict]:
        """Fetch audit events from a content blob URI.

        The ``content_uri`` is an absolute URL returned by ``list_content``.
        Returns a list of audit event dicts.
        """
        _validate_management_api_url(content_uri, base_url=self.base_url)
        result = self._get(content_uri, absolute=True)
        if isinstance(result, list):
            return result
        if isinstance(result, dict):
            return result.get("value", [])
        return []

    # ------------------------------------------------------------------
    # Internal HTTP helpers
    # ------------------------------------------------------------------

    def _get(
        self,
        path: str,
        params: dict[str, str] | None = None,
        *,
        absolute: bool = False,
    ) -> Any:
        result, _ = self._get_with_headers(path, params=params, absolute=absolute)
        return result

    def _get_with_headers(
        self,
        path: str,
        params: dict[str, str] | None = None,
        *,
        absolute: bool = False,
    ) -> tuple[Any, dict[str, str]]:
        """GET with retry, returning (parsed_body, response_headers)."""
        if absolute:
            url = path
        else:
            url = f"{self.base_url}{path}"

        all_params = {"PublisherIdentifier": self.tenant_id}
        if params:
            all_params.update(params)

        return self._request("GET", url, params=all_params)

    def _post(
        self,
        path: str,
        params: dict[str, str] | None = None,
        json: dict[str, Any] | None = None,
    ) -> dict:
        all_params = {"PublisherIdentifier": self.tenant_id}
        if params:
            all_params.update(params)
        url = f"{self.base_url}{path}"
        body, _ = self._request("POST", url, params=all_params, json=json)
        return body if isinstance(body, dict) else {}

    def _request(
        self,
        method: str,
        url: str,
        **kwargs: Any,
    ) -> tuple[Any, dict[str, str]]:
        """Execute an HTTP request with retry and backoff."""
        for attempt in range(self.retries):
            try:
                response = self.session.request(method, url, timeout=self.timeout, **kwargs)
            except requests.RequestException as exc:
                if attempt < self.retries - 1:
                    time.sleep(_compute_backoff(attempt))
                    continue
                raise AuditApiError(
                    f"Network error calling Management Activity API: {exc}",
                    method=method,
                    url=url,
                ) from exc

            if response.status_code == 429 and attempt < self.retries - 1:
                retry_after = _parse_retry_after(response.headers.get("Retry-After"))
                time.sleep(retry_after)
                continue

            if 500 <= response.status_code <= 599 and attempt < self.retries - 1:
                time.sleep(_compute_backoff(attempt))
                continue

            if not response.ok:
                raise AuditApiError(
                    _extract_error_message(response),
                    status_code=response.status_code,
                    method=method,
                    url=url,
                )

            return _parse_body(response), dict(response.headers)

        raise AuditApiError(
            "Request failed after retries.",
            method=method,
            url=url,
        )


# ------------------------------------------------------------------
# Utility helpers
# ------------------------------------------------------------------


def _compute_backoff(attempt: int, *, max_seconds: int = 8) -> int:
    return min(2**attempt, max_seconds)


def _validate_management_api_url(url: str, *, base_url: str = MANAGEMENT_API_BASE_URL) -> None:
    if _management_api_origin(url) != _management_api_origin(base_url):
        raise AuditApiError(
            "Management Activity API URL must stay on the configured Management API host"
        )


def _management_api_origin(url: str) -> tuple[str, str, int]:
    try:
        parsed = urlparse(url)
        hostname = parsed.hostname
        port = parsed.port if parsed.port is not None else 443
    except ValueError as exc:
        raise AuditApiError("Management Activity API URL is malformed") from exc

    if parsed.scheme != "https":
        raise AuditApiError("Management Activity API URL must use https")
    if not hostname:
        raise AuditApiError("Management Activity API URL must include a host")
    if parsed.username is not None or parsed.password is not None:
        raise AuditApiError("Management Activity API URL must not include credentials")

    return (parsed.scheme, hostname.lower(), port)


def _parse_retry_after(value: str | None) -> int:
    if not value:
        return 1
    try:
        return max(int(value), 1)
    except ValueError:
        return 1


def _extract_error_message(response: requests.Response) -> str:
    try:
        payload = response.json()
    except ValueError:
        return response.text or f"HTTP {response.status_code}"

    if isinstance(payload, dict):
        error = payload.get("error", {})
        if isinstance(error, dict):
            code = error.get("code", "Unknown")
            message = error.get("message", response.text)
            return f"{code}: {message}"
        # Some endpoints return {"Message": "..."}
        msg = payload.get("Message") or payload.get("message")
        if msg:
            return str(msg)

    return response.text or f"HTTP {response.status_code}"


def _parse_body(response: requests.Response) -> Any:
    if response.status_code == 204 or not response.content:
        return {}
    try:
        return response.json()
    except ValueError:
        return {}
