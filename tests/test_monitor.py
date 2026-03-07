"""Tests for the canary monitoring module (monitor.py)."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

from rich.console import Console

from anglerfish.alerts import AlertDispatcher
from anglerfish.monitor import (
    CanaryAlert,
    CanaryIndex,
    _TokenManager,
    _build_entry,
    _write_heartbeat,
    load_records,
    run_monitor,
)
from anglerfish.state import StateManager


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------


def _outlook_record(**overrides) -> dict:
    base = {
        "timestamp": "2026-03-01T00:00:00Z",
        "canary_type": "outlook",
        "template_name": "Fake Password Reset",
        "target_user": "alice@contoso.com",
        "internet_message_id": "<canary-msg-001@contoso.com>",
        "folder_name": "IT Notifications",
        "folder_id": "folder-abc",
        "subject": "Password Reset Required",
    }
    base.update(overrides)
    return base


def _sharepoint_record(**overrides) -> dict:
    base = {
        "timestamp": "2026-03-01T00:00:00Z",
        "canary_type": "sharepoint",
        "template_name": "Employee Salary Bands",
        "uploaded_files": ["Salary_Bands_2026.txt"],
        "item_id": "item-sp-001",
        "site_web_url": "https://contoso.sharepoint.com/sites/HR",
        "site_name": "HR",
    }
    base.update(overrides)
    return base


def _onedrive_record(**overrides) -> dict:
    base = {
        "timestamp": "2026-03-01T00:00:00Z",
        "canary_type": "onedrive",
        "template_name": "VPN Credentials Backup",
        "target_user": "j.smith@contoso.com",
        "uploaded_files": ["VPN_Config_Backup.txt"],
        "item_id": "item-od-001",
    }
    base.update(overrides)
    return base


# ------------------------------------------------------------------
# CanaryIndex.match — Outlook
# ------------------------------------------------------------------


def test_match_outlook_by_internet_message_id():
    rec = _outlook_record()
    idx = CanaryIndex([("rec.json", rec)])

    event = {
        "Operation": "MailItemsAccessed",
        "UserId": "attacker@evil.com",
        "ClientIP": "203.0.113.42",
        "CreationTime": "2026-03-05T14:00:00",
        "Folders": [
            {
                "Path": "\\IT Notifications",
                "FolderItems": [{"InternetMessageId": "<canary-msg-001@contoso.com>"}],
            }
        ],
    }
    alert = idx.match(event)

    assert alert is not None
    assert isinstance(alert, CanaryAlert)
    assert alert.canary_type == "outlook"
    assert alert.accessed_by == "attacker@evil.com"
    assert "<canary-msg-001@contoso.com>" in alert.artifact_label


def test_match_outlook_by_folder_name_fallback():
    rec = _outlook_record(internet_message_id="")
    idx = CanaryIndex([("rec.json", rec)])

    event = {
        "Operation": "MailItemsAccessed",
        "UserId": "attacker@evil.com",
        "ClientIP": "198.51.100.1",
        "Folders": [{"Path": "\\IT Notifications\\SubFolder"}],
    }
    alert = idx.match(event)

    assert alert is not None
    assert "folder" in alert.artifact_label.lower()


def test_no_match_outlook_wrong_message_id():
    rec = _outlook_record()
    idx = CanaryIndex([("rec.json", rec)])

    event = {
        "Operation": "MailItemsAccessed",
        "Folders": [{"FolderItems": [{"InternetMessageId": "<other-msg@contoso.com>"}]}],
    }
    assert idx.match(event) is None


# ------------------------------------------------------------------
# CanaryIndex.match — SharePoint / OneDrive file events
# ------------------------------------------------------------------


def test_match_sharepoint_by_item_id():
    rec = _sharepoint_record()
    idx = CanaryIndex([("rec.json", rec)])

    event = {
        "Operation": "FileAccessed",
        "OfficeObjectId": "item-sp-001",
        "UserId": "attacker@evil.com",
        "ClientIP": "198.51.100.1",
        "CreationTime": "2026-03-05T14:00:00",
    }
    alert = idx.match(event)

    assert alert is not None
    assert alert.canary_type == "sharepoint"


def test_match_sharepoint_by_filename_and_site():
    rec = _sharepoint_record(item_id="")
    idx = CanaryIndex([("rec.json", rec)])

    event = {
        "Operation": "FileDownloaded",
        "SourceFileName": "Salary_Bands_2026.txt",
        "ObjectId": "https://contoso.sharepoint.com/sites/HR/Shared Documents/Salary_Bands_2026.txt",
        "UserId": "attacker@evil.com",
        "ClientIP": "198.51.100.1",
    }
    alert = idx.match(event)

    assert alert is not None
    assert "file" in alert.artifact_label.lower()


def test_match_onedrive_by_item_id():
    rec = _onedrive_record()
    idx = CanaryIndex([("rec.json", rec)])

    event = {
        "Operation": "FileAccessed",
        "OfficeObjectId": "item-od-001",
        "UserId": "attacker@evil.com",
        "ClientIP": "198.51.100.1",
    }
    alert = idx.match(event)

    assert alert is not None
    assert alert.canary_type == "onedrive"


def test_match_onedrive_by_filename_and_upn():
    rec = _onedrive_record(item_id="")
    idx = CanaryIndex([("rec.json", rec)])

    event = {
        "Operation": "FileAccessed",
        "SourceFileName": "VPN_Config_Backup.txt",
        "ObjectId": "https://contoso-my.sharepoint.com/personal/j_smith_contoso_com/Documents/VPN_Config_Backup.txt",
        "UserId": "attacker@evil.com",
        "ClientIP": "198.51.100.1",
    }
    alert = idx.match(event)

    assert alert is not None


def test_no_match_file_event_wrong_filename():
    rec = _sharepoint_record()
    idx = CanaryIndex([("rec.json", rec)])

    event = {
        "Operation": "FileAccessed",
        "SourceFileName": "Totally_Different_File.txt",
        "ObjectId": "https://other.sharepoint.com/sites/Other/file.txt",
    }
    assert idx.match(event) is None


# ------------------------------------------------------------------
# CanaryIndex.match — exclusion
# ------------------------------------------------------------------


def test_exclude_app_id_skips_matching_event():
    rec = _outlook_record()
    idx = CanaryIndex([("rec.json", rec)])

    event = {
        "Operation": "MailItemsAccessed",
        "AppId": "canary-deployer-app-id",
        "Folders": [{"FolderItems": [{"InternetMessageId": "<canary-msg-001@contoso.com>"}]}],
    }
    alert = idx.match(event, exclude_app_ids={"canary-deployer-app-id"})

    assert alert is None


# ------------------------------------------------------------------
# CanaryIndex.match — unrelated operations
# ------------------------------------------------------------------


def test_unrelated_operation_returns_none():
    rec = _outlook_record()
    idx = CanaryIndex([("rec.json", rec)])

    event = {"Operation": "UserLoggedIn", "UserId": "someone@contoso.com"}

    assert idx.match(event) is None


# ------------------------------------------------------------------
# CanaryIndex.count
# ------------------------------------------------------------------


def test_index_count():
    idx = CanaryIndex(
        [
            ("a.json", _outlook_record()),
            ("b.json", _sharepoint_record()),
        ]
    )
    assert idx.count == 2


# ------------------------------------------------------------------
# _build_entry
# ------------------------------------------------------------------


def test_build_entry_parses_uploaded_files_string():
    rec = {"timestamp": "t", "canary_type": "sharepoint", "uploaded_files": "a.txt, b.txt"}
    entry = _build_entry("rec.json", rec)

    assert entry.uploaded_files == ["a.txt", "b.txt"]


def test_build_entry_parses_uploaded_files_list():
    rec = {"timestamp": "t", "canary_type": "onedrive", "uploaded_files": ["file.docx"]}
    entry = _build_entry("rec.json", rec)

    assert entry.uploaded_files == ["file.docx"]


# ------------------------------------------------------------------
# load_records
# ------------------------------------------------------------------


def test_load_records_from_directory(tmp_path):
    rec = _outlook_record(status="active")
    (tmp_path / "rec1.json").write_text(json.dumps(rec))

    cleaned = _outlook_record(status="cleaned")
    (tmp_path / "rec2.json").write_text(json.dumps(cleaned))

    results = load_records(tmp_path)

    assert len(results) == 1
    assert results[0][1]["canary_type"] == "outlook"


def test_load_records_nonexistent_directory():
    results = load_records("/tmp/nonexistent_dir_xyz_abc")

    assert results == []


# ------------------------------------------------------------------
# run_monitor with StateManager and AlertDispatcher
# ------------------------------------------------------------------


def _mock_audit_client(events=None):
    """Return a mock AuditClient that yields the given events."""
    client = MagicMock()
    client.tenant_id = "test-tenant"
    client.base_url = "https://manage.office.com/api/v1.0"
    client.retries = 3
    client.timeout = 30
    client.ensure_subscriptions.return_value = []
    if events is None:
        events = []
    client.list_content.return_value = [{"contentUri": "https://example.com/content/1"}]
    client.fetch_content.return_value = events
    return client


def test_run_monitor_once_with_state_and_dispatcher(tmp_path):
    """run_monitor --once persists state and dispatches alerts."""
    state_path = tmp_path / "state.json"
    log_path = tmp_path / "alerts.jsonl"
    heartbeat_path = tmp_path / "heartbeat.json"

    event = {
        "Id": "evt-100",
        "Operation": "MailItemsAccessed",
        "UserId": "attacker@evil.com",
        "ClientIP": "203.0.113.42",
        "CreationTime": "2026-03-05T14:00:00",
        "Folders": [
            {
                "Path": "\\IT Notifications",
                "FolderItems": [{"InternetMessageId": "<canary-msg-001@contoso.com>"}],
            }
        ],
    }

    client = _mock_audit_client([event])
    idx = CanaryIndex([("rec.json", _outlook_record())])
    sm = StateManager(state_path)
    dispatcher = AlertDispatcher(alert_log=log_path)
    console = Console(file=None, force_terminal=False)

    rc = run_monitor(
        client,
        idx,
        once=True,
        console=console,
        state_manager=sm,
        dispatcher=dispatcher,
        heartbeat_path=heartbeat_path,
    )

    assert rc == 0

    # State was persisted.
    assert state_path.is_file()
    state_data = json.loads(state_path.read_text())
    assert state_data["total_polls"] == 1
    assert state_data["total_alerts"] >= 1
    assert "evt-100" in state_data["seen_ids"]

    # Alert was logged.
    assert log_path.is_file()
    alert_record = json.loads(log_path.read_text().strip().split("\n")[0])
    assert alert_record["accessed_by"] == "attacker@evil.com"

    # Heartbeat was written.
    assert heartbeat_path.is_file()
    hb = json.loads(heartbeat_path.read_text())
    assert hb["status"] == "healthy"


def test_run_monitor_deduplicates_across_runs(tmp_path):
    """Running --once twice with the same event should only alert once."""
    state_path = tmp_path / "state.json"
    log_path = tmp_path / "alerts.jsonl"

    event = {
        "Id": "evt-dedup",
        "Operation": "FileAccessed",
        "OfficeObjectId": "item-sp-001",
        "UserId": "attacker@evil.com",
        "ClientIP": "198.51.100.1",
    }

    idx = CanaryIndex([("rec.json", _sharepoint_record())])
    console = Console(file=None, force_terminal=False)

    # First run.
    client1 = _mock_audit_client([event])
    sm1 = StateManager(state_path)
    d1 = AlertDispatcher(alert_log=log_path)
    run_monitor(client1, idx, once=True, console=console, state_manager=sm1, dispatcher=d1, heartbeat_path=None)

    # Second run (new state manager reads from disk).
    client2 = _mock_audit_client([event])
    sm2 = StateManager(state_path)
    d2 = AlertDispatcher(alert_log=log_path)
    run_monitor(client2, idx, once=True, console=console, state_manager=sm2, dispatcher=d2, heartbeat_path=None)

    lines = log_path.read_text().strip().split("\n")
    assert len(lines) == 1, f"Expected 1 alert but got {len(lines)}"


# ------------------------------------------------------------------
# Token refresh
# ------------------------------------------------------------------


def test_token_manager_refreshes_when_near_expiry():
    """_TokenManager should re-acquire token when close to expiry."""
    mgr = _TokenManager("initial-token")
    # Simulate token near expiry.
    mgr._expires_at = datetime.now(timezone.utc) - timedelta(minutes=1)

    with patch("anglerfish.monitor.authenticate_management_api", return_value="new-token"):
        token = mgr.get_token()

    assert token == "new-token"


def test_token_manager_returns_cached_when_valid():
    mgr = _TokenManager("cached-token")
    assert mgr.get_token() == "cached-token"


# ------------------------------------------------------------------
# Heartbeat
# ------------------------------------------------------------------


def test_write_heartbeat(tmp_path):
    hb_path = tmp_path / "heartbeat.json"
    _write_heartbeat(hb_path, canary_count=5, session_alerts=2)

    assert hb_path.is_file()
    data = json.loads(hb_path.read_text())
    assert data["canaries"] == 5
    assert data["alerts_this_session"] == 2
    assert data["status"] == "healthy"
