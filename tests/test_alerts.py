"""Tests for the alert dispatcher (alerts.py)."""

from __future__ import annotations

import json
import stat
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


def test_dispatch_jsonl_uses_0600_permissions(tmp_path):
    log_path = tmp_path / "alerts.jsonl"
    dispatcher = AlertDispatcher(alert_log=log_path)
    dispatcher.dispatch(_sample_alert())
    assert stat.S_IMODE(log_path.stat().st_mode) == 0o600


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


def test_console_alert_escapes_markup_in_untrusted_fields():
    """Audit-derived fields must not be interpreted as Rich console markup."""
    console = Console(record=True, force_terminal=False, width=200)
    dispatcher = AlertDispatcher(console=console)
    dispatcher.dispatch(_sample_alert(client_info="[red]SPOOFED[/red]", accessed_by="[bold]evil[/bold]"))
    out = console.export_text()
    # Escaped markup renders literally; if interpreted, these brackets vanish.
    assert "[red]SPOOFED[/red]" in out
    assert "[bold]evil[/bold]" in out


def test_dispatch_slack_skips_non_https_url():
    with patch("anglerfish.alerts.requests.post") as mock_post:
        dispatcher = AlertDispatcher(slack_webhook_url="http://insecure.example/webhook")
        dispatcher.dispatch(_sample_alert())
        mock_post.assert_not_called()


def test_dispatch_slack_non_ok_response_does_not_block_other_channels(tmp_path):
    log_path = tmp_path / "alerts.jsonl"
    with patch("anglerfish.alerts.requests.post") as mock_post:
        mock_post.return_value.ok = False
        mock_post.return_value.status_code = 404
        dispatcher = AlertDispatcher(alert_log=log_path, slack_webhook_url="https://hooks.slack.com/services/x")
        dispatcher.dispatch(_sample_alert())  # must not raise on a non-2xx Slack response
    assert log_path.is_file()  # JSONL channel still wrote


# ------------------------------------------------------------------
# Teams channel
# ------------------------------------------------------------------


def test_dispatch_teams_posts_adaptive_card():
    with patch("anglerfish.alerts.requests.post") as mock_post:
        mock_post.return_value.ok = True
        dispatcher = AlertDispatcher(teams_webhook_url="https://prod-01.westus.logic.azure.com/workflows/abc")
        dispatcher.dispatch(_sample_alert())

        mock_post.assert_called_once()
        payload = mock_post.call_args[1]["json"]
        assert payload["type"] == "message"
        card = payload["attachments"][0]["content"]
        assert card["type"] == "AdaptiveCard"
        assert "accessed" in card["body"][0]["text"]
        assert mock_post.call_args[1]["timeout"] == 10


def test_dispatch_teams_tamper_alert_says_tampered():
    with patch("anglerfish.alerts.requests.post") as mock_post:
        mock_post.return_value.ok = True
        dispatcher = AlertDispatcher(teams_webhook_url="https://prod-01.westus.logic.azure.com/workflows/abc")
        dispatcher.dispatch(_sample_alert(category="tamper", operation="HardDelete"))

        card = mock_post.call_args[1]["json"]["attachments"][0]["content"]
        assert "tampered" in card["body"][0]["text"]


def test_dispatch_teams_skips_non_https_url():
    with patch("anglerfish.alerts.requests.post") as mock_post:
        dispatcher = AlertDispatcher(teams_webhook_url="http://insecure.example.com/hook")
        dispatcher.dispatch(_sample_alert())
        mock_post.assert_not_called()


def test_dispatch_teams_failure_does_not_raise():
    with patch("anglerfish.alerts.requests.post") as mock_post:
        mock_post.side_effect = ConnectionError("network down")
        dispatcher = AlertDispatcher(teams_webhook_url="https://prod-01.westus.logic.azure.com/workflows/abc")
        dispatcher.dispatch(_sample_alert())


# ------------------------------------------------------------------
# Generic webhook channel
# ------------------------------------------------------------------


def test_dispatch_webhook_posts_versioned_json():
    with patch("anglerfish.alerts.requests.post") as mock_post:
        mock_post.return_value.ok = True
        dispatcher = AlertDispatcher(webhook_url="https://siem.example.com/anglerfish")
        dispatcher.dispatch(_sample_alert())

        mock_post.assert_called_once()
        body = mock_post.call_args[1]["data"]
        payload = json.loads(body)
        assert payload["schema_version"] == 1
        assert payload["accessed_by"] == "attacker@evil.com"
        assert payload["category"] == "access"
        headers = mock_post.call_args[1]["headers"]
        assert headers["Content-Type"] == "application/json"
        assert "X-Anglerfish-Signature" not in headers


def test_dispatch_webhook_hmac_signature_verifies():
    import hashlib
    import hmac as hmac_mod

    with patch("anglerfish.alerts.requests.post") as mock_post:
        mock_post.return_value.ok = True
        dispatcher = AlertDispatcher(
            webhook_url="https://siem.example.com/anglerfish",
            webhook_hmac_secret="shared-secret",
        )
        dispatcher.dispatch(_sample_alert())

        body = mock_post.call_args[1]["data"]
        signature = mock_post.call_args[1]["headers"]["X-Anglerfish-Signature"]
        expected = hmac_mod.new(b"shared-secret", body, hashlib.sha256).hexdigest()
        assert signature == f"sha256={expected}"


def test_dispatch_webhook_skips_non_https_url():
    with patch("anglerfish.alerts.requests.post") as mock_post:
        dispatcher = AlertDispatcher(webhook_url="http://siem.example.com/anglerfish")
        dispatcher.dispatch(_sample_alert())
        mock_post.assert_not_called()


def test_dispatch_webhook_redirects_disabled():
    with patch("anglerfish.alerts.requests.post") as mock_post:
        mock_post.return_value.ok = True
        dispatcher = AlertDispatcher(webhook_url="https://siem.example.com/anglerfish")
        dispatcher.dispatch(_sample_alert())
        assert mock_post.call_args[1]["allow_redirects"] is False


# ------------------------------------------------------------------
# Tamper alert rendering
# ------------------------------------------------------------------


def test_console_tamper_alert_title():
    console = Console(record=True, force_terminal=False, width=100)
    dispatcher = AlertDispatcher(console=console)
    dispatcher.dispatch(_sample_alert(category="tamper", operation="HardDelete"))
    output = console.export_text()
    assert "CANARY TAMPERED" in output


def test_jsonl_includes_category(tmp_path):
    log = tmp_path / "alerts.jsonl"
    dispatcher = AlertDispatcher(alert_log=log)
    dispatcher.dispatch(_sample_alert(category="tamper"))
    record = json.loads(log.read_text().splitlines()[0])
    assert record["category"] == "tamper"
