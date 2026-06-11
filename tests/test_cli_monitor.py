"""Tests for the monitor CLI subcommand entry point."""

from __future__ import annotations

import argparse
from datetime import timedelta
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from anglerfish.auth import AuthConfig
from anglerfish.cli.monitor import _run_monitor
from anglerfish.exceptions import AuthenticationError


def _make_args(**overrides):
    """Return a minimal argparse.Namespace for _run_monitor."""
    defaults = {
        "demo": False,
        "demo_count": 1,
        "records_dir": str(Path.home() / ".anglerfish" / "records"),
        "tenant_id": None,
        "client_id": None,
        "credential_mode": "secret",
        "interval": 300,
        "once": False,
        "exclude_app_ids": [],
        "cleaned_up_lookback_hours": 24.0,
        "state_file": None,
        "no_console": False,
        "alert_log": None,
        "slack_webhook_url": None,
    }
    defaults.update(overrides)
    return argparse.Namespace(**defaults)


def test_demo_mode_returns_zero():
    console = MagicMock()
    args = _make_args(demo=True)
    with patch("anglerfish.monitor.render_demo_alert") as mock_render:
        result = _run_monitor(args, console)
    assert result == 0
    mock_render.assert_called_once_with(console, count=1)


def test_demo_mode_custom_count():
    console = MagicMock()
    args = _make_args(demo=True, demo_count=3)
    with patch("anglerfish.monitor.render_demo_alert") as mock_render:
        result = _run_monitor(args, console)
    assert result == 0
    mock_render.assert_called_once_with(console, count=3)


def test_no_records_returns_one(tmp_path):
    console = MagicMock()
    empty_dir = tmp_path / "empty"
    empty_dir.mkdir()
    args = _make_args(records_dir=str(empty_dir))
    with patch("anglerfish.monitor.load_records", return_value=[]):
        result = _run_monitor(args, console)
    assert result == 1


def test_monitor_passes_cleaned_up_lookback_to_load_records(tmp_path):
    console = MagicMock()
    empty_dir = tmp_path / "empty"
    empty_dir.mkdir()
    args = _make_args(records_dir=str(empty_dir), cleaned_up_lookback_hours=6.5)
    with patch("anglerfish.monitor.load_records", return_value=[]) as mock_load_records:
        result = _run_monitor(args, console)
    assert result == 1
    mock_load_records.assert_called_once_with(str(empty_dir), cleaned_up_lookback=timedelta(hours=6.5))


def test_monitor_clamps_negative_cleaned_up_lookback_to_zero(tmp_path):
    console = MagicMock()
    empty_dir = tmp_path / "empty"
    empty_dir.mkdir()
    args = _make_args(records_dir=str(empty_dir), cleaned_up_lookback_hours=-1.5)
    with patch("anglerfish.monitor.load_records", return_value=[]) as mock_load_records:
        result = _run_monitor(args, console)
    assert result == 1
    mock_load_records.assert_called_once_with(str(empty_dir), cleaned_up_lookback=timedelta(0))


def test_missing_tenant_id_raises(tmp_path, monkeypatch):
    monkeypatch.delenv("ANGLERFISH_TENANT_ID", raising=False)
    console = MagicMock()
    records = [("rec.json", {"canary_type": "outlook", "target_user": "a@b.com"})]
    args = _make_args(records_dir=str(tmp_path))
    with (
        patch("anglerfish.monitor.load_records", return_value=records),
        patch("anglerfish.monitor.CanaryIndex") as mock_index,
        pytest.raises(AuthenticationError, match="ANGLERFISH_TENANT_ID"),
    ):
        mock_index.return_value.count = 1
        _run_monitor(args, console)


def test_run_monitor_wires_dependencies_and_runs(tmp_path, monkeypatch):
    """The non-demo path builds state/dispatcher/token-manager and calls run_monitor."""
    monkeypatch.setenv("ANGLERFISH_TENANT_ID", "tenant-1")
    console = MagicMock()
    records = [("rec.json", {"canary_type": "outlook", "target_user": "a@b.com"})]
    args = _make_args(
        records_dir=str(tmp_path),
        no_console=True,
        slack_webhook_url="https://hooks.slack.com/services/x",
        alert_log=str(tmp_path / "alerts.jsonl"),
        state_file=str(tmp_path / "state.json"),
        exclude_app_ids=["AbC", "   "],
    )

    captured: dict[str, object] = {}

    def fake_run_monitor(audit_client, canary_index, **kwargs):
        captured.update(kwargs)
        return 0

    with (
        patch("anglerfish.monitor.load_records", return_value=records),
        patch("anglerfish.monitor.CanaryIndex") as mock_index,
        patch("anglerfish.cli.monitor._prompt_auth_setup", return_value=AuthConfig(credential_mode="secret")),
        patch("anglerfish.cli.monitor.authenticate_management_api_with_expiry", return_value=("tok", 3600)),
        patch("anglerfish.monitor.run_monitor", side_effect=fake_run_monitor),
    ):
        mock_index.return_value.count = 1
        rc = _run_monitor(args, console)

    assert rc == 0
    assert captured["once"] is False
    assert captured["interval"] == 300
    # Blank/dup IDs normalized and lower-cased.
    assert captured["exclude_app_ids"] == {"abc"}
    # no_console -> dispatcher suppresses console; Slack + state wired through.
    assert captured["dispatcher"]._console is None
    assert captured["dispatcher"]._slack_webhook_url == "https://hooks.slack.com/services/x"
    assert captured["state_manager"] is not None
    assert captured["token_manager"] is not None


def test_run_monitor_returns_130_when_auth_prompt_cancelled(tmp_path, monkeypatch):
    monkeypatch.setenv("ANGLERFISH_TENANT_ID", "tenant-1")
    console = MagicMock()
    records = [("rec.json", {"canary_type": "outlook", "target_user": "a@b.com"})]
    args = _make_args(records_dir=str(tmp_path))

    with (
        patch("anglerfish.monitor.load_records", return_value=records),
        patch("anglerfish.monitor.CanaryIndex") as mock_index,
        patch("anglerfish.cli.monitor._prompt_auth_setup", return_value=None),
    ):
        mock_index.return_value.count = 1
        rc = _run_monitor(args, console)

    assert rc == 130
