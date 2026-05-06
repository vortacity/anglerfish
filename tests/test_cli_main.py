"""Unit tests for anglerfish.cli._main helpers and argument parser."""

from __future__ import annotations

import inspect

import pytest
from rich.console import Console

from anglerfish.cli._main import (
    _find_graph_api_error,
    _format_exception_message,
    _parse_args,
    _print_auth_success,
)
from anglerfish.exceptions import DeploymentError, GraphApiError


# ---------------------------------------------------------------------------
# _find_graph_api_error
# ---------------------------------------------------------------------------


class TestFindGraphApiError:
    def test_direct_graph_api_error(self):
        exc = GraphApiError("fail", 403)
        assert _find_graph_api_error(exc) is exc

    def test_chained_via_cause(self):
        graph_exc = GraphApiError("upstream", 500)
        wrapper = DeploymentError("deploy failed")
        wrapper.__cause__ = graph_exc
        assert _find_graph_api_error(wrapper) is graph_exc

    def test_no_graph_error_returns_none(self):
        exc = DeploymentError("plain error")
        assert _find_graph_api_error(exc) is None

    def test_chained_via_context(self):
        graph_exc = GraphApiError("context error", 404)
        wrapper = DeploymentError("outer")
        wrapper.__context__ = graph_exc
        assert _find_graph_api_error(wrapper) is graph_exc


# ---------------------------------------------------------------------------
# _format_exception_message
# ---------------------------------------------------------------------------


class TestFormatExceptionMessage:
    def test_plain_error(self):
        exc = DeploymentError("something broke")
        assert _format_exception_message(exc) == "something broke"

    def test_with_graph_api_error_details(self):
        graph_exc = GraphApiError(
            "Forbidden",
            403,
            method="GET",
            path="/users/me",
            request_id="req-123",
        )
        result = _format_exception_message(graph_exc)
        assert "Forbidden" in result
        assert "GET /users/me" in result
        assert "req-123" in result

    def test_chained_graph_error_includes_details(self):
        graph_exc = GraphApiError(
            "Not Found",
            404,
            method="DELETE",
            path="/items/abc",
            request_id="req-456",
            client_request_id="cli-789",
        )
        wrapper = DeploymentError("cleanup failed")
        wrapper.__cause__ = graph_exc
        result = _format_exception_message(wrapper)
        assert "cleanup failed" in result
        assert "DELETE /items/abc" in result
        assert "req-456" in result
        assert "cli-789" in result

    def test_graph_error_path_only(self):
        graph_exc = GraphApiError("err", 500, path="/users")
        result = _format_exception_message(graph_exc)
        assert "Graph request path: /users" in result


# ---------------------------------------------------------------------------
# _parse_args
# ---------------------------------------------------------------------------


class TestParseArgs:
    def test_version_flag(self):
        args = _parse_args(["--version"])
        assert args.version is True

    def test_canary_type_outlook(self):
        args = _parse_args(["--canary-type", "outlook"])
        assert args.canary_type == "outlook"

    def test_monitor_once(self):
        args = _parse_args(["monitor", "--once"])
        assert args.subcommand == "monitor"
        assert args.once is True

    def test_cleanup(self):
        args = _parse_args(["cleanup", "record.json"])
        assert args.subcommand == "cleanup"
        assert args.record == "record.json"

    def test_cleanup_demo(self):
        args = _parse_args(["cleanup", "--demo", "--non-interactive", "record.json"])
        assert args.subcommand == "cleanup"
        assert args.demo is True
        assert args.non_interactive is True
        assert args.record == "record.json"

    def test_verify_demo(self):
        args = _parse_args(["verify", "--demo"])
        assert args.subcommand == "verify"
        assert args.demo is True

    def test_var_args(self):
        args = _parse_args(["--var", "name=Alice", "--var", "role=Admin"])
        assert args.vars == ["name=Alice", "role=Admin"]

    def test_defaults_no_args(self):
        args = _parse_args([])
        assert args.version is False
        assert args.canary_type is None
        assert args.subcommand is None
        assert args.non_interactive is False
        assert args.dry_run is False
        assert args.demo is False

    def test_verbose_flag(self):
        args = _parse_args(["-v"])
        assert args.verbose is True

    def test_non_interactive_flag(self):
        args = _parse_args(["--non-interactive"])
        assert args.non_interactive is True

    def test_template_and_target(self):
        args = _parse_args(["--template", "MyTemplate", "--target", "user@contoso.com"])
        assert args.template == "MyTemplate"
        assert args.target == "user@contoso.com"

    def test_invalid_canary_type_rejected(self):
        with pytest.raises(SystemExit):
            _parse_args(["--canary-type", "invalid"])

    def test_parse_args_rejects_removed_batch_subcommand(self):
        with pytest.raises(SystemExit):
            _parse_args(["batch", "manifest.yaml"])

    def test_parse_args_rejects_removed_dashboard_subcommand(self):
        with pytest.raises(SystemExit):
            _parse_args(["dashboard"])

    def test_parse_args_rejects_sharepoint_canary_type(self):
        with pytest.raises(SystemExit):
            _parse_args(["--canary-type", "sharepoint"])

    def test_parse_args_rejects_removed_folder_path_flag(self):
        with pytest.raises(SystemExit):
            _parse_args(["--folder-path", "Finance/Restricted"])

    def test_parse_args_rejects_removed_filename_flag(self):
        with pytest.raises(SystemExit):
            _parse_args(["--filename", "bonus_plan.txt"])

    def test_parse_args_help_does_not_advertise_non_outlook_deploy_args(self, capsys):
        with pytest.raises(SystemExit):
            _parse_args(["--help"])
        help_text = capsys.readouterr().out
        assert "site name (SharePoint)" not in help_text
        assert "OneDrive" not in help_text
        assert "--folder-path" not in help_text
        assert "--filename" not in help_text

    def test_monitor_interval(self):
        args = _parse_args(["monitor", "--interval", "120"])
        assert args.interval == 120

    def test_output_json(self):
        args = _parse_args(["--output-json", "/tmp/out.json"])
        assert args.output_json == "/tmp/out.json"


class TestPrintAuthSuccess:
    def test_application_mode_prints_application_success(self):
        console = Console(record=True)
        _print_auth_success(console)
        output = console.export_text()
        assert "application permissions" in output

    def test_application_mode_helper_signature_has_no_auth_mode_param(self):
        parameters = inspect.signature(_print_auth_success).parameters
        assert "auth_mode" not in parameters
