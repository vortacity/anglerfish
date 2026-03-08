"""Tests for the alert dispatcher (alerts.py)."""

from __future__ import annotations

import json
from unittest.mock import patch

from rich.console import Console

from anglerfish.alerts import AlertDispatcher
from anglerfish.monitor import CanaryAlert


def _sample_alert(**overrides) -> CanaryAlert:
    defaults = {
        "canary_type": "outlook",
        "template_name": "Fake Password Reset",
        "artifact_label": "internet_message_id: <test@contoso.com>",
        "accessed_by": "attacker@evil.com",
        "source_ip": "203.0.113.42",
        "timestamp": "2026-03-05T14:22:00Z",
        "operation": "MailItemsAccessed",
        "client_info": "Client=OWA",
        "record_path": "records/test.json",
    }
    defaults.update(overrides)
    return CanaryAlert(**defaults)


# ------------------------------------------------------------------
# Console channel
# ------------------------------------------------------------------


def test_dispatch_console():
    console = Console(file=None, force_terminal=False)
    dispatcher = AlertDispatcher(console=console)
    # Should not raise.
    dispatcher.dispatch(_sample_alert())


def test_dispatch_no_console():
    dispatcher = AlertDispatcher(console=None)
    # Should not raise even without any channels.
    dispatcher.dispatch(_sample_alert())


# ------------------------------------------------------------------
# JSONL log channel
# ------------------------------------------------------------------


def test_dispatch_jsonl(tmp_path):
    log_path = tmp_path / "alerts.jsonl"
    dispatcher = AlertDispatcher(alert_log=log_path)

    dispatcher.dispatch(_sample_alert())
    dispatcher.dispatch(_sample_alert(accessed_by="other@evil.com"))

    lines = log_path.read_text().strip().split("\n")
    assert len(lines) == 2

    record = json.loads(lines[0])
    assert record["canary_type"] == "outlook"
    assert record["accessed_by"] == "attacker@evil.com"

    record2 = json.loads(lines[1])
    assert record2["accessed_by"] == "other@evil.com"


def test_dispatch_jsonl_creates_parent_dirs(tmp_path):
    log_path = tmp_path / "deep" / "nested" / "alerts.jsonl"
    dispatcher = AlertDispatcher(alert_log=log_path)
    dispatcher.dispatch(_sample_alert())

    assert log_path.is_file()


# ------------------------------------------------------------------
# Multi-channel fan-out
# ------------------------------------------------------------------


def test_dispatch_all_channels(tmp_path):
    console = Console(file=None, force_terminal=False)
    log_path = tmp_path / "alerts.jsonl"

    with patch("anglerfish.alerts.requests.post") as mock_post:
        mock_post.return_value.ok = True
        dispatcher = AlertDispatcher(
            console=console,
            alert_log=log_path,
            slack_webhook_url="https://hooks.slack.com/services/T/B/xxx",
        )
        dispatcher.dispatch(_sample_alert())

    assert log_path.is_file()
    mock_post.assert_called_once()


def test_console_failure_does_not_block_jsonl(tmp_path):
    """If console rendering fails, JSONL should still get the alert."""
    log_path = tmp_path / "alerts.jsonl"

    # Use a console that will raise on print.
    bad_console = Console(file=None, force_terminal=False)
    with patch.object(bad_console, "print", side_effect=RuntimeError("boom")):
        dispatcher = AlertDispatcher(console=bad_console, alert_log=log_path)
        dispatcher.dispatch(_sample_alert())

    assert log_path.is_file()
    lines = log_path.read_text().strip().split("\n")
    assert len(lines) == 1


# ------------------------------------------------------------------
# Slack channel
# ------------------------------------------------------------------


def test_dispatch_slack_posts_block_kit():
    with patch("anglerfish.alerts.requests.post") as mock_post:
        mock_post.return_value.ok = True
        dispatcher = AlertDispatcher(slack_webhook_url="https://hooks.slack.com/services/T/B/xxx")
        dispatcher.dispatch(_sample_alert())

        mock_post.assert_called_once()
        call_kwargs = mock_post.call_args
        payload = call_kwargs[1]["json"]
        # Slack Block Kit has "blocks" key
        assert "blocks" in payload
        assert call_kwargs[1]["timeout"] == 10


def test_dispatch_slack_failure_does_not_raise():
    with patch("anglerfish.alerts.requests.post") as mock_post:
        mock_post.side_effect = ConnectionError("network down")
        dispatcher = AlertDispatcher(slack_webhook_url="https://hooks.slack.com/services/T/B/xxx")
        # Should not raise.
        dispatcher.dispatch(_sample_alert())
