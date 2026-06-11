"""Tests for the canary monitoring module (monitor.py)."""

from __future__ import annotations

import json
import os
import stat
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

from rich.console import Console

from anglerfish.alerts import AlertDispatcher
from anglerfish.auth import AuthConfig
from anglerfish.deployers.outlook import _build_entry
from anglerfish.inventory import DeploymentRecord
from anglerfish.monitor import (
    CanaryAlert,
    CanaryIndex,
    _TokenManager,
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


def test_no_match_outlook_by_folder_name_without_canary_id():
    rec = _outlook_record(internet_message_id="")
    idx = CanaryIndex([("rec.json", rec)])

    event = {
        "Operation": "MailItemsAccessed",
        "UserId": "attacker@evil.com",
        "ClientIP": "198.51.100.1",
        "Folders": [{"Path": "\\IT Notifications\\SubFolder"}],
    }
    alert = idx.match(event)

    assert alert is None


def test_match_outlook_by_folder_id_fallback():
    rec = _outlook_record(internet_message_id="", folder_id="folder-abc")
    idx = CanaryIndex([("rec.json", rec)])

    event = {
        "Operation": "MailItemsAccessed",
        "UserId": "attacker@evil.com",
        "Folders": [{"Id": "folder-abc", "Path": "\\Other Folder"}],
    }
    alert = idx.match(event)

    assert alert is not None
    assert "folder_id" in alert.artifact_label


def test_match_outlook_by_unique_folder_name_fallback():
    rec = _outlook_record(
        internet_message_id="",
        canary_id="af-test-001",
        folder_name="IT Notifications - af-test-001",
    )
    idx = CanaryIndex([("rec.json", rec)])

    event = {
        "Operation": "MailItemsAccessed",
        "UserId": "attacker@evil.com",
        "Folders": [{"Path": "\\Mailbox\\IT Notifications - af-test-001"}],
    }
    alert = idx.match(event)

    assert alert is not None
    assert "folder:" in alert.artifact_label.lower()


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
        canary_id="af-test-clean",
        folder_name="IT Notifications - af-test-clean",
        status="cleaned_up",
        status_updated_at=(now - timedelta(hours=2)).isoformat(),
    )
    (tmp_path / "rec.json").write_text(json.dumps(rec), encoding="utf-8")

    records = load_records(tmp_path, cleaned_up_lookback=timedelta(hours=24), now=now)
    idx = CanaryIndex(records)
    event = _mail_items_accessed_event(
        Folders=[{"Path": "\\Mailbox\\IT Notifications - af-test-clean\\SubFolder"}],
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
        "canary_id": "af-test-001",
    }
    entry = _build_entry("rec.json", DeploymentRecord.from_dict(rec))

    assert entry.internet_message_id == "<m1@contoso.com>"
    assert entry.folder_name == "Inbox/IT Notifications"
    assert entry.canary_id == "af-test-001"


def test_build_entry_defaults_missing_outlook_fields_to_empty_strings():
    rec = {"timestamp": "t", "canary_type": "outlook"}
    entry = _build_entry("rec.json", DeploymentRecord.from_dict(rec))

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
    assert results[0][1].canary_type == "outlook"


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

    assert results[0][1].monitor_expires_at == now + timedelta(hours=22)
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

    with patch("anglerfish.monitor.authenticate_management_api_with_expiry", return_value=("new-token", 3600)):
        token = mgr.get_token()

    assert token == "new-token"


def test_token_manager_returns_cached_when_valid():
    mgr = _TokenManager("cached-token")
    assert mgr.get_token() == "cached-token"


def test_token_manager_refreshes_with_auth_config_not_env(monkeypatch):
    monkeypatch.delenv("ANGLERFISH_CLIENT_SECRET", raising=False)
    config = AuthConfig(credential_mode="secret", client_secret="prompted-secret")
    mgr = _TokenManager("initial-token", "secret", auth_config=config)
    mgr._expires_at = datetime.now(timezone.utc) - timedelta(minutes=1)

    def _fake_authenticate(mode, *, auth_config=None):
        assert mode == "secret"
        # The prompted secret arrives by value; the environment is untouched.
        assert auth_config is config
        assert "ANGLERFISH_CLIENT_SECRET" not in os.environ
        return ("new-token", 3600)

    with patch("anglerfish.monitor.authenticate_management_api_with_expiry", side_effect=_fake_authenticate):
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


# ------------------------------------------------------------------
# Watermark advancement on partial failure (regression)
# ------------------------------------------------------------------


def test_run_monitor_does_not_advance_watermark_on_fetch_failure(tmp_path):
    """A failed audit fetch must NOT advance the poll watermark, or events are lost."""
    state_path = tmp_path / "state.json"
    fixed = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
    state_path.write_text(
        json.dumps(
            {
                "last_poll_end": fixed,
                "seen_ids": [],
                "total_alerts": 0,
                "total_polls": 0,
                "started_at": fixed,
            }
        )
    )

    client = _mock_audit_client([])
    client.list_content.side_effect = RuntimeError("audit API unavailable")
    idx = CanaryIndex([("rec.json", _outlook_record())])
    sm = StateManager(state_path)
    console = Console(file=None, force_terminal=False)

    rc = run_monitor(client, idx, once=True, console=console, state_manager=sm, heartbeat_path=None)

    assert rc == 0
    data = json.loads(state_path.read_text())
    assert data["last_poll_end"] == fixed  # unchanged: the failed window will be re-polled


def test_run_monitor_advances_watermark_on_success(tmp_path):
    """A clean poll advances the watermark past the previous value."""
    state_path = tmp_path / "state.json"
    fixed = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
    state_path.write_text(
        json.dumps(
            {
                "last_poll_end": fixed,
                "seen_ids": [],
                "total_alerts": 0,
                "total_polls": 0,
                "started_at": fixed,
            }
        )
    )

    client = _mock_audit_client([])
    idx = CanaryIndex([("rec.json", _outlook_record())])
    sm = StateManager(state_path)
    console = Console(file=None, force_terminal=False)

    rc = run_monitor(client, idx, once=True, console=console, state_manager=sm, heartbeat_path=None)

    assert rc == 0
    data = json.loads(state_path.read_text())
    assert data["last_poll_end"] != fixed  # advanced after a complete window


def test_run_monitor_resumes_from_z_suffix_watermark(tmp_path):
    """A 'Z'-suffixed persisted watermark must resume correctly, including on
    Python 3.10 where datetime.fromisoformat rejects the 'Z' form."""
    state_path = tmp_path / "state.json"
    fixed_dt = datetime.now(timezone.utc) - timedelta(hours=1)
    fixed = fixed_dt.isoformat().replace("+00:00", "Z")
    state_path.write_text(
        json.dumps(
            {
                "last_poll_end": fixed,
                "seen_ids": [],
                "total_alerts": 0,
                "total_polls": 0,
                "started_at": fixed,
            }
        )
    )

    client = _mock_audit_client([])
    idx = CanaryIndex([("rec.json", _outlook_record())])
    sm = StateManager(state_path)
    console = Console(file=None, force_terminal=False)

    rc = run_monitor(client, idx, once=True, console=console, state_manager=sm, heartbeat_path=None)

    assert rc == 0
    # The poll window starts at the persisted watermark, not the 1h fallback.
    assert client.list_content.call_args_list[0].args[1] == fixed_dt


def _write_state(state_path, last_poll_end: datetime) -> None:
    state_path.write_text(
        json.dumps(
            {
                "last_poll_end": last_poll_end.isoformat(),
                "seen_ids": [],
                "total_alerts": 0,
                "total_polls": 0,
                "started_at": last_poll_end.isoformat(),
            }
        )
    )


def test_run_monitor_skips_non_dict_blob_entries(tmp_path):
    """Malformed blob entries from list_content must not crash the poll loop."""
    event = _mail_items_accessed_event(Id="evt-blob-guard")
    client = _mock_audit_client([event])
    client.list_content.return_value = [
        "garbage-string",
        42,
        {"contentUri": "https://example.com/content/1"},
    ]
    idx = CanaryIndex([("rec.json", _outlook_record())])
    console = Console(file=None, force_terminal=False)

    rc = run_monitor(client, idx, once=True, console=console, heartbeat_path=None)

    assert rc == 0
    assert client.fetch_content.call_count == 1


def test_run_monitor_chunks_backlog_into_24h_windows(tmp_path):
    """A backlog longer than 24h is ingested as successive <=24h windows, not skipped."""
    state_path = tmp_path / "state.json"
    backlog_start = datetime.now(timezone.utc) - timedelta(hours=60)
    _write_state(state_path, backlog_start)

    client = _mock_audit_client([])
    idx = CanaryIndex([("rec.json", _outlook_record())])
    sm = StateManager(state_path)
    console = Console(file=None, force_terminal=False)

    rc = run_monitor(client, idx, once=True, console=console, state_manager=sm, heartbeat_path=None)

    assert rc == 0
    calls = client.list_content.call_args_list
    assert len(calls) == 3  # 60h backlog -> 24h + 24h + 12h
    assert calls[0].args[1] == backlog_start
    assert calls[0].args[2] == backlog_start + timedelta(hours=24)
    assert calls[1].args[1] == backlog_start + timedelta(hours=24)
    assert calls[1].args[2] == backlog_start + timedelta(hours=48)
    assert calls[2].args[1] == backlog_start + timedelta(hours=48)
    # Last window ends at "now"; no gap between windows.
    assert (datetime.now(timezone.utc) - calls[2].args[2]).total_seconds() < 60

    data = json.loads(state_path.read_text())
    assert data["last_poll_end"] == calls[2].args[2].isoformat()


def test_run_monitor_backlog_stops_advancing_at_failed_window(tmp_path):
    """If a backlog window fails, the watermark stops at the last complete window."""
    state_path = tmp_path / "state.json"
    backlog_start = datetime.now(timezone.utc) - timedelta(hours=60)
    _write_state(state_path, backlog_start)

    client = _mock_audit_client([])
    client.list_content.side_effect = [[], RuntimeError("audit API unavailable")]
    idx = CanaryIndex([("rec.json", _outlook_record())])
    sm = StateManager(state_path)
    console = Console(file=None, force_terminal=False)

    rc = run_monitor(client, idx, once=True, console=console, state_manager=sm, heartbeat_path=None)

    assert rc == 0
    # Third window is not attempted once the second fails (ordering preserved).
    assert client.list_content.call_count == 2
    data = json.loads(state_path.read_text())
    assert data["last_poll_end"] == (backlog_start + timedelta(hours=24)).isoformat()


def test_run_monitor_clamps_backlog_to_retention_window(tmp_path):
    """A watermark older than the 7-day content retention is clamped, not requested."""
    state_path = tmp_path / "state.json"
    backlog_start = datetime.now(timezone.utc) - timedelta(days=10)
    _write_state(state_path, backlog_start)

    client = _mock_audit_client([])
    idx = CanaryIndex([("rec.json", _outlook_record())])
    sm = StateManager(state_path)
    console = Console(file=None, force_terminal=False)

    rc = run_monitor(client, idx, once=True, console=console, state_manager=sm, heartbeat_path=None)

    assert rc == 0
    calls = client.list_content.call_args_list
    first_start = calls[0].args[1]
    # Clamped to retention, but the whole retained range is still covered.
    assert first_start >= datetime.now(timezone.utc) - timedelta(days=7, minutes=1)
    assert first_start <= datetime.now(timezone.utc) - timedelta(days=7) + timedelta(minutes=1)
    assert len(calls) == 7  # 7 retained days in 24h windows


def test_heartbeat_reports_degraded_when_poll_fails(tmp_path):
    """A poll cycle that could not ingest its window must not report healthy."""
    state_path = tmp_path / "state.json"
    heartbeat_path = tmp_path / "heartbeat.json"
    _write_state(state_path, datetime.now(timezone.utc) - timedelta(hours=1))

    client = _mock_audit_client([])
    client.list_content.side_effect = RuntimeError("audit API unavailable")
    idx = CanaryIndex([("rec.json", _outlook_record())])
    sm = StateManager(state_path)
    console = Console(file=None, force_terminal=False)

    rc = run_monitor(client, idx, once=True, console=console, state_manager=sm, heartbeat_path=heartbeat_path)

    assert rc == 0
    hb = json.loads(heartbeat_path.read_text())
    assert hb["status"] == "degraded"


def test_run_monitor_survives_token_refresh_failure(tmp_path):
    """A transient token refresh failure must not kill the monitor loop."""
    from anglerfish.exceptions import AuthenticationError

    token_manager = MagicMock()
    token_manager.get_token.side_effect = AuthenticationError("AAD temporarily unavailable")

    client = _mock_audit_client([])
    idx = CanaryIndex([("rec.json", _outlook_record())])
    console = Console(file=None, force_terminal=False)

    rc = run_monitor(
        client,
        idx,
        once=True,
        console=console,
        token_manager=token_manager,
        heartbeat_path=None,
    )

    assert rc == 0
    # The poll still ran with the existing client/token.
    assert client.list_content.called


def test_token_manager_uses_provided_expires_in():
    mgr = _TokenManager("token", expires_in=7200)
    expected = datetime.now(timezone.utc) + timedelta(seconds=7200)
    assert abs((mgr._expires_at - expected).total_seconds()) < 5


def test_token_manager_short_lifetime_does_not_refresh_immediately():
    # With a lifetime shorter than the refresh margin, the margin must shrink
    # rather than trigger a refresh on every call.
    mgr = _TokenManager("short-lived", expires_in=120)
    assert mgr.get_token() == "short-lived"


def test_token_manager_refresh_uses_expires_in_from_auth():
    mgr = _TokenManager("old-token")
    mgr._expires_at = datetime.now(timezone.utc) - timedelta(minutes=1)

    with patch(
        "anglerfish.monitor.authenticate_management_api_with_expiry",
        return_value=("new-token", 1800),
    ):
        assert mgr.get_token() == "new-token"

    expected = datetime.now(timezone.utc) + timedelta(seconds=1800)
    assert abs((mgr._expires_at - expected).total_seconds()) < 5


def test_load_records_logs_warning_for_malformed_record(tmp_path, caplog):
    """Malformed records are skipped AND logged (the comment used to lie about this)."""
    (tmp_path / "good.json").write_text(json.dumps(_outlook_record()))
    (tmp_path / "broken.json").write_text("{ this is not valid json")

    with caplog.at_level("WARNING", logger="anglerfish.monitor"):
        results = load_records(tmp_path)

    assert len(results) == 1
    assert any("broken.json" in rec.message for rec in caplog.records)
