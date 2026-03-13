"""Tests for the monitor CLI subcommand entry point."""

from __future__ import annotations

import argparse
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

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


def test_missing_tenant_id_raises(tmp_path, monkeypatch):
    monkeypatch.delenv("ANGLERFISH_TENANT_ID", raising=False)
    console = MagicMock()
    records = [("rec.json", {"canary_type": "outlook", "target_user": "a@b.com"})]
    args = _make_args(records_dir=str(tmp_path))
    with (
        patch("anglerfish.monitor.load_records", return_value=records),
        patch("anglerfish.monitor.CanaryIndex") as mock_index,
        patch("anglerfish.config.TENANT_ID", ""),
        pytest.raises(AuthenticationError, match="ANGLERFISH_TENANT_ID"),
    ):
        mock_index.return_value.count = 1
        _run_monitor(args, console)
