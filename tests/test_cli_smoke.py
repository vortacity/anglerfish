import json
import sys

import pytest

import anglerfish.auth as auth_mod
from anglerfish.cli import deploy as deploy_mod
from anglerfish.cli import main
import anglerfish.cli._main as main_mod
import anglerfish.templates as templates_mod
from anglerfish.models import OutlookTemplate


class _Prompt:
    def __init__(self, value):
        self._value = value

    def ask(self):
        return self._value


def test_main_version_flag():
    assert main(["--version"]) == 0


def test_parse_args_rejects_removed_simulate_flag():
    with pytest.raises(SystemExit):
        main_mod._parse_args(["--simulate"])


def test_parse_args_rejects_removed_batch_subcommand():
    with pytest.raises(SystemExit):
        main_mod._parse_args(["batch", "manifest.yaml"])


def test_parse_args_rejects_removed_dashboard_subcommand():
    with pytest.raises(SystemExit):
        main_mod._parse_args(["dashboard"])


def test_parse_args_rejects_sharepoint_canary_type():
    with pytest.raises(SystemExit):
        main_mod._parse_args(["--canary-type", "sharepoint"])


def test_main_non_interactive_requires_canary_type():
    assert main(["--non-interactive"]) == 1


def test_main_non_interactive_requires_template_for_outlook():
    assert (
        main(
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


def test_main_outlook_flow_still_deploys(monkeypatch):
    monkeypatch.setenv("ANGLERFISH_CLIENT_ID", "client-id")
    monkeypatch.setattr(deploy_mod, "_prompt_auth_setup", lambda *args, **kwargs: "")
    monkeypatch.setattr(deploy_mod, "_print_auth_success", lambda *args, **kwargs: None)
    monkeypatch.setattr(deploy_mod, "authenticate", lambda *args, **kwargs: "token-123")

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
        main_mod,
        "list_templates",
        lambda canary_type: [{"name": "Outlook Template", "description": "desc", "path": "pkg://outlook/test.yaml"}],
    )
    monkeypatch.setattr(main_mod, "load_template", lambda path: template)

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
        deploy_mod.questionary,
        "select",
        lambda message, *args, **kwargs: _Prompt(select_answers[message]),
    )
    monkeypatch.setattr(
        deploy_mod.questionary,
        "text",
        lambda message, *args, **kwargs: _Prompt(text_answers[message]),
    )
    monkeypatch.setattr(
        deploy_mod.questionary,
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

    monkeypatch.setattr(deploy_mod, "GraphClient", FakeGraphClient)
    monkeypatch.setattr(deploy_mod, "OutlookDeployer", FakeOutlookDeployer)

    result = main([])

    assert result == 0
    assert observed["token"] == "token-123"
    assert observed["target_user"] == "victim@contoso.com"
    assert observed["kwargs"] == {"delivery_mode": "draft"}


def test_main_list_returns_zero_when_records_dir_missing(tmp_path):
    missing = tmp_path / "does-not-exist"
    assert main(["list", "--records-dir", str(missing)]) == 0


def test_main_cleanup_outlook_happy_path(monkeypatch, tmp_path):
    record_path = tmp_path / "record.json"
    record_path.write_text("{}", encoding="utf-8")

    monkeypatch.setattr(
        deploy_mod,
        "read_deployment_record",
        lambda path: {
            "type": "outlook",
            "target_user": "user@contoso.com",
            "message_id": "msg-1",
        },
    )
    monkeypatch.setattr(deploy_mod, "_prompt_auth_setup", lambda *args, **kwargs: "")
    monkeypatch.setattr(deploy_mod, "authenticate", lambda *args, **kwargs: "token-123")
    monkeypatch.setattr(deploy_mod, "_print_auth_success", lambda *args, **kwargs: None)

    class FakeGraphClient:
        def __init__(self, token):
            assert token == "token-123"

    monkeypatch.setattr(deploy_mod, "GraphClient", FakeGraphClient)
    monkeypatch.setattr(deploy_mod, "outlook_remove_canary", lambda graph, record: {"removed": "true"})

    status_updates: list[tuple[str, str]] = []
    monkeypatch.setattr(
        deploy_mod,
        "update_deployment_status",
        lambda path, status: status_updates.append((str(path), status)),
    )

    result = main(["cleanup", "--non-interactive", str(record_path)])

    assert result == 0
    assert status_updates == [(str(record_path), "cleaned_up")]


def test_main_outlook_writes_output_json(monkeypatch, tmp_path):
    monkeypatch.setenv("ANGLERFISH_CLIENT_ID", "client-id")
    monkeypatch.setattr(deploy_mod, "_prompt_auth_setup", lambda *args, **kwargs: "")
    monkeypatch.setattr(deploy_mod, "_print_auth_success", lambda *args, **kwargs: None)
    monkeypatch.setattr(deploy_mod, "authenticate", lambda *args, **kwargs: "token-123")

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
        main_mod,
        "list_templates",
        lambda canary_type: [{"name": "Outlook Template", "description": "desc", "path": "pkg://outlook/test.yaml"}],
    )
    monkeypatch.setattr(main_mod, "load_template", lambda path: template)

    select_answers = {
        "Select canary type:": "outlook",
        "Select template:": "pkg://outlook/test.yaml",
        "Select delivery mode:": "send",
    }
    text_answers = {
        "Target mailbox (UPN/email):": "victim@contoso.com",
    }
    monkeypatch.setattr(
        deploy_mod.questionary, "select", lambda message, *args, **kwargs: _Prompt(select_answers[message])
    )
    monkeypatch.setattr(deploy_mod.questionary, "text", lambda message, *args, **kwargs: _Prompt(text_answers[message]))
    monkeypatch.setattr(deploy_mod.questionary, "confirm", lambda *args, **kwargs: _Prompt(True))

    monkeypatch.setattr(deploy_mod, "GraphClient", lambda token: object())

    class FakeOutlookDeployer:
        def __init__(self, graph, template_obj):
            pass

        def deploy(self, target_user: str, **kwargs):
            return {"delivery_mode": "send", "target_user": target_user, "inbox_message_id": "msg-1"}

    monkeypatch.setattr(deploy_mod, "OutlookDeployer", FakeOutlookDeployer)

    output = tmp_path / "record.json"
    result = main(["--output-json", str(output)])

    assert result == 0
    data = json.loads(output.read_text(encoding="utf-8"))
    assert data["canary_type"] == "outlook"
    assert data["status"] == "active"
    assert data["auth_mode"] == "application"


def test_main_delegates_to_outlook_handler(monkeypatch):
    monkeypatch.setattr(main_mod, "_print_banner", lambda *_: None)

    def _fake_list(canary_type):
        return [{"name": "Outlook Template", "description": "desc", "path": "pkg://outlook/test.yaml"}]

    monkeypatch.setattr(main_mod, "list_templates", _fake_list)
    monkeypatch.setattr(templates_mod, "list_templates", _fake_list)
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
    monkeypatch.setattr(main_mod, "load_template", lambda path: template)

    observed: dict[str, object] = {}

    def fake_outlook_handler(args, console, rendered_template, non_interactive, total_steps, cli_var_values):
        observed["template"] = rendered_template
        observed["non_interactive"] = non_interactive
        observed["total_steps"] = total_steps
        observed["cli_var_values"] = cli_var_values
        return 0

    monkeypatch.setattr(deploy_mod, "_run_outlook_deploy", fake_outlook_handler)

    result = main(
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


def test_parse_args_verify_subcommand():
    args = main_mod._parse_args(["verify", "--demo"])
    assert args.subcommand == "verify"
    assert args.demo is True


def test_verify_demo_exits_one():
    import subprocess

    result = subprocess.run(
        [sys.executable, "-m", "anglerfish", "verify", "--demo"],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 1
    assert "Canary Verification" in result.stdout or "GONE" in result.stdout


def test_verify_send_record_returns_error_without_auth(monkeypatch):
    monkeypatch.setattr(
        deploy_mod,
        "read_deployment_record",
        lambda _path: {
            "canary_type": "outlook",
            "delivery_mode": "send",
            "target_user": "alice@contoso.com",
            "inbox_message_id": "msg-123",
            "template_name": "Fake Password Reset",
        },
    )
    auth_calls: list[tuple[tuple[object, ...], dict[str, object]]] = []
    auth_setup_calls: list[tuple[tuple[object, ...], dict[str, object]]] = []

    def _fake_authenticate(*args, **kwargs):
        auth_calls.append((args, kwargs))
        return "token-123"

    def _fake_prompt_auth_setup(*args, **kwargs):
        auth_setup_calls.append((args, kwargs))
        return ""

    monkeypatch.setattr(deploy_mod, "_prompt_auth_setup", _fake_prompt_auth_setup)
    monkeypatch.setattr(deploy_mod, "authenticate", _fake_authenticate)
    monkeypatch.setattr(auth_mod, "authenticate", _fake_authenticate)
    monkeypatch.setattr(
        deploy_mod,
        "GraphClient",
        lambda _token: object(),
    )

    result = main(["verify", "record.json"])

    assert result == 1
    assert auth_setup_calls == []
    assert auth_calls == []


def test_verify_unsupported_record_returns_error_without_auth(monkeypatch):
    monkeypatch.setattr(
        deploy_mod,
        "read_deployment_record",
        lambda _path: {
            "canary_type": "sharepoint",
            "template_name": "Employee Salary Bands",
            "site_name": "HR Site",
        },
    )
    auth_calls: list[tuple[tuple[object, ...], dict[str, object]]] = []
    auth_setup_calls: list[tuple[tuple[object, ...], dict[str, object]]] = []

    def _fake_authenticate(*args, **kwargs):
        auth_calls.append((args, kwargs))
        return "token-123"

    def _fake_prompt_auth_setup(*args, **kwargs):
        auth_setup_calls.append((args, kwargs))
        return ""

    monkeypatch.setattr(deploy_mod, "_prompt_auth_setup", _fake_prompt_auth_setup)
    monkeypatch.setattr(deploy_mod, "authenticate", _fake_authenticate)
    monkeypatch.setattr(auth_mod, "authenticate", _fake_authenticate)
    monkeypatch.setattr(
        deploy_mod,
        "GraphClient",
        lambda _token: object(),
    )

    result = main(["verify", "record.json"])

    assert result == 1
    assert auth_setup_calls == []
    assert auth_calls == []


def test_verify_malformed_draft_record_returns_error_without_auth(monkeypatch):
    monkeypatch.setattr(
        deploy_mod,
        "read_deployment_record",
        lambda _path: {
            "canary_type": "outlook",
            "delivery_mode": "draft",
            "target_user": "alice@contoso.com",
            "template_name": "Fake Password Reset",
            # Missing folder_id
        },
    )
    auth_calls: list[tuple[tuple[object, ...], dict[str, object]]] = []
    auth_setup_calls: list[tuple[tuple[object, ...], dict[str, object]]] = []

    def _fake_authenticate(*args, **kwargs):
        auth_calls.append((args, kwargs))
        return "token-123"

    def _fake_prompt_auth_setup(*args, **kwargs):
        auth_setup_calls.append((args, kwargs))
        return ""

    monkeypatch.setattr(deploy_mod, "_prompt_auth_setup", _fake_prompt_auth_setup)
    monkeypatch.setattr(deploy_mod, "authenticate", _fake_authenticate)
    monkeypatch.setattr(auth_mod, "authenticate", _fake_authenticate)
    monkeypatch.setattr(
        deploy_mod,
        "GraphClient",
        lambda _token: object(),
    )

    result = main(["verify", "record.json"])

    assert result == 1
    assert auth_setup_calls == []
    assert auth_calls == []


def test_deploy_module_keeps_outlook_deployer_available():
    assert deploy_mod.OutlookDeployer is not None


def test_verify_demo_runs_with_src_pythonpath():
    import os
    import subprocess

    env = os.environ.copy()
    env["PYTHONPATH"] = "src"
    result = subprocess.run(
        ["/home/odie/code/deploy/.venv/bin/python", "-m", "anglerfish", "verify", "--demo"],
        capture_output=True,
        text=True,
        timeout=30,
        env=env,
        cwd="/home/odie/code/deploy/.worktrees/anglerfish-outlook-mvp-reset",
    )
    assert result.returncode == 1
    assert "Canary Verification" in result.stdout or "GONE" in result.stdout
