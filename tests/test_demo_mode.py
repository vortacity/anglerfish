"""Tests for --demo flag behavior."""

import json
import tempfile
from pathlib import Path

from anglerfish.cli import main
from anglerfish.cli import deploy as deploy_mod
import anglerfish.cli._main as main_mod
import anglerfish.templates as templates_mod
from anglerfish.models import OutlookTemplate


class _Prompt:
    def __init__(self, value):
        self._value = value

    def ask(self):
        return self._value


EXAMPLES_DIR = Path(__file__).resolve().parents[1] / "examples" / "demo-records"


# --- list subcommand with demo fixtures ---


def test_demo_list_shows_fixture_records():
    """--demo list --records-dir examples/demo-records/ loads fixture JSON files."""
    result = main(["list", "--records-dir", str(EXAMPLES_DIR)])
    assert result == 0


def test_demo_list_only_shows_outlook_fixture_records():
    """Verify the fixture directory contains only the supported Outlook fixtures."""
    files = sorted(EXAMPLES_DIR.glob("*.json"))
    assert [f.name for f in files] == ["outlook-draft-record.json", "outlook-send-record.json"]


def test_demo_list_fixture_records_are_valid():
    """Each fixture record has the required 'timestamp' and 'canary_type' fields."""
    for path in EXAMPLES_DIR.glob("*.json"):
        data = json.loads(path.read_text(encoding="utf-8"))
        assert "timestamp" in data, f"{path.name} missing 'timestamp'"
        assert "canary_type" in data, f"{path.name} missing 'canary_type'"
        assert data["canary_type"] == "outlook"
        assert data["status"] == "active"


# --- cleanup subcommand in demo mode ---


def test_demo_cleanup_skips_auth_and_api_calls():
    """--demo cleanup should print simulated output without auth or Graph calls."""
    record_path = EXAMPLES_DIR / "outlook-draft-record.json"
    result = main(["--demo", "cleanup", "--non-interactive", str(record_path)])
    assert result == 0


def test_demo_cleanup_send_record_skips_auth_and_api_calls():
    """--demo cleanup supports send-mode Outlook records without auth or Graph calls."""
    record_path = EXAMPLES_DIR / "outlook-send-record.json"
    result = main(["--demo", "cleanup", "--non-interactive", str(record_path)])
    assert result == 0


def test_demo_cleanup_rejects_unknown_type():
    """--demo cleanup with an unknown canary type returns error."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
        json.dump({"timestamp": "2026-01-01T00:00:00Z", "canary_type": "unknown"}, f)
        path = f.name
    result = main(["--demo", "cleanup", "--non-interactive", path])
    assert result == 1


# --- deploy in demo mode ---


def test_demo_deploy_outlook_skips_auth(monkeypatch):
    """--demo deploy with outlook template prints simulated output without auth."""
    template = OutlookTemplate(
        name="Fake Password Reset",
        description="desc",
        folder_name="IT Notifications",
        subject="[ACTION REQUIRED] Password Expiry",
        body_html="<p>Hello</p>",
        sender_name="IT Security",
        sender_email="it@contoso.com",
        variables=[],
    )

    def _fake_list(canary_type):
        return [{"name": "Fake Password Reset", "description": "desc", "path": "pkg://outlook/test.yaml"}]

    monkeypatch.setattr(main_mod, "list_templates", _fake_list)
    monkeypatch.setattr(templates_mod, "list_templates", _fake_list)
    monkeypatch.setattr(main_mod, "load_template", lambda path: template)

    result = main(
        [
            "--demo",
            "--non-interactive",
            "--canary-type",
            "outlook",
            "--template",
            "Fake Password Reset",
            "--target",
            "test@example.com",
            "--delivery-mode",
            "draft",
        ]
    )
    assert result == 0


def test_demo_deploy_interactive_selects_template(monkeypatch):
    """--demo auto-enables non-interactive when stdin is not a TTY."""
    template = OutlookTemplate(
        name="Fake Wire Transfer",
        description="desc",
        folder_name="Finance Alerts",
        subject="Wire Transfer",
        body_html="<p>Transfer</p>",
        sender_name="Finance",
        sender_email="finance@contoso.com",
        variables=[],
    )

    def _fake_list(canary_type):
        return [{"name": "Fake Wire Transfer", "description": "desc", "path": "pkg://outlook/test.yaml"}]

    monkeypatch.setattr(main_mod, "list_templates", _fake_list)
    monkeypatch.setattr(templates_mod, "list_templates", _fake_list)
    monkeypatch.setattr(main_mod, "load_template", lambda path: template)

    result = main(
        [
            "--demo",
            "--canary-type",
            "outlook",
            "--template",
            "Fake Wire Transfer",
            "--target",
            "test@contoso.com",
            "--delivery-mode",
            "draft",
        ]
    )
    assert result == 0


def test_demo_flag_never_calls_authenticate(monkeypatch):
    """Ensure authenticate is never called in demo mode."""

    def fail_auth(*args, **kwargs):
        raise AssertionError("authenticate should not be called in demo mode")

    monkeypatch.setattr(deploy_mod, "authenticate", fail_auth)
    monkeypatch.setattr(deploy_mod, "_prompt_auth_setup", fail_auth)

    template = OutlookTemplate(
        name="Test",
        description="desc",
        folder_name="Folder",
        subject="Sub",
        body_html="<p>Body</p>",
        sender_name="Sender",
        sender_email="s@example.com",
        variables=[],
    )

    def _fake_list(canary_type):
        return [{"name": "Test", "description": "desc", "path": "pkg://outlook/t.yaml"}]

    monkeypatch.setattr(main_mod, "list_templates", _fake_list)
    monkeypatch.setattr(templates_mod, "list_templates", _fake_list)
    monkeypatch.setattr(main_mod, "load_template", lambda path: template)

    result = main(
        [
            "--demo",
            "--non-interactive",
            "--canary-type",
            "outlook",
            "--template",
            "Test",
            "--target",
            "x@example.com",
            "--delivery-mode",
            "draft",
        ]
    )
    assert result == 0
