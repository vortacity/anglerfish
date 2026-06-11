"""Office 365 Management Activity API client."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlparse

import requests
from requests.structures import CaseInsensitiveDict

from ._http import request_with_retries
from .config import MANAGEMENT_API_BASE_URL
from .exceptions import AuditApiError

# Maximum time window the API allows per request.
_MAX_WINDOW_HOURS = 24
# Time format the API expects.
_TIME_FORMAT = "%Y-%m-%dT%H:%M:%S"

# Outlook-only content feed for canary monitoring.
CONTENT_TYPES = ("Audit.Exchange",)

# Hard cap on pagination depth; a stale or self-referencing NextPageUri must
# not loop or accumulate forever.
_MAX_CONTENT_PAGES = 1000


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

        pages = 0
        while True:
            if url:
                # Pagination: follow NextPageUri (absolute URL).
                _validate_management_api_url(url, base_url=self.base_url)
                result, headers = self._get_with_headers(url, absolute=True)
            else:
                result, headers = self._get_with_headers(path, params=params)
            pages += 1

            if isinstance(result, list):
                blobs.extend(result)
            elif isinstance(result, dict):
                blobs.extend(result.get("value", []))

            next_page = CaseInsensitiveDict(headers).get("NextPageUri")
            if not next_page:
                break
            if next_page == url:
                raise AuditApiError("Content pagination returned a self-referencing NextPageUri")
            if pages >= _MAX_CONTENT_PAGES:
                raise AuditApiError(f"Content pagination exceeded {_MAX_CONTENT_PAGES} pages")
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
            value = result.get("value", [])
            return value if isinstance(value, list) else []
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
            # Absolute URLs (NextPageUri / contentUri) already carry
            # PublisherIdentifier; don't append a duplicate query parameter.
            url = path
            all_params = dict(params) if params else {}
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
        """Execute an HTTP request with retry and backoff.

        Only idempotent reads (GET) auto-retry; the subscription-start POST does
        not, so a transient failure cannot double-execute the write.
        """
        can_retry = method.strip().upper() == "GET"
        response = request_with_retries(
            self.session,
            method,
            url,
            retries=self.retries,
            timeout=self.timeout,
            can_retry=can_retry,
            network_error=lambda exc: AuditApiError(
                f"Network error calling Management Activity API: {exc}",
                method=method,
                url=url,
            ),
            exhausted_error=lambda: AuditApiError(
                "Request failed after retries.",
                method=method,
                url=url,
            ),
            **kwargs,
        )

        # Redirects are disabled; the Management API should not 3xx here.
        if 300 <= response.status_code < 400:
            raise AuditApiError(
                f"Unexpected redirect response (HTTP {response.status_code})",
                status_code=response.status_code,
                method=method,
                url=url,
            )

        if not response.ok:
            raise AuditApiError(
                _extract_error_message(response),
                status_code=response.status_code,
                method=method,
                url=url,
            )

        return _parse_body(response), dict(response.headers)


# ------------------------------------------------------------------
# Utility helpers
# ------------------------------------------------------------------


def _validate_management_api_url(url: str, *, base_url: str = MANAGEMENT_API_BASE_URL) -> None:
    if _management_api_origin(url) != _management_api_origin(base_url):
        raise AuditApiError("Management Activity API URL must stay on the configured Management API host")


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


def _extract_error_message(response: requests.Response) -> str:
    try:
        payload = response.json()
    except ValueError:
        return response.text or f"HTTP {response.status_code}"

    if isinstance(payload, dict):
        error = payload.get("error")
        if isinstance(error, dict):
            code = error.get("code", "Unknown")
            message = error.get("message", response.text)
            return f"{code}: {message}"
        # Some endpoints return {"Message": "..."} with no "error" key.
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
