"""Shared HTTP retry/backoff machinery for the Graph and Management API clients."""

from __future__ import annotations

import logging
import time
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Any, Callable

import requests

# A misbehaving server or proxy must not be able to park the client for hours.
_MAX_RETRY_AFTER_SECONDS = 120


def compute_backoff(attempt: int, *, max_seconds: int = 8) -> int:
    return int(min(2**attempt, max_seconds))


def parse_retry_after(value: str | None) -> int:
    if not value:
        return 1
    try:
        return min(max(int(value), 1), _MAX_RETRY_AFTER_SECONDS)
    except ValueError:
        # RFC 7231 also permits an HTTP-date; Microsoft throttling may use either.
        try:
            retry_at = parsedate_to_datetime(value)
            delay = int((retry_at - datetime.now(timezone.utc)).total_seconds())
            return min(max(delay, 1), _MAX_RETRY_AFTER_SECONDS)
        except (TypeError, ValueError):
            return 1


def request_with_retries(
    session: requests.Session,
    method: str,
    url: str,
    *,
    retries: int,
    timeout: int,
    can_retry: bool,
    network_error: Callable[[requests.RequestException], Exception],
    exhausted_error: Callable[[], Exception],
    logger: logging.Logger | None = None,
    **kwargs: Any,
) -> requests.Response:
    """Run the shared retry loop: network errors and 5xx back off
    exponentially, 429 honors Retry-After (numeric or HTTP-date, capped).

    Only retries when *can_retry* is true (idempotent requests). Returns the
    final response — including non-2xx and 3xx — for the caller to interpret;
    raises the caller's domain error for network failures and retry
    exhaustion. Redirects are never followed.
    """
    for attempt in range(retries):
        if logger:
            logger.debug("%s %s", method, url)
        try:
            response = session.request(method, url, timeout=timeout, allow_redirects=False, **kwargs)
        except requests.RequestException as exc:
            if can_retry and attempt < retries - 1:
                time.sleep(compute_backoff(attempt))
                continue
            raise network_error(exc) from exc

        if logger:
            logger.debug("%s %s -> %d", method, url, response.status_code)

        if response.status_code == 429 and can_retry and attempt < retries - 1:
            time.sleep(parse_retry_after(response.headers.get("Retry-After")))
            continue

        if 500 <= response.status_code <= 599 and can_retry and attempt < retries - 1:
            time.sleep(compute_backoff(attempt))
            continue

        return response

    raise exhausted_error()
