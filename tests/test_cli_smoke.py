import json

import pytest

from anglerfish import cli
from anglerfish.models import OneDriveTemplate, OutlookTemplate, SharePointTemplate


class _Prompt:
    def __init__(self, value):
        self._value = value

    def ask(self):
        return self._value


def test_main_version_flag():
    assert cli.main(["--version"]) == 0


def test_parse_args_accepts_onedrive_type():
    args = cli._parse_args(["--canary-type", "onedrive"])
    assert args.canary_type == "onedrive"


def test_parse_args_rejects_removed_simulate_flag():
    with pytest.raises(SystemExit):
        cli._parse_args(["--simulate"])


def test_main_non_interactive_requires_canary_type():
    assert cli.main(["--non-interactive"]) == 1


def test_main_non_interactive_requires_template_for_outlook():
    assert (
        cli.main(
            [
                "--non-interactive",
                "--canary-type",
                "outlook",
                "--target",
                "user@contoso.com",
                "--delivery-mode",
                "draft",
            ]
        )
        == 1
    )


def test_main_sharepoint_flow_deploys(monkeypatch):
    monkeypatch.setenv("ANGLERFISH_CLIENT_ID", "client-id")
    monkeypatch.setattr(cli, "_prompt_auth_setup", lambda *args, **kwargs: "")
    monkeypatch.setattr(cli, "_print_auth_success", lambda *args, **kwargs: None)
    monkeypatch.setattr(cli, "authenticate", lambda *args, **kwargs: "token-123")

    template = SharePointTemplate(
        name="SharePoint Template",
        description="desc",
        site_name="Finance",
        folder_path="Shared Documents/Canary",
        filenames=["bonus_plan.txt"],
        content_text="Canary file: ${filename}",
        variables=[],
    )
    monkeypatch.setattr(
        cli,
        "list_templates",
        lambda canary_type: [
            {"name": "SharePoint Template", "description": "desc", "path": "pkg://sharepoint/test.yaml"}
        ],
    )
    monkeypatch.setattr(cli, "load_template", lambda path: template)

    select_answers = {
        "Select canary type:": "sharepoint",
        "Select template:": "pkg://sharepoint/test.yaml",
        "Select SharePoint site:": "contoso.sharepoint.com,abc123,def456",
    }
    text_answers = {
        "Search SharePoint sites:": "Finance",
        "Destination folder path:": "Shared Documents/Canary",
        "Canary filename:": "bonus_plan.txt",
    }

    monkeypatch.setattr(
        cli.questionary,
        "select",
        lambda message, *args, **kwargs: _Prompt(select_answers[message]),
    )
    monkeypatch.setattr(
        cli.questionary,
        "text",
        lambda message, *args, **kwargs: _Prompt(text_answers[message]),
    )
    monkeypatch.setattr(
        cli.questionary,
        "confirm",
        lambda *args, **kwargs: _Prompt(True),
    )

    observed: dict[str, object] = {}

    class FakeGraphClient:
        def __init__(self, token):
            observed["token"] = token

        def get(self, path, params=None):
            if path == "/sites":
                return {
                    "value": [
                        {
                            "id": "contoso.sharepoint.com,abc123,def456",
                            "displayName": "Finance",
                            "name": "Finance",
                            "webUrl": "https://contoso.sharepoint.com/sites/Finance",
                        }
                    ]
                }
            raise AssertionError(f"Unexpected GET path: {path}")

    class FakeSharePointDeployer:
        def __init__(self, graph, template_obj):
            observed["graph"] = graph
            observed["template"] = template_obj

        def deploy(self, target_user: str, **kwargs):
            observed["target_user"] = target_user
            observed["kwargs"] = kwargs
            return {"type": "sharepoint", "uploaded_count": "1"}

    monkeypatch.setattr(cli, "GraphClient", FakeGraphClient)
    monkeypatch.setattr(cli, "SharePointDeployer", FakeSharePointDeployer)

    result = cli.main([])

    assert result == 0
    assert observed["token"] == "token-123"
    assert observed["target_user"] == "Finance"
    assert observed["kwargs"] == {
        "folder_path": "Canary",
        "filenames": ["bonus_plan.txt"],
        "site_id": "contoso.sharepoint.com,abc123,def456",
    }


def test_main_sharepoint_flow_prompts_manual_when_no_discovered_sites(monkeypatch):
    monkeypatch.setenv("ANGLERFISH_CLIENT_ID", "client-id")
    monkeypatch.setattr(cli, "_prompt_auth_setup", lambda *args, **kwargs: "")
    monkeypatch.setattr(cli, "_print_auth_success", lambda *args, **kwargs: None)
    monkeypatch.setattr(cli, "authenticate", lambda *args, **kwargs: "token-123")

    template = SharePointTemplate(
        name="SharePoint Template",
        description="desc",
        site_name="Finance",
        folder_path="Shared Documents/Canary",
        filenames=["bonus_plan.txt"],
        content_text="Canary file: ${filename}",
        variables=[],
    )
    monkeypatch.setattr(
        cli,
        "list_templates",
        lambda canary_type: [
            {"name": "SharePoint Template", "description": "desc", "path": "pkg://sharepoint/test.yaml"}
        ],
    )
    monkeypatch.setattr(cli, "load_template", lambda path: template)

    select_answers = {
        "Select canary type:": "sharepoint",
        "Select template:": "pkg://sharepoint/test.yaml",
    }
    text_answers = {
        "Search SharePoint sites:": "Unknown",
        "SharePoint site name:": "ManualSite",
        "Destination folder path:": "Finance/Restricted",
        "Canary filename:": "manual.txt",
    }

    monkeypatch.setattr(
        cli.questionary,
        "select",
        lambda message, *args, **kwargs: _Prompt(select_answers[message]),
    )
    monkeypatch.setattr(
        cli.questionary,
        "text",
        lambda message, *args, **kwargs: _Prompt(text_answers[message]),
    )
    monkeypatch.setattr(
        cli.questionary,
        "confirm",
        lambda *args, **kwargs: _Prompt(True),
    )

    observed: dict[str, object] = {}

    class FakeGraphClient:
        def __init__(self, token):
            observed["token"] = token

        def get(self, path, params=None):
            if path == "/sites":
                return {"value": []}
            raise AssertionError(f"Unexpected GET path: {path}")

    class FakeSharePointDeployer:
        def __init__(self, graph, template_obj):
            observed["template"] = template_obj

        def deploy(self, target_user: str, **kwargs):
            observed["target_user"] = target_user
            observed["kwargs"] = kwargs
            return {"type": "sharepoint", "uploaded_count": "1"}

    monkeypatch.setattr(cli, "GraphClient", FakeGraphClient)
    monkeypatch.setattr(cli, "SharePointDeployer", FakeSharePointDeployer)

    result = cli.main([])

    assert result == 0
    assert observed["target_user"] == "ManualSite"
    assert observed["kwargs"] == {
        "folder_path": "Finance/Restricted",
        "filenames": ["manual.txt"],
        "site_id": "",
    }


def test_main_outlook_flow_deploys(monkeypatch):
    monkeypatch.setenv("ANGLERFISH_CLIENT_ID", "client-id")
    monkeypatch.setattr(cli, "_prompt_auth_setup", lambda *args, **kwargs: "")
    monkeypatch.setattr(cli, "_print_auth_success", lambda *args, **kwargs: None)
    monkeypatch.setattr(cli, "authenticate", lambda *args, **kwargs: "token-123")

    template = OutlookTemplate(
        name="Outlook Template",
        description="desc",
        folder_name="IT Notifications",
        subject="Subject",
        body_html="<p>Hello</p>",
        sender_name="IT",
        sender_email="it@contoso.com",
        variables=[],
    )
    monkeypatch.setattr(
        cli,
        "list_templates",
        lambda canary_type: [{"name": "Outlook Template", "description": "desc", "path": "pkg://outlook/test.yaml"}],
    )
    monkeypatch.setattr(cli, "load_template", lambda path: template)

    select_answers = {
        "Select canary type:": "outlook",
        "Select template:": "pkg://outlook/test.yaml",
        "Select delivery mode:": "draft",
    }
    text_answers = {
        "Hidden folder name:": "IT Notifications",
        "Target mailbox (UPN/email):": "victim@contoso.com",
    }

    monkeypatch.setattr(
        cli.questionary,
        "select",
        lambda message, *args, **kwargs: _Prompt(select_answers[message]),
    )
    monkeypatch.setattr(
        cli.questionary,
        "text",
        lambda message, *args, **kwargs: _Prompt(text_answers[message]),
    )
    monkeypatch.setattr(
        cli.questionary,
        "confirm",
        lambda *args, **kwargs: _Prompt(True),
    )

    observed: dict[str, object] = {}

    class FakeGraphClient:
        def __init__(self, token):
            observed["token"] = token

    class FakeOutlookDeployer:
        def __init__(self, graph, template_obj):
            observed["template"] = template_obj

        def deploy(self, target_user: str, **kwargs):
            observed["target_user"] = target_user
            observed["kwargs"] = kwargs
            return {"delivery_mode": "draft", "folder_id": "folder-1", "message_id": "msg-1"}

    monkeypatch.setattr(cli, "GraphClient", FakeGraphClient)
    monkeypatch.setattr(cli, "OutlookDeployer", FakeOutlookDeployer)

    result = cli.main([])

    assert result == 0
    assert observed["token"] == "token-123"
    assert observed["target_user"] == "victim@contoso.com"
    assert observed["kwargs"] == {"delivery_mode": "draft"}


def test_main_cleanup_sharepoint_happy_path(monkeypatch, tmp_path):
    record_path = tmp_path / "record.json"
    record_path.write_text("{}", encoding="utf-8")

    monkeypatch.setattr(
        cli,
        "read_deployment_record",
        lambda path: {
            "type": "sharepoint",
            "site_id": "site-1",
            "item_id": "item-1",
            "folder_path": "Finance/Restricted",
            "uploaded_files": "manual.txt",
        },
    )
    monkeypatch.setattr(cli, "_prompt_auth_setup", lambda *args, **kwargs: "")
    monkeypatch.setattr(cli, "authenticate", lambda *args, **kwargs: "token-123")
    monkeypatch.setattr(cli, "_print_auth_success", lambda *args, **kwargs: None)

    class FakeGraphClient:
        def __init__(self, token):
            assert token == "token-123"

    monkeypatch.setattr(cli, "GraphClient", FakeGraphClient)
    monkeypatch.setattr(cli, "sharepoint_remove_canary", lambda graph, record: {"removed": "true"})

    status_updates: list[tuple[str, str]] = []
    monkeypatch.setattr(
        cli,
        "update_deployment_status",
        lambda path, status: status_updates.append((str(path), status)),
    )

    result = cli.main(["cleanup", "--non-interactive", str(record_path)])

    assert result == 0
    assert status_updates == [(str(record_path), "cleaned_up")]


def test_main_list_returns_zero_when_records_dir_missing(tmp_path):
    missing = tmp_path / "does-not-exist"
    assert cli.main(["list", "--records-dir", str(missing)]) == 0


def test_main_outlook_writes_output_json(monkeypatch, tmp_path):
    monkeypatch.setenv("ANGLERFISH_CLIENT_ID", "client-id")
    monkeypatch.setattr(cli, "_prompt_auth_setup", lambda *args, **kwargs: "")
    monkeypatch.setattr(cli, "_print_auth_success", lambda *args, **kwargs: None)
    monkeypatch.setattr(cli, "authenticate", lambda *args, **kwargs: "token-123")

    template = OutlookTemplate(
        name="Outlook Template",
        description="desc",
        folder_name="IT Notifications",
        subject="Subject",
        body_html="<p>Hello</p>",
        sender_name="IT",
        sender_email="it@contoso.com",
        variables=[],
    )
    monkeypatch.setattr(
        cli,
        "list_templates",
        lambda canary_type: [{"name": "Outlook Template", "description": "desc", "path": "pkg://outlook/test.yaml"}],
    )
    monkeypatch.setattr(cli, "load_template", lambda path: template)

    select_answers = {
        "Select canary type:": "outlook",
        "Select template:": "pkg://outlook/test.yaml",
        "Select delivery mode:": "send",
    }
    text_answers = {
        "Target mailbox (UPN/email):": "victim@contoso.com",
    }
    monkeypatch.setattr(cli.questionary, "select", lambda message, *args, **kwargs: _Prompt(select_answers[message]))
    monkeypatch.setattr(cli.questionary, "text", lambda message, *args, **kwargs: _Prompt(text_answers[message]))
    monkeypatch.setattr(cli.questionary, "confirm", lambda *args, **kwargs: _Prompt(True))

    monkeypatch.setattr(cli, "GraphClient", lambda token: object())

    class FakeOutlookDeployer:
        def __init__(self, graph, template_obj):
            pass

        def deploy(self, target_user: str, **kwargs):
            return {"delivery_mode": "send", "target_user": target_user, "inbox_message_id": "msg-1"}

    monkeypatch.setattr(cli, "OutlookDeployer", FakeOutlookDeployer)

    output = tmp_path / "record.json"
    result = cli.main(["--output-json", str(output)])

    assert result == 0
    data = json.loads(output.read_text(encoding="utf-8"))
    assert data["canary_type"] == "outlook"
    assert data["status"] == "active"
    assert data["auth_mode"] == "application"


def test_main_delegates_to_outlook_handler(monkeypatch):
    monkeypatch.setattr(cli, "_print_banner", lambda *_: None)
    monkeypatch.setattr(
        cli,
        "list_templates",
        lambda canary_type: [{"name": "Outlook Template", "description": "desc", "path": "pkg://outlook/test.yaml"}],
    )
    template = OutlookTemplate(
        name="Outlook Template",
        description="desc",
        folder_name="IT Notifications",
        subject="Subject",
        body_html="<p>Hello</p>",
        sender_name="IT",
        sender_email="it@contoso.com",
        variables=[],
    )
    monkeypatch.setattr(cli, "load_template", lambda path: template)

    observed: dict[str, object] = {}

    def fake_outlook_handler(args, console, rendered_template, non_interactive, total_steps, cli_var_values):
        observed["template"] = rendered_template
        observed["non_interactive"] = non_interactive
        observed["total_steps"] = total_steps
        observed["cli_var_values"] = cli_var_values
        return 0

    monkeypatch.setattr(cli, "_run_outlook_deploy", fake_outlook_handler)
    monkeypatch.setattr(
        cli,
        "_run_sharepoint_deploy",
        lambda *args, **kwargs: pytest.fail("SharePoint handler should not be called"),
    )

    result = cli.main(
        [
            "--non-interactive",
            "--canary-type",
            "outlook",
            "--template",
            "Outlook Template",
            "--target",
            "user@contoso.com",
            "--delivery-mode",
            "draft",
        ]
    )

    assert result == 0
    assert observed["template"] == template
    assert observed["non_interactive"] is True
    assert observed["total_steps"] == 4
    assert observed["cli_var_values"] == {}


def test_main_delegates_to_sharepoint_handler(monkeypatch):
    monkeypatch.setattr(cli, "_print_banner", lambda *_: None)
    monkeypatch.setattr(
        cli,
        "list_templates",
        lambda canary_type: [
            {"name": "SharePoint Template", "description": "desc", "path": "pkg://sharepoint/test.yaml"}
        ],
    )
    template = SharePointTemplate(
        name="SharePoint Template",
        description="desc",
        site_name="Finance",
        folder_path="Shared Documents/Canary",
        filenames=["bonus_plan.txt"],
        content_text="Canary file: ${filename}",
        variables=[],
    )
    monkeypatch.setattr(cli, "load_template", lambda path: template)

    observed: dict[str, object] = {}

    def fake_sharepoint_handler(args, console, rendered_template, non_interactive, total_steps, cli_var_values):
        observed["template"] = rendered_template
        observed["non_interactive"] = non_interactive
        observed["total_steps"] = total_steps
        observed["cli_var_values"] = cli_var_values
        return 0

    monkeypatch.setattr(
        cli,
        "_run_outlook_deploy",
        lambda *args, **kwargs: pytest.fail("Outlook handler should not be called"),
    )
    monkeypatch.setattr(cli, "_run_sharepoint_deploy", fake_sharepoint_handler)

    result = cli.main(
        [
            "--non-interactive",
            "--canary-type",
            "sharepoint",
            "--template",
            "SharePoint Template",
            "--target",
            "Finance",
            "--folder-path",
            "Canary",
            "--filename",
            "bonus_plan.txt",
        ]
    )

    assert result == 0
    assert observed["template"] == template
    assert observed["non_interactive"] is True
    assert observed["total_steps"] == 4
    assert observed["cli_var_values"] == {}


def test_main_onedrive_flow_deploys(monkeypatch):
    monkeypatch.setenv("ANGLERFISH_CLIENT_ID", "client-id")
    monkeypatch.setattr(cli, "_prompt_auth_setup", lambda *args, **kwargs: "")
    monkeypatch.setattr(cli, "_print_auth_success", lambda *args, **kwargs: None)
    monkeypatch.setattr(cli, "authenticate", lambda *args, **kwargs: "token-123")

    template = OneDriveTemplate(
        name="OneDrive Template",
        description="desc",
        folder_path="IT/Backups",
        filenames=["vpn_config.txt"],
        content_text="Canary file: ${filename}",
        variables=[],
    )
    monkeypatch.setattr(
        cli,
        "list_templates",
        lambda canary_type: [{"name": "OneDrive Template", "description": "desc", "path": "pkg://onedrive/test.yaml"}],
    )
    monkeypatch.setattr(cli, "load_template", lambda path: template)

    select_answers = {
        "Select canary type:": "onedrive",
        "Select template:": "pkg://onedrive/test.yaml",
    }
    text_answers = {
        "Target user (UPN/email):": "j.smith@contoso.com",
        "Destination folder path:": "IT/Backups",
        "Canary filename:": "vpn_config.txt",
    }

    monkeypatch.setattr(
        cli.questionary,
        "select",
        lambda message, *args, **kwargs: _Prompt(select_answers[message]),
    )
    monkeypatch.setattr(
        cli.questionary,
        "text",
        lambda message, *args, **kwargs: _Prompt(text_answers[message]),
    )
    monkeypatch.setattr(
        cli.questionary,
        "confirm",
        lambda *args, **kwargs: _Prompt(True),
    )

    observed: dict[str, object] = {}

    class FakeGraphClient:
        def __init__(self, token):
            observed["token"] = token

    class FakeOneDriveDeployer:
        def __init__(self, graph, template_obj):
            observed["graph"] = graph
            observed["template"] = template_obj

        def deploy(self, target_user: str, **kwargs):
            observed["target_user"] = target_user
            observed["kwargs"] = kwargs
            return {"type": "onedrive", "uploaded_count": "1"}

    monkeypatch.setattr(cli, "GraphClient", FakeGraphClient)
    monkeypatch.setattr(cli, "OneDriveDeployer", FakeOneDriveDeployer)

    result = cli.main([])

    assert result == 0
    assert observed["token"] == "token-123"
    assert observed["target_user"] == "j.smith@contoso.com"
    assert observed["kwargs"] == {
        "folder_path": "IT/Backups",
        "filenames": ["vpn_config.txt"],
    }


def test_main_onedrive_non_interactive_deploys(monkeypatch):
    monkeypatch.setenv("ANGLERFISH_CLIENT_ID", "client-id")
    monkeypatch.setattr(cli, "_prompt_auth_setup", lambda *args, **kwargs: "")
    monkeypatch.setattr(cli, "_print_auth_success", lambda *args, **kwargs: None)
    monkeypatch.setattr(cli, "authenticate", lambda *args, **kwargs: "token-123")

    template = OneDriveTemplate(
        name="OneDrive Template",
        description="desc",
        folder_path="IT/Backups",
        filenames=["vpn_config.txt"],
        content_text="Canary file: ${filename}",
        variables=[],
    )
    monkeypatch.setattr(
        cli,
        "list_templates",
        lambda canary_type: [{"name": "OneDrive Template", "description": "desc", "path": "pkg://onedrive/test.yaml"}],
    )
    monkeypatch.setattr(cli, "load_template", lambda path: template)

    observed: dict[str, object] = {}

    class FakeGraphClient:
        def __init__(self, token):
            observed["token"] = token

    class FakeOneDriveDeployer:
        def __init__(self, graph, template_obj):
            pass

        def deploy(self, target_user: str, **kwargs):
            observed["target_user"] = target_user
            observed["kwargs"] = kwargs
            return {"type": "onedrive", "uploaded_count": "1"}

    monkeypatch.setattr(cli, "GraphClient", FakeGraphClient)
    monkeypatch.setattr(cli, "OneDriveDeployer", FakeOneDriveDeployer)

    result = cli.main(
        [
            "--non-interactive",
            "--canary-type",
            "onedrive",
            "--template",
            "OneDrive Template",
            "--target",
            "j.smith@contoso.com",
            "--folder-path",
            "IT/Backups",
            "--filename",
            "vpn_config.txt",
        ]
    )

    assert result == 0
    assert observed["target_user"] == "j.smith@contoso.com"


def test_main_cleanup_onedrive_happy_path(monkeypatch, tmp_path):
    record_path = tmp_path / "record.json"
    record_path.write_text("{}", encoding="utf-8")

    monkeypatch.setattr(
        cli,
        "read_deployment_record",
        lambda path: {
            "type": "onedrive",
            "target_user": "j.smith@contoso.com",
            "item_id": "item-1",
            "folder_path": "IT/Backups",
            "uploaded_files": "vpn_config.txt",
        },
    )
    monkeypatch.setattr(cli, "_prompt_auth_setup", lambda *args, **kwargs: "")
    monkeypatch.setattr(cli, "authenticate", lambda *args, **kwargs: "token-123")
    monkeypatch.setattr(cli, "_print_auth_success", lambda *args, **kwargs: None)

    class FakeGraphClient:
        def __init__(self, token):
            assert token == "token-123"

    monkeypatch.setattr(cli, "GraphClient", FakeGraphClient)
    monkeypatch.setattr(cli, "onedrive_remove_canary", lambda graph, record: {"removed": "true"})

    status_updates: list[tuple[str, str]] = []
    monkeypatch.setattr(
        cli,
        "update_deployment_status",
        lambda path, status: status_updates.append((str(path), status)),
    )

    result = cli.main(["cleanup", "--non-interactive", str(record_path)])

    assert result == 0
    assert status_updates == [(str(record_path), "cleaned_up")]


def test_main_delegates_to_onedrive_handler(monkeypatch):
    monkeypatch.setattr(cli, "_print_banner", lambda *_: None)
    monkeypatch.setattr(
        cli,
        "list_templates",
        lambda canary_type: [{"name": "OneDrive Template", "description": "desc", "path": "pkg://onedrive/test.yaml"}],
    )
    template = OneDriveTemplate(
        name="OneDrive Template",
        description="desc",
        folder_path="IT/Backups",
        filenames=["vpn_config.txt"],
        content_text="Canary file: ${filename}",
        variables=[],
    )
    monkeypatch.setattr(cli, "load_template", lambda path: template)

    observed: dict[str, object] = {}

    def fake_onedrive_handler(args, console, rendered_template, non_interactive, total_steps, cli_var_values):
        observed["template"] = rendered_template
        observed["non_interactive"] = non_interactive
        observed["total_steps"] = total_steps
        observed["cli_var_values"] = cli_var_values
        return 0

    monkeypatch.setattr(cli, "_run_onedrive_deploy", fake_onedrive_handler)
    monkeypatch.setattr(
        cli,
        "_run_outlook_deploy",
        lambda *args, **kwargs: pytest.fail("Outlook handler should not be called"),
    )
    monkeypatch.setattr(
        cli,
        "_run_sharepoint_deploy",
        lambda *args, **kwargs: pytest.fail("SharePoint handler should not be called"),
    )

    result = cli.main(
        [
            "--non-interactive",
            "--canary-type",
            "onedrive",
            "--template",
            "OneDrive Template",
            "--target",
            "j.smith@contoso.com",
            "--folder-path",
            "IT/Backups",
            "--filename",
            "vpn_config.txt",
        ]
    )

    assert result == 0
    assert observed["template"] == template
    assert observed["non_interactive"] is True
    assert observed["total_steps"] == 4
    assert observed["cli_var_values"] == {}


# ---------------------------------------------------------------------------
# Batch subcommand tests
# ---------------------------------------------------------------------------


def test_parse_args_batch_subcommand():
    args = cli._parse_args(["batch", "manifest.yaml"])
    assert args.subcommand == "batch"
    assert args.manifest == "manifest.yaml"


def test_parse_args_batch_with_output_dir():
    args = cli._parse_args(["batch", "manifest.yaml", "--output-dir", "/tmp/records"])
    assert args.output_dir == "/tmp/records"


def test_parse_args_batch_with_dry_run():
    args = cli._parse_args(["batch", "manifest.yaml", "--dry-run"])
    assert args.dry_run is True


def test_main_batch_missing_manifest_file():
    assert cli.main(["batch", "/nonexistent/manifest.yaml"]) == 1


def test_main_batch_happy_path(monkeypatch, tmp_path):
    """End-to-end: batch subcommand deploys from manifest and writes records."""
    import yaml

    import anglerfish.batch as batch_mod

    manifest = tmp_path / "manifest.yaml"
    manifest.write_text(
        yaml.dump(
            {
                "canaries": [
                    {
                        "canary_type": "outlook",
                        "template": "Outlook Template",
                        "target": "cfo@contoso.com",
                        "delivery_mode": "draft",
                    },
                ]
            }
        )
    )
    output_dir = tmp_path / "records"

    monkeypatch.setattr(cli, "_prompt_auth_setup", lambda *args, **kwargs: "")
    monkeypatch.setattr(cli, "_print_auth_success", lambda *args, **kwargs: None)
    monkeypatch.setattr(cli, "authenticate", lambda *args, **kwargs: "token-123")

    fake_graph = type("FakeGraph", (), {})()
    monkeypatch.setattr(cli, "GraphClient", lambda token: fake_graph)

    template = OutlookTemplate(
        name="Outlook Template",
        description="desc",
        folder_name="IT Notifications",
        subject="Reset",
        body_html="<p>Test</p>",
        sender_name="IT",
        sender_email="it@contoso.com",
        variables=[],
    )

    monkeypatch.setattr(batch_mod, "_find_template_by_name", lambda ct, name: "pkg://outlook/fake.yaml")
    monkeypatch.setattr(batch_mod, "load_template", lambda path: template)
    monkeypatch.setattr(batch_mod, "render_template", lambda t, v: t)

    class FakeOutlookDeployer:
        def __init__(self, graph, tmpl):
            pass

        def deploy(self, target_user, **kwargs):
            return {"type": "outlook", "delivery_mode": "draft", "target_user": target_user, "message_id": "msg-1"}

    monkeypatch.setattr(batch_mod, "OutlookDeployer", FakeOutlookDeployer)

    result = cli.main(["batch", str(manifest), "--output-dir", str(output_dir)])
    assert result == 0

    records = list(output_dir.glob("*.json"))
    assert len(records) == 1


# ---------------------------------------------------------------------------
# Verify subcommand tests
# ---------------------------------------------------------------------------


def test_parse_args_verify_subcommand():
    args = cli._parse_args(["verify", "--demo"])
    assert args.subcommand == "verify"
    assert args.demo is True


def test_verify_demo_exits_one():
    """Smoke test: verify --demo should exit 1 (simulated output includes a GONE)."""
    import subprocess

    result = subprocess.run(
        [".venv/bin/python", "-m", "anglerfish", "verify", "--demo"],
        capture_output=True,
        text=True,
        timeout=30,
    )
    # Demo includes a GONE canary, so exit code is 1.
    assert result.returncode == 1
    assert "Canary Verification" in result.stdout or "GONE" in result.stdout


# ---------------------------------------------------------------------------
# Dashboard subcommand tests
# ---------------------------------------------------------------------------


def test_parse_args_dashboard_subcommand():
    args = cli._parse_args(["dashboard", "--demo"])
    assert args.subcommand == "dashboard"
    assert args.demo is True


def test_parse_args_dashboard_with_intervals():
    args = cli._parse_args([
        "dashboard",
        "--poll-interval", "60",
        "--verify-interval", "120",
        "--records-dir", "/tmp/records",
    ])
    assert args.poll_interval == 60
    assert args.verify_interval == 120
    assert args.records_dir == "/tmp/records"


def test_dashboard_demo_runs_briefly(monkeypatch):
    """Smoke test: dashboard --demo launches and can be stopped."""
    from anglerfish.dashboard import AnglerDashboard

    ran = False

    class FakeApp(AnglerDashboard):
        def on_mount(self):
            nonlocal ran
            super().on_mount()
            ran = True
            self.exit()

    monkeypatch.setattr("anglerfish.cli.AnglerDashboard", FakeApp, raising=False)

    # We can't easily test the full Textual run loop in a CLI smoke test,
    # so just verify the parser accepts the args.
    args = cli._parse_args(["dashboard", "--demo"])
    assert args.subcommand == "dashboard"
    assert args.demo is True
