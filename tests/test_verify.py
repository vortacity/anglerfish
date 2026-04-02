"""Tests for the canary health-check module (verify.py)."""

from __future__ import annotations

from unittest.mock import MagicMock

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
    graph.get.assert_called_once_with("/users/alice%40contoso.com/mailFolders/folder-abc")


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


def test_verify_outlook_send_record_returns_error():
    record = {
        "canary_type": "outlook",
        "delivery_mode": "send",
        "target_user": "alice@contoso.com",
        "inbox_message_id": "msg-123",
    }
    graph = _mock_graph()
    result = verify_record(graph, record)

    assert result.status == VerifyStatus.ERROR
    assert "draft" in result.detail.lower()
    graph.get.assert_not_called()


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


def test_run_verify_returns_results_for_multiple_records():
    from anglerfish.verify import run_verify

    records = [
        (
            "rec1.json",
            {
                "timestamp": "t",
                "canary_type": "outlook",
                "target_user": "a@contoso.com",
                "folder_id": "f1",
                "template_name": "T1",
            },
        ),
        (
            "rec2.json",
            {
                "timestamp": "t",
                "canary_type": "outlook",
                "target_user": "b@contoso.com",
                "folder_id": "f2",
                "template_name": "T2",
            },
        ),
    ]
    graph = _mock_graph()
    results = run_verify(records, graph)

    assert len(results) == 2
    assert all(r.status == VerifyStatus.OK for r in results)


def test_run_verify_mixed_results():
    from anglerfish.verify import run_verify

    records = [
        (
            "ok.json",
            {
                "timestamp": "t",
                "canary_type": "outlook",
                "target_user": "u@contoso.com",
                "folder_id": "f1",
                "template_name": "T1",
            },
        ),
        (
            "gone.json",
            {
                "timestamp": "t",
                "canary_type": "outlook",
                "target_user": "u@contoso.com",
                "folder_id": "f1",
                "template_name": "T2",
            },
        ),
    ]
    graph = MagicMock()
    # First call succeeds, second raises 404.
    graph.get.side_effect = [
        {"id": "ok"},
        GraphApiError("Not found", status_code=404),
    ]
    results = run_verify(records, graph)

    assert results[0].status == VerifyStatus.OK
    assert results[1].status == VerifyStatus.GONE


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
