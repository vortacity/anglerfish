"""Unit tests for anglerfish.cli.prompts validators and helpers."""

from __future__ import annotations

import argparse
import os

import pytest
import questionary
from rich.console import Console

import anglerfish.templates as templates_mod
from anglerfish.inventory import DeploymentRecord
from anglerfish.cli import deploy as deploy_mod
from anglerfish.templates import find_template_by_name as _find_template_by_name
from anglerfish.auth import AuthConfig
from anglerfish.cli.prompts import (
    _parse_var_args,
    _prompt_auth_setup,
    _render_deploy_template,
    _validate_email,
    _validate_file_path,
    _validate_non_empty,
    _validate_subject,
    _validate_variable_value,
)
from anglerfish.models import OutlookTemplate
from anglerfish.exceptions import DeploymentError
from anglerfish.exceptions import AuthenticationError, TemplateError
from anglerfish.verify import VerifyResult, VerifyStatus


# ---------------------------------------------------------------------------
# _validate_email
# ---------------------------------------------------------------------------


class TestValidateEmail:
    def test_valid_email(self):
        assert _validate_email("user@domain.com") is True

    def test_invalid_email_no_at(self):
        result = _validate_email("userdomain.com")
        assert isinstance(result, str)
        assert "valid email" in result

    def test_empty_string(self):
        result = _validate_email("")
        assert isinstance(result, str)

    def test_whitespace_stripped(self):
        assert _validate_email("  user@domain.com  ") is True

    def test_missing_tld(self):
        result = _validate_email("user@domain")
        assert isinstance(result, str)


# ---------------------------------------------------------------------------
# _validate_non_empty
# ---------------------------------------------------------------------------


class TestValidateNonEmpty:
    def test_non_empty(self):
        assert _validate_non_empty("hello") is True

    def test_empty(self):
        result = _validate_non_empty("")
        assert isinstance(result, str)
        assert "required" in result.lower()

    def test_whitespace_only(self):
        result = _validate_non_empty("   ")
        assert isinstance(result, str)


# ---------------------------------------------------------------------------
# _validate_file_path
# ---------------------------------------------------------------------------


class TestValidateFilePath:
    def test_existing_file(self, tmp_path):
        f = tmp_path / "test.txt"
        f.write_text("data")
        assert _validate_file_path(str(f)) is True

    def test_nonexistent_file(self):
        result = _validate_file_path("/nonexistent/file.txt")
        assert isinstance(result, str)
        assert "valid file path" in result


# ---------------------------------------------------------------------------
# _validate_subject
# ---------------------------------------------------------------------------


class TestValidateSubject:
    def test_valid_subject(self):
        assert _validate_subject("Meeting Notes") is True

    def test_empty(self):
        result = _validate_subject("")
        assert isinstance(result, str)
        assert "required" in result.lower()

    def test_too_long_256(self):
        result = _validate_subject("x" * 256)
        assert isinstance(result, str)
        assert "255" in result

    def test_max_length_255(self):
        assert _validate_subject("x" * 255) is True


# ---------------------------------------------------------------------------
# _validate_variable_value
# ---------------------------------------------------------------------------


class TestValidateVariableValue:
    def test_valid_value(self):
        assert _validate_variable_value("hello") is True

    def test_too_long_501(self):
        result = _validate_variable_value("x" * 501)
        assert isinstance(result, str)
        assert "500" in result

    def test_max_length_500(self):
        assert _validate_variable_value("x" * 500) is True


# ---------------------------------------------------------------------------
# _parse_var_args
# ---------------------------------------------------------------------------


class TestParseVarArgs:
    def test_single_var(self):
        assert _parse_var_args(["name=Alice"]) == {"name": "Alice"}

    def test_multiple_vars(self):
        result = _parse_var_args(["name=Alice", "role=Admin"])
        assert result == {"name": "Alice", "role": "Admin"}

    def test_value_with_equals_sign(self):
        result = _parse_var_args(["query=a=b"])
        assert result == {"query": "a=b"}

    def test_missing_equals_raises_template_error(self):
        with pytest.raises(TemplateError, match="KEY=VALUE"):
            _parse_var_args(["no-equals"])

    def test_empty_key_raises_template_error(self):
        with pytest.raises(TemplateError, match="Key cannot be empty"):
            _parse_var_args(["=value"])


# ---------------------------------------------------------------------------
# _find_template_by_name
# ---------------------------------------------------------------------------


class TestFindTemplateByName:
    def test_found(self, monkeypatch):
        monkeypatch.setattr(
            templates_mod,
            "list_templates",
            lambda ct: [{"name": "Outlook Template", "path": "pkg://outlook/test.yaml"}],
        )
        assert _find_template_by_name("outlook", "Outlook Template") == "pkg://outlook/test.yaml"

    def test_case_insensitive(self, monkeypatch):
        monkeypatch.setattr(
            templates_mod,
            "list_templates",
            lambda ct: [{"name": "Outlook Template", "path": "pkg://outlook/test.yaml"}],
        )
        assert _find_template_by_name("outlook", "outlook template") == "pkg://outlook/test.yaml"

    def test_not_found_raises_template_error(self, monkeypatch):
        monkeypatch.setattr(
            templates_mod,
            "list_templates",
            lambda ct: [{"name": "Outlook Template", "path": "pkg://outlook/test.yaml"}],
        )
        with pytest.raises(TemplateError, match="not found"):
            _find_template_by_name("outlook", "Missing Template")

    def test_no_templates_raises_template_error(self, monkeypatch):
        monkeypatch.setattr(templates_mod, "list_templates", lambda ct: [])
        with pytest.raises(TemplateError, match="No outlook templates"):
            _find_template_by_name("outlook", "Any")


class TestPromptAuthSetup:
    def test_prompt_auth_setup_non_interactive_application_secret_only_returns_secret(self, monkeypatch):
        args = type("Args", (), {"tenant_id": None, "client_id": None, "credential_mode": "auto"})()
        monkeypatch.setenv("ANGLERFISH_TENANT_ID", "tenant-id")
        monkeypatch.setenv("ANGLERFISH_CLIENT_ID", "client-id")
        monkeypatch.setenv("ANGLERFISH_CLIENT_SECRET", "secret")

        result = _prompt_auth_setup(args, console=None, auth_mode="application", non_interactive=True)

        assert result == AuthConfig(
            tenant_id="tenant-id", client_id="client-id", credential_mode="secret", client_secret="secret"
        )

    def test_prompt_auth_setup_non_interactive_application_certificate_only_returns_certificate(self, monkeypatch):
        args = type("Args", (), {"tenant_id": None, "client_id": None, "credential_mode": "auto"})()
        monkeypatch.setenv("ANGLERFISH_TENANT_ID", "tenant-id")
        monkeypatch.setenv("ANGLERFISH_CLIENT_ID", "client-id")
        monkeypatch.setenv("ANGLERFISH_CLIENT_CERT_PFX_PATH", "/tmp/client.pfx")

        result = _prompt_auth_setup(args, console=None, auth_mode="application", non_interactive=True)

        assert result is not None
        assert result.credential_mode == "certificate"
        assert result.cert_pfx_path == "/tmp/client.pfx"

    def test_prompt_auth_setup_non_interactive_application_mixed_defaults_to_secret(self, monkeypatch):
        args = type("Args", (), {"tenant_id": None, "client_id": None, "credential_mode": "auto"})()
        monkeypatch.setenv("ANGLERFISH_TENANT_ID", "tenant-id")
        monkeypatch.setenv("ANGLERFISH_CLIENT_ID", "client-id")
        monkeypatch.setenv("ANGLERFISH_CLIENT_SECRET", "secret")
        monkeypatch.setenv("ANGLERFISH_CLIENT_CERT_PRIVATE_KEY_PATH", "/tmp/client.key")
        monkeypatch.setenv("ANGLERFISH_CLIENT_CERT_THUMBPRINT", "ABCDEF")

        result = _prompt_auth_setup(args, console=None, auth_mode="application", non_interactive=True)

        assert result is not None
        assert result.credential_mode == "secret"

    def test_prompt_auth_setup_rejects_delegated_auth_mode(self, monkeypatch):
        args = type("Args", (), {"tenant_id": None, "client_id": None, "credential_mode": None})()
        monkeypatch.setenv("ANGLERFISH_TENANT_ID", "tenant-id")
        monkeypatch.setenv("ANGLERFISH_CLIENT_ID", "client-id")
        monkeypatch.setenv("ANGLERFISH_CLIENT_SECRET", "secret")
        with pytest.raises(AuthenticationError, match="application auth"):
            _prompt_auth_setup(args, console=None, auth_mode="delegated", non_interactive=True)

    def test_prompt_auth_setup_keeps_prompted_passphrase_out_of_env(self, monkeypatch, tmp_path):
        args = type("Args", (), {"tenant_id": None, "client_id": None, "credential_mode": "certificate"})()
        monkeypatch.setenv("ANGLERFISH_TENANT_ID", "tenant-id")
        monkeypatch.setenv("ANGLERFISH_CLIENT_ID", "client-id")
        monkeypatch.setenv("ANGLERFISH_CLIENT_CERT_PASSPHRASE", "existing-passphrase")

        pfx_path = tmp_path / "client.pfx"
        pfx_path.write_text("fake-pfx", encoding="utf-8")

        answers = iter(["pfx", str(pfx_path), "prompted-passphrase"])

        class _FakePrompt:
            def __init__(self, answer):
                self._answer = answer

            def ask(self):
                return self._answer

        monkeypatch.setattr(questionary, "select", lambda *args, **kwargs: _FakePrompt(next(answers)))
        monkeypatch.setattr(questionary, "text", lambda *args, **kwargs: _FakePrompt(next(answers)))
        monkeypatch.setattr(questionary, "password", lambda *args, **kwargs: _FakePrompt(next(answers)))

        result = _prompt_auth_setup(args, console=Console(file=None, force_terminal=False))

        assert result is not None
        assert result.credential_mode == "certificate"
        assert result.cert_passphrase == "prompted-passphrase"
        # The environment is an input, never an output.
        assert os.environ["ANGLERFISH_CLIENT_CERT_PASSPHRASE"] == "existing-passphrase"

    def test_prompt_auth_setup_interactive_prompts_for_secret(self, monkeypatch):
        args = type("Args", (), {"tenant_id": None, "client_id": None, "credential_mode": "auto"})()
        monkeypatch.setenv("ANGLERFISH_TENANT_ID", "tenant-id")
        monkeypatch.setenv("ANGLERFISH_CLIENT_ID", "client-id")
        for var in (
            "ANGLERFISH_CLIENT_SECRET",
            "ANGLERFISH_CLIENT_CERT_PFX_PATH",
            "ANGLERFISH_CLIENT_CERT_PRIVATE_KEY_PATH",
            "ANGLERFISH_CLIENT_CERT_PUBLIC_CERT_PATH",
            "ANGLERFISH_CLIENT_CERT_THUMBPRINT",
        ):
            monkeypatch.delenv(var, raising=False)

        answers = iter(["secret", "prompted-secret"])

        class _FakePrompt:
            def ask(self):
                return next(answers)

        monkeypatch.setattr(questionary, "select", lambda *a, **k: _FakePrompt())
        monkeypatch.setattr(questionary, "password", lambda *a, **k: _FakePrompt())

        result = _prompt_auth_setup(args, console=Console(file=None, force_terminal=False))

        assert result.credential_mode == "secret"
        assert result.client_secret == "prompted-secret"
        # The prompted secret never enters the process environment.
        assert "ANGLERFISH_CLIENT_SECRET" not in os.environ

    def test_prompt_auth_setup_interactive_both_present_selects_certificate(self, monkeypatch):
        args = type("Args", (), {"tenant_id": None, "client_id": None, "credential_mode": "auto"})()
        monkeypatch.setenv("ANGLERFISH_TENANT_ID", "tenant-id")
        monkeypatch.setenv("ANGLERFISH_CLIENT_ID", "client-id")
        monkeypatch.setenv("ANGLERFISH_CLIENT_SECRET", "secret")
        monkeypatch.setenv("ANGLERFISH_CLIENT_CERT_PFX_PATH", "/tmp/client.pfx")  # noqa: S108 - not opened here

        class _FakePrompt:
            def ask(self):
                return "certificate"

        monkeypatch.setattr(questionary, "select", lambda *a, **k: _FakePrompt())

        result = _prompt_auth_setup(args, console=Console(file=None, force_terminal=False))

        assert result.credential_mode == "certificate"

    def test_prompt_auth_setup_cancellation_returns_none(self, monkeypatch):
        args = type("Args", (), {"tenant_id": None, "client_id": None, "credential_mode": "auto"})()
        monkeypatch.setenv("ANGLERFISH_TENANT_ID", "tenant-id")
        monkeypatch.setenv("ANGLERFISH_CLIENT_ID", "client-id")
        for var in (
            "ANGLERFISH_CLIENT_SECRET",
            "ANGLERFISH_CLIENT_CERT_PFX_PATH",
            "ANGLERFISH_CLIENT_CERT_PRIVATE_KEY_PATH",
            "ANGLERFISH_CLIENT_CERT_PUBLIC_CERT_PATH",
            "ANGLERFISH_CLIENT_CERT_THUMBPRINT",
        ):
            monkeypatch.delenv(var, raising=False)

        class _FakePrompt:
            def ask(self):
                return None  # user cancelled (Ctrl-C / Esc)

        monkeypatch.setattr(questionary, "select", lambda *a, **k: _FakePrompt())

        result = _prompt_auth_setup(args, console=Console(file=None, force_terminal=False))

        assert result is None


def test_verify_prompted_secret_never_enters_env(monkeypatch):
    args = argparse.Namespace(
        demo=False,
        record="record.json",
        records_dir=None,
        tenant_id=None,
        client_id=None,
        credential_mode="secret",
    )
    monkeypatch.setenv("ANGLERFISH_TENANT_ID", "tenant-id")
    monkeypatch.setenv("ANGLERFISH_CLIENT_ID", "client-id")
    monkeypatch.delenv("ANGLERFISH_CLIENT_SECRET", raising=False)
    monkeypatch.setattr(
        deploy_mod,
        "read_deployment_record",
        lambda _path: DeploymentRecord.from_dict(
            {
                "canary_type": "outlook",
                "delivery_mode": "draft",
                "template_name": "Fake Password Reset",
                "target_user": "alice@contoso.com",
                "folder_id": "folder-123",
            }
        ),
    )
    monkeypatch.setattr(deploy_mod, "GraphClient", lambda _token: object())

    def _fake_prompt_auth_setup(*_args, **_kwargs):
        return AuthConfig(credential_mode="secret", client_secret="prompted-secret")

    def _fake_authenticate(*_args, **_kwargs):
        auth_config = _kwargs.get("auth_config")
        assert auth_config is not None and auth_config.client_secret == "prompted-secret"
        assert "ANGLERFISH_CLIENT_SECRET" not in os.environ
        return "token-123"

    monkeypatch.setattr(deploy_mod, "_prompt_auth_setup", _fake_prompt_auth_setup)
    monkeypatch.setattr(deploy_mod, "authenticate", _fake_authenticate)
    monkeypatch.setattr(
        "anglerfish.verify.run_verify",
        lambda _records, _graph: [
            VerifyResult(
                canary_type="outlook",
                template_name="Fake Password Reset",
                target="alice@contoso.com",
                status=VerifyStatus.OK,
            )
        ],
    )

    rc = deploy_mod._run_verify(args, Console(file=None, force_terminal=False))
    assert rc == 0
    assert "ANGLERFISH_CLIENT_SECRET" not in os.environ


def test_verify_prompted_passphrase_leaves_env_value_untouched(monkeypatch):
    args = argparse.Namespace(
        demo=False,
        record="record.json",
        records_dir=None,
        tenant_id=None,
        client_id=None,
        credential_mode="certificate",
    )
    monkeypatch.setenv("ANGLERFISH_TENANT_ID", "tenant-id")
    monkeypatch.setenv("ANGLERFISH_CLIENT_ID", "client-id")
    monkeypatch.setenv("ANGLERFISH_CLIENT_CERT_PASSPHRASE", "existing-passphrase")
    monkeypatch.setattr(
        deploy_mod,
        "read_deployment_record",
        lambda _path: DeploymentRecord.from_dict(
            {
                "canary_type": "outlook",
                "delivery_mode": "draft",
                "template_name": "Fake Password Reset",
                "target_user": "alice@contoso.com",
                "folder_id": "folder-123",
            }
        ),
    )
    monkeypatch.setattr(deploy_mod, "GraphClient", lambda _token: object())

    def _fake_prompt_auth_setup(*_args, **_kwargs):
        return AuthConfig(credential_mode="certificate", cert_passphrase="prompted-passphrase")

    def _fake_authenticate(*_args, **_kwargs):
        auth_config = _kwargs.get("auth_config")
        assert auth_config is not None and auth_config.cert_passphrase == "prompted-passphrase"
        assert os.environ.get("ANGLERFISH_CLIENT_CERT_PASSPHRASE") == "existing-passphrase"
        return "token-123"

    monkeypatch.setattr(deploy_mod, "_prompt_auth_setup", _fake_prompt_auth_setup)
    monkeypatch.setattr(deploy_mod, "authenticate", _fake_authenticate)
    monkeypatch.setattr(
        "anglerfish.verify.run_verify",
        lambda _records, _graph: [
            VerifyResult(
                canary_type="outlook",
                template_name="Fake Password Reset",
                target="alice@contoso.com",
                status=VerifyStatus.OK,
            )
        ],
    )

    rc = deploy_mod._run_verify(args, Console(file=None, force_terminal=False))
    assert rc == 0
    assert os.environ["ANGLERFISH_CLIENT_CERT_PASSPHRASE"] == "existing-passphrase"


def _template_with_vars():
    return OutlookTemplate(
        name="Var Template",
        description="d",
        folder_name="F",
        subject="Hi ${who}",
        body_html="<p>${who} owes ${amount}</p>",
        sender_name="S",
        sender_email="s@c.com",
        variables=[{"name": "who", "default": "User"}, {"name": "amount"}],
    )


def test_render_deploy_template_non_interactive_uses_cli_vars_and_defaults():
    rendered = _render_deploy_template(
        _template_with_vars(),
        canary_type="outlook",
        console=Console(file=None, force_terminal=False),
        non_interactive=True,
        cli_var_values={"amount": "$100"},
    )
    assert rendered is not None
    assert rendered.subject == "Hi User"
    assert "$100" in rendered.body_html


def test_render_deploy_template_warns_on_unknown_var_keys(capsys):
    """A typo'd --var key must be surfaced, not silently dropped."""
    rendered = _render_deploy_template(
        _template_with_vars(),
        canary_type="outlook",
        console=Console(force_terminal=False),
        non_interactive=True,
        cli_var_values={"amount": "$100", "whoo": "typo"},
    )
    assert rendered is not None
    out = capsys.readouterr().out
    assert "whoo" in out
    assert "Unknown" in out or "unknown" in out


def test_render_deploy_template_non_interactive_missing_required_var_raises():
    with pytest.raises(DeploymentError, match="amount"):
        _render_deploy_template(
            _template_with_vars(),
            canary_type="outlook",
            console=Console(file=None, force_terminal=False),
            non_interactive=True,
            cli_var_values={},  # 'amount' has no default and no override
        )


def test_render_deploy_template_interactive_prompts_for_values(monkeypatch):
    answers = {"who": "Adele", "amount": "$200"}

    class _FakePrompt:
        def __init__(self, message):
            # questionary.text is called with the variable description/name as message
            self._key = "amount" if "amount" in message.lower() else "who"

        def ask(self):
            return answers[self._key]

    monkeypatch.setattr(questionary, "text", lambda message, *a, **k: _FakePrompt(message))
    rendered = _render_deploy_template(
        _template_with_vars(),
        canary_type="outlook",
        console=Console(file=None, force_terminal=False),
        non_interactive=False,
        cli_var_values={},
    )
    assert rendered is not None
    assert rendered.subject == "Hi Adele"
    assert "$200" in rendered.body_html


def test_render_deploy_template_interactive_cancel_returns_none(monkeypatch):
    class _FakePrompt:
        def ask(self):
            return None  # cancelled

    monkeypatch.setattr(questionary, "text", lambda *a, **k: _FakePrompt())
    rendered = _render_deploy_template(
        _template_with_vars(),
        canary_type="outlook",
        console=Console(file=None, force_terminal=False),
        non_interactive=False,
        cli_var_values={},
    )
    assert rendered is None
