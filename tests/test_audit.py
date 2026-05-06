"""Tests for the Office 365 Management Activity API client (audit module)."""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest
import requests

from anglerfish.audit import CONTENT_TYPES, AuditClient, _compute_backoff, _parse_retry_after
from anglerfish.exceptions import AuditApiError


# ------------------------------------------------------------------
# Stub response helpers
# ------------------------------------------------------------------


def _response(status: int = 200, json_data=None, headers=None, text: str = "") -> MagicMock:
    resp = MagicMock(spec=requests.Response)
    resp.status_code = status
    resp.ok = 200 <= status < 300
    resp.headers = headers or {}
    resp.text = text
    resp.content = b"x" if json_data is not None or text else b""
    resp.json.return_value = json_data if json_data is not None else {}
    return resp


def _session(*responses: MagicMock) -> MagicMock:
    sess = MagicMock(spec=requests.Session)
    sess.headers = {}
    sess.request = MagicMock(side_effect=list(responses))
    return sess


def _client(session: MagicMock, **kwargs) -> AuditClient:
    return AuditClient(
        access_token="fake-token",
        tenant_id="tenant-123",
        session=session,
        **kwargs,
    )


# ------------------------------------------------------------------
# ensure_subscriptions
# ------------------------------------------------------------------


def test_content_types_outlook_only():
    assert CONTENT_TYPES == ("Audit.Exchange",)


def test_ensure_subscriptions_starts_missing_types():
    current = [
        {"contentType": "Audit.Exchange", "status": "enabled"},
    ]
    started_sub = {"contentType": "Audit.SharePoint", "status": "enabled"}
    sess = _session(
        _response(json_data=current),  # list
        _response(json_data=started_sub),  # start SharePoint
        _response(json_data={"contentType": "Audit.General", "status": "enabled"}),  # start General
    )
    client = _client(sess)

    result = client.ensure_subscriptions(["Audit.Exchange", "Audit.SharePoint", "Audit.General"])

    assert len(result) == 3


def test_ensure_subscriptions_all_already_active():
    current = [
        {"contentType": "Audit.Exchange", "status": "enabled"},
        {"contentType": "Audit.SharePoint", "status": "enabled"},
    ]
    sess = _session(_response(json_data=current))
    client = _client(sess)

    result = client.ensure_subscriptions(["Audit.Exchange", "Audit.SharePoint"])

    assert len(result) == 2
    assert sess.request.call_count == 1  # only list, no start calls


# ------------------------------------------------------------------
# list_content
# ------------------------------------------------------------------


def test_list_content_returns_blobs():
    blobs = [
        {"contentUri": "https://manage.office.com/api/v1.0/tenant-123/content/blob1"},
        {"contentUri": "https://manage.office.com/api/v1.0/tenant-123/content/blob2"},
    ]
    sess = _session(_response(json_data=blobs))
    client = _client(sess)

    result = client.list_content(
        "Audit.Exchange",
        datetime(2026, 3, 1, tzinfo=timezone.utc),
        datetime(2026, 3, 2, tzinfo=timezone.utc),
    )

    assert len(result) == 2
    assert result[0]["contentUri"] == "https://manage.office.com/api/v1.0/tenant-123/content/blob1"


def test_list_content_follows_pagination():
    page1 = [{"contentUri": "https://manage.office.com/api/v1.0/tenant-123/content/blob1"}]
    page2 = [{"contentUri": "https://manage.office.com/api/v1.0/tenant-123/content/blob2"}]
    sess = _session(
        _response(json_data=page1, headers={"NextPageUri": "https://manage.office.com/api/v1.0/page2"}),
        _response(json_data=page2),
    )
    client = _client(sess)

    result = client.list_content(
        "Audit.SharePoint",
        datetime(2026, 3, 1, tzinfo=timezone.utc),
        datetime(2026, 3, 2, tzinfo=timezone.utc),
    )

    assert len(result) == 2


def test_list_content_rejects_non_manage_office_next_page_url():
    page1 = [{"contentUri": "https://manage.office.com/api/v1.0/tenant-123/content/blob1"}]
    sess = _session(
        _response(json_data=page1, headers={"NextPageUri": "https://evil.example/page2"}),
    )
    client = _client(sess)

    with pytest.raises(AuditApiError, match="Management Activity API URL"):
        client.list_content(
            "Audit.Exchange",
            datetime(2026, 3, 1, tzinfo=timezone.utc),
            datetime(2026, 3, 2, tzinfo=timezone.utc),
        )


def test_list_content_handles_dict_response_with_value_key():
    body = {"value": [{"contentUri": "https://manage.office.com/api/v1.0/tenant-123/content/blob1"}]}
    sess = _session(_response(json_data=body))
    client = _client(sess)

    result = client.list_content(
        "Audit.General",
        datetime(2026, 3, 1, tzinfo=timezone.utc),
        datetime(2026, 3, 2, tzinfo=timezone.utc),
    )

    assert len(result) == 1


# ------------------------------------------------------------------
# fetch_content
# ------------------------------------------------------------------


def test_fetch_content_returns_events():
    events = [{"Id": "evt-1", "Operation": "MailItemsAccessed"}]
    sess = _session(_response(json_data=events))
    client = _client(sess)

    result = client.fetch_content("https://manage.office.com/api/v1.0/tenant-123/content/blob1")

    assert len(result) == 1
    assert result[0]["Operation"] == "MailItemsAccessed"


def test_fetch_content_handles_dict_with_value():
    body = {"value": [{"Id": "evt-1"}]}
    sess = _session(_response(json_data=body))
    client = _client(sess)

    result = client.fetch_content("https://manage.office.com/api/v1.0/tenant-123/content/blob1")

    assert len(result) == 1


def test_fetch_content_rejects_non_manage_office_url():
    client = AuditClient("token", "tenant-id")

    with pytest.raises(AuditApiError, match="Management Activity API URL"):
        client.fetch_content("https://evil.example/content")


def test_fetch_content_rejects_prefix_trick_url():
    client = AuditClient("token", "tenant-id")

    with pytest.raises(AuditApiError, match="Management Activity API URL"):
        client.fetch_content("https://manage.office.com.evil.example/content")


def test_fetch_content_accepts_configured_government_host():
    sess = _session(_response(json_data=[{"Id": "evt-1"}]))
    client = _client(sess, base_url="https://manage.office365.us/api/v1.0")

    result = client.fetch_content("https://manage.office365.us/api/v1.0/tenant-123/content/blob")

    assert result == [{"Id": "evt-1"}]


def test_fetch_content_rejects_schemeless_url():
    client = AuditClient("token", "tenant-id")

    with pytest.raises(AuditApiError, match="Management Activity API URL"):
        client.fetch_content("//manage.office.com/api/v1.0/tenant-123/content/blob")


# ------------------------------------------------------------------
# Retry and error handling
# ------------------------------------------------------------------


def test_retry_on_429():
    sess = _session(
        _response(status=429, headers={"Retry-After": "0"}),
        _response(json_data={"ok": True}),
    )
    client = _client(sess, retries=2)

    result = client.fetch_content("https://manage.office.com/api/v1.0/tenant-123/content/blob")

    assert result == []  # {"ok": True} is a dict without "value"
    assert sess.request.call_count == 2


def test_retry_on_500():
    sess = _session(
        _response(status=500, text="Internal Server Error"),
        _response(json_data=[{"Id": "evt-1"}]),
    )
    client = _client(sess, retries=2)

    result = client.fetch_content("https://manage.office.com/api/v1.0/tenant-123/content/blob")

    assert len(result) == 1


def test_raises_audit_api_error_on_non_retryable_failure():
    sess = _session(_response(status=403, text="Forbidden"))
    client = _client(sess)

    with pytest.raises(AuditApiError) as exc_info:
        client.fetch_content("https://manage.office.com/api/v1.0/tenant-123/content/blob")

    assert exc_info.value.status_code == 403


def test_raises_audit_api_error_on_network_failure():
    sess = MagicMock(spec=requests.Session)
    sess.headers = {}
    sess.request = MagicMock(side_effect=requests.ConnectionError("fail"))
    client = _client(sess, retries=1)

    with pytest.raises(AuditApiError, match="Network error"):
        client.fetch_content("https://manage.office.com/api/v1.0/tenant-123/content/blob")


def test_error_message_extracts_json_error():
    body = {"error": {"code": "AF20024", "message": "Subscription not found"}}
    sess = _session(_response(status=404, json_data=body, text="Not Found"))
    client = _client(sess)

    with pytest.raises(AuditApiError, match="AF20024"):
        client.fetch_content("https://manage.office.com/api/v1.0/tenant-123/content/blob")


# ------------------------------------------------------------------
# Utility helpers
# ------------------------------------------------------------------


def test_compute_backoff():
    assert _compute_backoff(0) == 1
    assert _compute_backoff(1) == 2
    assert _compute_backoff(2) == 4
    assert _compute_backoff(3) == 8
    assert _compute_backoff(10) == 8  # clamped


def test_parse_retry_after():
    assert _parse_retry_after(None) == 1
    assert _parse_retry_after("") == 1
    assert _parse_retry_after("5") == 5
    assert _parse_retry_after("0") == 1
    assert _parse_retry_after("not-a-number") == 1
