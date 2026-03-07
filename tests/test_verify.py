"""Tests for the canary health-check module (verify.py)."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from anglerfish.exceptions import GraphApiError
from anglerfish.verify import VerifyStatus, verify_record


def _mock_graph(status_code=200, side_effect=None):
    """Return a mock GraphClient."""
    client = MagicMock()
    if side_effect:
        client.get.side_effect = side_effect
    else:
        client.get.return_value = {"id": "some-id"}
    return client


# ------------------------------------------------------------------
# Outlook
# ------------------------------------------------------------------


def test_verify_outlook_ok():
    record = {
        "timestamp": "2026-03-01T00:00:00Z",
        "canary_type": "outlook",
        "target_user": "alice@contoso.com",
        "folder_id": "folder-abc",
        "template_name": "Fake Password Reset",
    }
    graph = _mock_graph()
    result = verify_record(graph, record)

    assert result.status == VerifyStatus.OK
    assert result.canary_type == "outlook"
    graph.get.assert_called_once_with("/users/alice@contoso.com/mailFolders/folder-abc")


def test_verify_outlook_gone():
    record = {
        "timestamp": "2026-03-01T00:00:00Z",
        "canary_type": "outlook",
        "target_user": "alice@contoso.com",
        "folder_id": "folder-abc",
        "template_name": "Fake Password Reset",
    }
    graph = _mock_graph(side_effect=GraphApiError("Not found", status_code=404))
    result = verify_record(graph, record)

    assert result.status == VerifyStatus.GONE


# ------------------------------------------------------------------
# SharePoint
# ------------------------------------------------------------------


def test_verify_sharepoint_ok():
    record = {
        "timestamp": "2026-03-01T00:00:00Z",
        "canary_type": "sharepoint",
        "site_id": "contoso.sharepoint.com,abc,def",
        "item_id": "item-sp-001",
        "template_name": "Employee Salary Bands",
    }
    graph = _mock_graph()
    result = verify_record(graph, record)

    assert result.status == VerifyStatus.OK
    graph.get.assert_called_once_with("/sites/contoso.sharepoint.com,abc,def/drive/items/item-sp-001")


def test_verify_sharepoint_gone():
    record = {
        "timestamp": "2026-03-01T00:00:00Z",
        "canary_type": "sharepoint",
        "site_id": "contoso.sharepoint.com,abc,def",
        "item_id": "item-sp-001",
        "template_name": "Employee Salary Bands",
    }
    graph = _mock_graph(side_effect=GraphApiError("Not found", status_code=404))
    result = verify_record(graph, record)

    assert result.status == VerifyStatus.GONE


# ------------------------------------------------------------------
# OneDrive
# ------------------------------------------------------------------


def test_verify_onedrive_ok():
    record = {
        "timestamp": "2026-03-01T00:00:00Z",
        "canary_type": "onedrive",
        "target_user": "j.smith@contoso.com",
        "item_id": "item-od-001",
        "template_name": "VPN Credentials Backup",
    }
    graph = _mock_graph()
    result = verify_record(graph, record)

    assert result.status == VerifyStatus.OK
    graph.get.assert_called_once_with("/users/j.smith@contoso.com/drive/items/item-od-001")


def test_verify_onedrive_gone():
    record = {
        "timestamp": "2026-03-01T00:00:00Z",
        "canary_type": "onedrive",
        "target_user": "j.smith@contoso.com",
        "item_id": "item-od-001",
        "template_name": "VPN Credentials Backup",
    }
    graph = _mock_graph(side_effect=GraphApiError("Not found", status_code=404))
    result = verify_record(graph, record)

    assert result.status == VerifyStatus.GONE


# ------------------------------------------------------------------
# Error handling
# ------------------------------------------------------------------


def test_verify_graph_error_returns_error_status():
    record = {
        "timestamp": "2026-03-01T00:00:00Z",
        "canary_type": "outlook",
        "target_user": "alice@contoso.com",
        "folder_id": "folder-abc",
        "template_name": "Fake Password Reset",
    }
    graph = _mock_graph(side_effect=GraphApiError("Server error", status_code=500))
    result = verify_record(graph, record)

    assert result.status == VerifyStatus.ERROR
    assert "500" in result.detail or "Server error" in result.detail


def test_verify_unknown_canary_type():
    record = {
        "timestamp": "2026-03-01T00:00:00Z",
        "canary_type": "unknown_type",
        "template_name": "Something",
    }
    graph = _mock_graph()
    result = verify_record(graph, record)

    assert result.status == VerifyStatus.ERROR
    assert "unsupported" in result.detail.lower() or "unknown" in result.detail.lower()


def test_verify_missing_required_field():
    record = {
        "timestamp": "2026-03-01T00:00:00Z",
        "canary_type": "outlook",
        "template_name": "Fake Password Reset",
        # Missing target_user and folder_id
    }
    graph = _mock_graph()
    result = verify_record(graph, record)

    assert result.status == VerifyStatus.ERROR
