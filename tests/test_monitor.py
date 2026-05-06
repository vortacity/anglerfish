"""Tests for the canary monitoring module (monitor.py)."""

from __future__ import annotations

import json
import os
import stat
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


def _mail_items_accessed_event(**overrides) -> dict:
    base = {
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
    base.update(overrides)
    return base


# ------------------------------------------------------------------
# CanaryIndex.match — Outlook only
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


def test_file_events_are_ignored_in_outlook_only_mode():
    rec = {
        "timestamp": "2026-03-01T00:00:00Z",
        "canary_type": "sharepoint",
        "template_name": "Employee Salary Bands",
        "item_id": "item-sp-001",
    }
    idx = CanaryIndex([("rec.json", rec)])

    event = {
        "Operation": "FileAccessed",
        "OfficeObjectId": "item-sp-001",
        "UserId": "attacker@evil.com",
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


def test_cleaned_index_entry_matches_until_expiry(tmp_path):
    now = datetime(2026, 5, 6, 12, 0, tzinfo=timezone.utc)
    rec = _outlook_record(
        status="cleaned_up",
        status_updated_at=(now - timedelta(hours=2)).isoformat(),
    )
    (tmp_path / "rec.json").write_text(json.dumps(rec), encoding="utf-8")

    records = load_records(tmp_path, cleaned_up_lookback=timedelta(hours=24), now=now)
    idx = CanaryIndex(records)
    event = _mail_items_accessed_event()
    expires_at = now + timedelta(hours=22)

    assert idx.match(event, now=expires_at - timedelta(microseconds=1)) is not None
    assert idx.match(event, now=expires_at) is not None
    assert idx.match(event, now=expires_at + timedelta(microseconds=1)) is None


def test_cleaned_index_entry_folder_fallback_matches_until_expiry(tmp_path):
    now = datetime(2026, 5, 6, 12, 0, tzinfo=timezone.utc)
    rec = _outlook_record(
        internet_message_id="",
        status="cleaned_up",
        status_updated_at=(now - timedelta(hours=2)).isoformat(),
    )
    (tmp_path / "rec.json").write_text(json.dumps(rec), encoding="utf-8")

    records = load_records(tmp_path, cleaned_up_lookback=timedelta(hours=24), now=now)
    idx = CanaryIndex(records)
    event = _mail_items_accessed_event(
        Folders=[{"Path": "\\Mailbox\\IT Notifications\\SubFolder"}],
    )
    expires_at = now + timedelta(hours=22)

    assert idx.match(event, now=expires_at - timedelta(microseconds=1)) is not None
    assert idx.match(event, now=expires_at) is not None
    assert idx.match(event, now=expires_at + timedelta(microseconds=1)) is None


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
            ("b.json", _outlook_record(internet_message_id="<canary-msg-002@contoso.com>")),
        ]
    )
    assert idx.count == 2


# ------------------------------------------------------------------
# _build_entry
# ------------------------------------------------------------------


def test_build_entry_sets_outlook_fields():
    rec = {
        "timestamp": "t",
        "canary_type": "outlook",
        "internet_message_id": "<m1@contoso.com>",
        "folder_name": "Inbox/IT Notifications",
    }
    entry = _build_entry("rec.json", rec)

    assert entry.internet_message_id == "<m1@contoso.com>"
    assert entry.folder_name == "Inbox/IT Notifications"


def test_build_entry_defaults_missing_outlook_fields_to_empty_strings():
    rec = {"timestamp": "t", "canary_type": "outlook"}
    entry = _build_entry("rec.json", rec)

    assert entry.internet_message_id == ""
    assert entry.folder_name == ""
    assert entry.expires_at is None


# ------------------------------------------------------------------
# load_records
# ------------------------------------------------------------------


def test_load_records_from_directory(tmp_path):
    rec = _outlook_record(status="active")
    (tmp_path / "rec1.json").write_text(json.dumps(rec))

    cleaned = _outlook_record(status="cleaned")
    (tmp_path / "rec2.json").write_text(json.dumps(cleaned))

    legacy = {
        "timestamp": "2026-03-01T00:00:00Z",
        "canary_type": "sharepoint",
        "template_name": "Legacy File Canary",
        "status": "active",
    }
    (tmp_path / "rec3.json").write_text(json.dumps(legacy))

    results = load_records(tmp_path)

    assert len(results) == 1
    assert results[0][1]["canary_type"] == "outlook"


def test_load_records_includes_recently_cleaned_outlook_records(tmp_path):
    now = datetime(2026, 5, 6, 12, 0, tzinfo=timezone.utc)
    rec = _outlook_record(
        status="cleaned_up",
        status_updated_at=(now - timedelta(hours=2)).isoformat(),
    )
    (tmp_path / "rec.json").write_text(json.dumps(rec), encoding="utf-8")

    results = load_records(tmp_path, cleaned_up_lookback=timedelta(hours=24), now=now)

    assert len(results) == 1


def test_load_records_includes_cleaned_record_at_exact_lookback(tmp_path):
    now = datetime(2026, 5, 6, 12, 0, tzinfo=timezone.utc)
    rec = _outlook_record(
        status="cleaned_up",
        status_updated_at=(now - timedelta(hours=24)).isoformat(),
    )
    (tmp_path / "rec.json").write_text(json.dumps(rec), encoding="utf-8")

    results = load_records(tmp_path, cleaned_up_lookback=timedelta(hours=24), now=now)

    assert len(results) == 1


def test_load_records_skips_old_cleaned_outlook_records(tmp_path):
    now = datetime(2026, 5, 6, 12, 0, tzinfo=timezone.utc)
    rec = _outlook_record(
        status="cleaned_up",
        status_updated_at=(now - timedelta(hours=25)).isoformat(),
    )
    (tmp_path / "rec.json").write_text(json.dumps(rec), encoding="utf-8")

    results = load_records(tmp_path, cleaned_up_lookback=timedelta(hours=24), now=now)

    assert results == []


def test_load_records_skips_future_cleaned_outlook_records(tmp_path):
    now = datetime(2026, 5, 6, 12, 0, tzinfo=timezone.utc)
    rec = _outlook_record(
        status="cleaned_up",
        status_updated_at=(now + timedelta(minutes=1)).isoformat(),
    )
    (tmp_path / "rec.json").write_text(json.dumps(rec), encoding="utf-8")

    results = load_records(tmp_path, cleaned_up_lookback=timedelta(hours=24), now=now)

    assert results == []


def test_load_records_zero_cleaned_lookback_includes_exact_timestamp(tmp_path):
    now = datetime(2026, 5, 6, 12, 0, tzinfo=timezone.utc)
    rec = _outlook_record(
        status="cleaned_up",
        status_updated_at=now.isoformat(),
    )
    (tmp_path / "rec.json").write_text(json.dumps(rec), encoding="utf-8")

    results = load_records(tmp_path, cleaned_up_lookback=timedelta(0), now=now)

    assert len(results) == 1


def test_load_records_zero_cleaned_lookback_skips_future_timestamp(tmp_path):
    now = datetime(2026, 5, 6, 12, 0, tzinfo=timezone.utc)
    rec = _outlook_record(
        status="cleaned_up",
        status_updated_at=(now + timedelta(microseconds=1)).isoformat(),
    )
    (tmp_path / "rec.json").write_text(json.dumps(rec), encoding="utf-8")

    results = load_records(tmp_path, cleaned_up_lookback=timedelta(0), now=now)

    assert results == []


def test_load_records_negative_cleaned_lookback_skips_cleaned_records(tmp_path):
    now = datetime(2026, 5, 6, 12, 0, tzinfo=timezone.utc)
    rec = _outlook_record(
        status="cleaned_up",
        status_updated_at=now.isoformat(),
    )
    (tmp_path / "rec.json").write_text(json.dumps(rec), encoding="utf-8")

    results = load_records(tmp_path, cleaned_up_lookback=timedelta(hours=-1), now=now)

    assert results == []


def test_load_records_accepts_cleaned_timestamp_with_trailing_z(tmp_path):
    now = datetime(2026, 5, 6, 12, 0, tzinfo=timezone.utc)
    rec = _outlook_record(
        status="cleaned_up",
        status_updated_at="2026-05-06T10:00:00Z",
    )
    (tmp_path / "rec.json").write_text(json.dumps(rec), encoding="utf-8")

    results = load_records(tmp_path, cleaned_up_lookback=timedelta(hours=24), now=now)

    assert len(results) == 1


def test_load_records_adds_internal_expiry_to_cleaned_record(tmp_path):
    now = datetime(2026, 5, 6, 12, 0, tzinfo=timezone.utc)
    rec = _outlook_record(
        status="cleaned_up",
        status_updated_at=(now - timedelta(hours=2)).isoformat(),
    )
    (tmp_path / "rec.json").write_text(json.dumps(rec), encoding="utf-8")

    results = load_records(tmp_path, cleaned_up_lookback=timedelta(hours=24), now=now)

    assert results[0][1]["_monitor_expires_at"] == (now + timedelta(hours=22)).isoformat()
    assert "_monitor_expires_at" not in json.loads((tmp_path / "rec.json").read_text(encoding="utf-8"))


def test_load_records_treats_naive_cleaned_timestamp_as_utc(tmp_path):
    now = datetime(2026, 5, 6, 12, 0, tzinfo=timezone.utc)
    rec = _outlook_record(
        status="cleaned_up",
        status_updated_at="2026-05-06T10:00:00",
    )
    (tmp_path / "rec.json").write_text(json.dumps(rec), encoding="utf-8")

    results = load_records(tmp_path, cleaned_up_lookback=timedelta(hours=24), now=now)

    assert len(results) == 1


def test_load_records_skips_cleaned_record_with_invalid_status_updated_at(tmp_path):
    now = datetime(2026, 5, 6, 12, 0, tzinfo=timezone.utc)
    rec = _outlook_record(
        status="cleaned_up",
        status_updated_at="not-a-timestamp",
    )
    (tmp_path / "rec.json").write_text(json.dumps(rec), encoding="utf-8")

    results = load_records(tmp_path, cleaned_up_lookback=timedelta(hours=24), now=now)

    assert results == []


def test_load_records_skips_cleaned_record_missing_status_updated_at(tmp_path):
    now = datetime(2026, 5, 6, 12, 0, tzinfo=timezone.utc)
    rec = _outlook_record(status="cleaned_up")
    (tmp_path / "rec.json").write_text(json.dumps(rec), encoding="utf-8")

    results = load_records(tmp_path, cleaned_up_lookback=timedelta(hours=24), now=now)

    assert results == []


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
    client.ensure_subscriptions.assert_called_once_with(["Audit.Exchange"])

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
        "Operation": "MailItemsAccessed",
        "Folders": [{"FolderItems": [{"InternetMessageId": "<canary-msg-001@contoso.com>"}]}],
        "UserId": "attacker@evil.com",
        "ClientIP": "198.51.100.1",
    }

    idx = CanaryIndex([("rec.json", _outlook_record())])
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


def test_run_monitor_passes_poll_now_to_canary_index_match(tmp_path):
    heartbeat_path = tmp_path / "heartbeat.json"
    event = _mail_items_accessed_event(Id="evt-now")
    client = _mock_audit_client([event])
    canary_index = MagicMock()
    canary_index.count = 1
    canary_index.match.return_value = None
    console = Console(file=None, force_terminal=False)

    rc = run_monitor(client, canary_index, once=True, console=console, heartbeat_path=heartbeat_path)

    assert rc == 0
    assert canary_index.match.call_count == 1
    matched_event = canary_index.match.call_args.args[0]
    match_kwargs = canary_index.match.call_args.kwargs
    assert matched_event == event
    assert match_kwargs["now"].tzinfo is not None


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


def test_token_manager_temporarily_restores_prompted_env(monkeypatch):
    monkeypatch.delenv("ANGLERFISH_CLIENT_SECRET", raising=False)
    mgr = _TokenManager(
        "initial-token",
        "secret",
        prompted_env={"ANGLERFISH_CLIENT_SECRET": "prompted-secret"},
    )
    mgr._expires_at = datetime.now(timezone.utc) - timedelta(minutes=1)

    def _fake_authenticate(mode):
        assert mode == "secret"
        assert os.environ.get("ANGLERFISH_CLIENT_SECRET") == "prompted-secret"
        return "new-token"

    with patch("anglerfish.monitor.authenticate_management_api", side_effect=_fake_authenticate):
        assert mgr.get_token() == "new-token"

    assert "ANGLERFISH_CLIENT_SECRET" not in os.environ


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
    assert stat.S_IMODE(hb_path.stat().st_mode) == 0o600
