"""Tests for --demo flag behavior."""

import json
import tempfile
from pathlib import Path

from anglerfish import cli
from anglerfish.models import OneDriveTemplate, OutlookTemplate, SharePointTemplate


class _Prompt:
    def __init__(self, value):
        self._value = value

    def ask(self):
        return self._value


EXAMPLES_DIR = Path(__file__).resolve().parents[1] / "examples" / "demo-records"


# --- list subcommand with demo fixtures ---


def test_demo_list_shows_fixture_records():
    """--demo list --records-dir examples/demo-records/ loads fixture JSON files."""
    result = cli.main(["list", "--records-dir", str(EXAMPLES_DIR)])
    assert result == 0


def test_demo_list_shows_outlook_sharepoint_and_onedrive_fixtures():
    """Verify the fixture directory contains the expected files."""
    files = sorted(EXAMPLES_DIR.glob("*.json"))
    names = [f.name for f in files]
    assert "outlook-draft-record.json" in names
    assert "sharepoint-upload-record.json" in names
    assert "onedrive-upload-record.json" in names


def test_demo_list_fixture_records_are_valid():
    """Each fixture record has the required 'timestamp' and 'canary_type' fields."""
    for path in EXAMPLES_DIR.glob("*.json"):
        data = json.loads(path.read_text(encoding="utf-8"))
        assert "timestamp" in data, f"{path.name} missing 'timestamp'"
        assert "canary_type" in data, f"{path.name} missing 'canary_type'"
        assert data["canary_type"] in ("outlook", "sharepoint", "onedrive")
        assert data["status"] == "active"


# --- cleanup subcommand in demo mode ---


def test_demo_cleanup_skips_auth_and_api_calls():
    """--demo cleanup should print simulated output without auth or Graph calls."""
    record_path = EXAMPLES_DIR / "outlook-draft-record.json"
    result = cli.main(["--demo", "cleanup", "--non-interactive", str(record_path)])
    assert result == 0


def test_demo_cleanup_works_for_sharepoint():
    """--demo cleanup with a SharePoint record."""
    record_path = EXAMPLES_DIR / "sharepoint-upload-record.json"
    result = cli.main(["--demo", "cleanup", "--non-interactive", str(record_path)])
    assert result == 0


def test_demo_cleanup_works_for_onedrive():
    """--demo cleanup with a OneDrive record."""
    record_path = EXAMPLES_DIR / "onedrive-upload-record.json"
    result = cli.main(["--demo", "cleanup", "--non-interactive", str(record_path)])
    assert result == 0


def test_demo_cleanup_rejects_unknown_type():
    """--demo cleanup with an unknown canary type returns error."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
        json.dump({"timestamp": "2026-01-01T00:00:00Z", "canary_type": "teams"}, f)
        path = f.name
    result = cli.main(["--demo", "cleanup", "--non-interactive", path])
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
    monkeypatch.setattr(
        cli,
        "list_templates",
        lambda canary_type: [{"name": "Fake Password Reset", "description": "desc", "path": "pkg://outlook/test.yaml"}],
    )
    monkeypatch.setattr(cli, "load_template", lambda path: template)

    result = cli.main(
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


def test_demo_deploy_sharepoint_skips_auth(monkeypatch):
    """--demo deploy with sharepoint template prints simulated output without auth."""
    template = SharePointTemplate(
        name="Employee Salary Bands",
        description="desc",
        site_name="HRSite",
        folder_path="Compensation/Restricted",
        filenames=["salary.txt"],
        content_text="Confidential data",
        variables=[],
    )
    monkeypatch.setattr(
        cli,
        "list_templates",
        lambda canary_type: [
            {"name": "Employee Salary Bands", "description": "desc", "path": "pkg://sharepoint/test.yaml"}
        ],
    )
    monkeypatch.setattr(cli, "load_template", lambda path: template)

    result = cli.main(
        [
            "--demo",
            "--non-interactive",
            "--canary-type",
            "sharepoint",
            "--template",
            "Employee Salary Bands",
            "--target",
            "HRSite",
            "--folder-path",
            "Compensation/Restricted",
            "--filename",
            "salary.txt",
        ]
    )
    assert result == 0


def test_demo_deploy_onedrive_skips_auth(monkeypatch):
    """--demo deploy with onedrive template prints simulated output without auth."""
    template = OneDriveTemplate(
        name="VPN Credentials Backup",
        description="desc",
        folder_path="IT/Backups",
        filenames=["vpn_config.txt"],
        content_text="Canary data",
        variables=[],
    )
    monkeypatch.setattr(
        cli,
        "list_templates",
        lambda canary_type: [
            {"name": "VPN Credentials Backup", "description": "desc", "path": "pkg://onedrive/test.yaml"}
        ],
    )
    monkeypatch.setattr(cli, "load_template", lambda path: template)

    result = cli.main(
        [
            "--demo",
            "--non-interactive",
            "--canary-type",
            "onedrive",
            "--template",
            "VPN Credentials Backup",
            "--target",
            "j.smith@contoso.com",
            "--folder-path",
            "IT/Backups",
            "--filename",
            "vpn_config.txt",
        ]
    )
    assert result == 0


def test_demo_deploy_interactive_selects_template(monkeypatch):
    """--demo in interactive mode runs template selection then prints simulated output."""
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
    monkeypatch.setattr(
        cli,
        "list_templates",
        lambda canary_type: [{"name": "Fake Wire Transfer", "description": "desc", "path": "pkg://outlook/test.yaml"}],
    )
    monkeypatch.setattr(cli, "load_template", lambda path: template)

    monkeypatch.setattr(
        cli.questionary,
        "select",
        lambda message, *args, **kwargs: _Prompt(
            "outlook" if "canary type" in message.lower() else "pkg://outlook/test.yaml"
        ),
    )

    result = cli.main(["--demo"])
    assert result == 0


def test_demo_flag_never_calls_authenticate(monkeypatch):
    """Ensure authenticate is never called in demo mode."""

    def fail_auth(*args, **kwargs):
        raise AssertionError("authenticate should not be called in demo mode")

    monkeypatch.setattr(cli, "authenticate", fail_auth)
    monkeypatch.setattr(cli, "_prompt_auth_setup", fail_auth)

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
    monkeypatch.setattr(
        cli,
        "list_templates",
        lambda canary_type: [{"name": "Test", "description": "desc", "path": "pkg://outlook/t.yaml"}],
    )
    monkeypatch.setattr(cli, "load_template", lambda path: template)

    result = cli.main(
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
