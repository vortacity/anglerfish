"""Unit tests for anglerfish.cli.prompts validators and helpers."""

from __future__ import annotations

import argparse
import os

import pytest
from rich.console import Console

import anglerfish.templates as templates_mod
from anglerfish.cli import deploy as deploy_mod
from anglerfish.templates import find_template_by_name as _find_template_by_name
from anglerfish.cli.prompts import (
    AuthPromptResult,
    _normalize_sharepoint_folder_path,
    _parse_var_args,
    _prompt_auth_setup,
    _validate_email,
    _validate_file_path,
    _validate_non_empty,
    _validate_sharepoint_folder_path,
    _validate_single_filename,
    _validate_subject,
    _validate_variable_value,
)
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
# _validate_single_filename
# ---------------------------------------------------------------------------


class TestValidateSingleFilename:
    def test_valid_filename(self):
        assert _validate_single_filename("report.pdf") is True

    def test_empty(self):
        result = _validate_single_filename("")
        assert isinstance(result, str)
        assert "filename" in result.lower()

    def test_comma_separated(self):
        result = _validate_single_filename("file1.txt,file2.txt")
        assert isinstance(result, str)
        assert "one" in result.lower()

    def test_forward_slash(self):
        result = _validate_single_filename("dir/file.txt")
        assert isinstance(result, str)
        assert "separator" in result.lower()

    def test_backslash(self):
        result = _validate_single_filename("dir\\file.txt")
        assert isinstance(result, str)
        assert "separator" in result.lower()


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
# _validate_sharepoint_folder_path
# ---------------------------------------------------------------------------


class TestValidateSharepointFolderPath:
    def test_valid(self):
        assert _validate_sharepoint_folder_path("HR/Restricted") is True

    def test_empty(self):
        result = _validate_sharepoint_folder_path("")
        assert isinstance(result, str)
        assert "folder path" in result.lower()

    def test_too_long(self):
        result = _validate_sharepoint_folder_path("a" * 401)
        assert isinstance(result, str)
        assert "400" in result


# ---------------------------------------------------------------------------
# _normalize_sharepoint_folder_path
# ---------------------------------------------------------------------------


class TestNormalizeSharepointFolderPath:
    def test_strips_shared_documents_prefix(self):
        assert _normalize_sharepoint_folder_path("Shared Documents/HR/Restricted") == "HR/Restricted"

    def test_strips_documents_prefix(self):
        assert _normalize_sharepoint_folder_path("Documents/Finance") == "Finance"

    def test_no_prefix(self):
        assert _normalize_sharepoint_folder_path("HR/Restricted") == "HR/Restricted"

    def test_empty(self):
        assert _normalize_sharepoint_folder_path("") == ""

    def test_whitespace(self):
        assert _normalize_sharepoint_folder_path("   ") == ""

    def test_case_insensitive_prefix(self):
        assert _normalize_sharepoint_folder_path("shared documents/IT") == "IT"

    def test_strips_leading_trailing_slashes(self):
        assert _normalize_sharepoint_folder_path("/HR/Restricted/") == "HR/Restricted"


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

        assert result == AuthPromptResult(credential_mode="secret")

    def test_prompt_auth_setup_non_interactive_application_certificate_only_returns_certificate(self, monkeypatch):
        args = type("Args", (), {"tenant_id": None, "client_id": None, "credential_mode": "auto"})()
        monkeypatch.setenv("ANGLERFISH_TENANT_ID", "tenant-id")
        monkeypatch.setenv("ANGLERFISH_CLIENT_ID", "client-id")
        monkeypatch.setenv("ANGLERFISH_CLIENT_CERT_PFX_PATH", "/tmp/client.pfx")

        result = _prompt_auth_setup(args, console=None, auth_mode="application", non_interactive=True)

        assert result == AuthPromptResult(credential_mode="certificate")

    def test_prompt_auth_setup_non_interactive_application_mixed_defaults_to_secret(self, monkeypatch):
        args = type("Args", (), {"tenant_id": None, "client_id": None, "credential_mode": "auto"})()
        monkeypatch.setenv("ANGLERFISH_TENANT_ID", "tenant-id")
        monkeypatch.setenv("ANGLERFISH_CLIENT_ID", "client-id")
        monkeypatch.setenv("ANGLERFISH_CLIENT_SECRET", "secret")
        monkeypatch.setenv("ANGLERFISH_CLIENT_CERT_PRIVATE_KEY_PATH", "/tmp/client.key")
        monkeypatch.setenv("ANGLERFISH_CLIENT_CERT_THUMBPRINT", "ABCDEF")

        result = _prompt_auth_setup(args, console=None, auth_mode="application", non_interactive=True)

        assert result == AuthPromptResult(credential_mode="secret")

    def test_prompt_auth_setup_rejects_delegated_auth_mode(self, monkeypatch):
        args = type("Args", (), {"tenant_id": None, "client_id": None, "credential_mode": None})()
        monkeypatch.setenv("ANGLERFISH_TENANT_ID", "tenant-id")
        monkeypatch.setenv("ANGLERFISH_CLIENT_ID", "client-id")
        monkeypatch.setenv("ANGLERFISH_CLIENT_SECRET", "secret")
        with pytest.raises(AuthenticationError, match="application auth"):
            _prompt_auth_setup(args, console=None, auth_mode="delegated", non_interactive=True)


def test_verify_prompted_secret_is_cleared_after_auth(monkeypatch):
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
        lambda _path: {
            "canary_type": "outlook",
            "delivery_mode": "draft",
            "template_name": "Fake Password Reset",
            "target_user": "alice@contoso.com",
            "folder_id": "folder-123",
        },
    )
    monkeypatch.setattr(deploy_mod, "GraphClient", lambda _token: object())

    def _fake_prompt_auth_setup(*_args, **_kwargs):
        os.environ["ANGLERFISH_CLIENT_SECRET"] = "prompted-secret"
        return AuthPromptResult(
            credential_mode="secret",
            clear_env_vars=("ANGLERFISH_CLIENT_SECRET",),
        )

    def _fake_authenticate(*_args, **_kwargs):
        assert os.environ.get("ANGLERFISH_CLIENT_SECRET") == "prompted-secret"
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
