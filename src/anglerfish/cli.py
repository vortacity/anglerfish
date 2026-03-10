"""Interactive CLI for canary deployment."""

from __future__ import annotations

import argparse
import dataclasses
import datetime
import logging
import os
import re
import sys
from pathlib import Path
from typing import Sequence
from urllib.parse import unquote

import questionary
from questionary import Style
from rich import box
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from . import __version__
from .auth import authenticate, authenticate_management_api
from .deployers.onedrive import OneDriveDeployer
from .deployers.onedrive import remove_canary as onedrive_remove_canary
from .deployers.outlook import OutlookDeployer
from .deployers.outlook import remove_canary as outlook_remove_canary
from .deployers.sharepoint import SharePointDeployer
from .deployers.sharepoint import remove_canary as sharepoint_remove_canary
from .exceptions import (
    AnglerfishError,
    AuditApiError,
    AuthenticationError,
    DeploymentError,
    GraphApiError,
    MonitorError,
    TemplateError,
)
from .graph import GraphClient
from .inventory import read_deployment_record, update_deployment_status, write_deployment_record
from .models import OneDriveTemplate, OutlookTemplate, SharePointTemplate
from .templates import list_templates, load_template, render_template

_EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

_STYLE = Style(
    [
        ("qmark", "fg:#5f8fd4 bold"),
        ("question", "bold"),
        ("answer", "fg:#61afef bold"),
        ("pointer", "fg:#61afef bold"),
        ("highlighted", "fg:#61afef bold"),
        ("selected", "fg:#98c379"),
        ("instruction", "fg:#7f848e italic"),
        ("text", ""),
        ("separator", "fg:#7f848e"),
        ("disabled", "fg:#7f848e"),
    ]
)

_QMARK = "\u2022"
_POINTER = ">"
_SHAREPOINT_LIBRARY_PREFIXES = {"shared documents", "documents"}


def _validate_email(value: str) -> bool | str:
    candidate = value.strip()
    if _EMAIL_PATTERN.match(candidate):
        return True
    return "Enter a valid email address (example: user@domain.com)."


def _validate_non_empty(value: str) -> bool | str:
    if value.strip():
        return True
    return "This value is required."


def _validate_file_path(value: str) -> bool | str:
    if Path(value.strip()).is_file():
        return True
    return "Enter a valid file path."


def _validate_single_filename(value: str) -> bool | str:
    filename = value.strip()
    if not filename:
        return "Enter a filename."
    if "," in filename:
        return "Enter exactly one filename."
    if "/" in filename or "\\" in filename:
        return "Filename must not contain path separators."
    return True


def _normalize_sharepoint_folder_path(value: str) -> str:
    segments: list[str] = []
    for raw_segment in value.strip().strip("/").split("/"):
        segment = raw_segment.strip()
        if segment:
            segments.append(segment)

    if not segments:
        return ""

    first_segment = unquote(segments[0]).strip().casefold()
    if first_segment in _SHAREPOINT_LIBRARY_PREFIXES:
        segments = segments[1:]

    return "/".join(segments)


def _validate_sharepoint_folder_path(value: str) -> bool | str:
    normalized = _normalize_sharepoint_folder_path(value)
    if not normalized:
        return "Enter a folder path under the site (example: HR/Restricted)."
    if len(normalized) > 400:
        return "Folder path must not exceed 400 characters."
    return True


def _validate_subject(value: str) -> bool | str:
    if not value.strip():
        return "This value is required."
    if len(value.strip()) > 255:
        return "Subject must not exceed 255 characters."
    return True


def _validate_variable_value(value: str) -> bool | str:
    if len(value) > 500:
        return "Variable value must not exceed 500 characters."
    return True


def _find_template_by_name(canary_type: str, template_name: str) -> str:
    """Find a template path by name (case-insensitive). Raises TemplateError on failure."""
    available = list_templates(canary_type)
    if not available:
        raise TemplateError(f"No {canary_type} templates found.")
    name_lower = template_name.casefold()
    matches = [t for t in available if t["name"].casefold() == name_lower]
    if not matches:
        names = ", ".join(repr(t["name"]) for t in available)
        raise TemplateError(f"Template {template_name!r} not found for {canary_type}. Available: {names}")
    if len(matches) > 1:
        raise TemplateError(f"Multiple templates named {template_name!r} found for {canary_type}.")
    return matches[0]["path"]


def _parse_var_args(var_args: list[str]) -> dict[str, str]:
    """Parse a list of 'KEY=VALUE' strings into a dict."""
    result: dict[str, str] = {}
    for arg in var_args:
        if "=" not in arg:
            raise TemplateError(f"Invalid --var argument {arg!r}. Expected KEY=VALUE format.")
        key, _, value = arg.partition("=")
        key = key.strip()
        if not key:
            raise TemplateError(f"Invalid --var argument {arg!r}. Key cannot be empty.")
        result[key] = value
    return result


def _search_sharepoint_sites(graph: GraphClient, search_term: str) -> list[dict[str, str]]:
    try:
        response = graph.get("/sites", params={"search": search_term})
    except GraphApiError as exc:
        raise DeploymentError(f"SharePoint site discovery failed: {exc}") from exc

    raw_sites = response.get("value", [])
    if not isinstance(raw_sites, list):
        return []

    sites: list[dict[str, str]] = []
    seen_ids: set[str] = set()
    for raw in raw_sites:
        if not isinstance(raw, dict):
            continue

        site_id = str(raw.get("id", "")).strip()
        if not site_id or site_id in seen_ids:
            continue
        seen_ids.add(site_id)

        display_name = str(raw.get("displayName", "")).strip()
        short_name = str(raw.get("name", "")).strip()
        web_url = str(raw.get("webUrl", "")).strip()
        site_name = display_name or short_name or site_id

        if web_url:
            label = f"{site_name} ({web_url})"
        elif short_name and short_name != site_name:
            label = f"{site_name} ({short_name})"
        else:
            label = site_name

        sites.append(
            {
                "id": site_id,
                "name": site_name,
                "label": label,
            }
        )

    return sites


def _parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Deploy Microsoft 365 canary artifacts.")
    parser.add_argument("--version", action="store_true", help="Print version and exit.")
    parser.add_argument(
        "--tenant-id",
        default=None,
        help="Microsoft Entra tenant ID. Overrides ANGLERFISH_TENANT_ID for this run.",
    )
    parser.add_argument(
        "--client-id",
        default=None,
        help="Microsoft Entra application (client) ID. Overrides ANGLERFISH_CLIENT_ID for this run.",
    )
    parser.add_argument(
        "--credential-mode",
        choices=("auto", "secret", "certificate"),
        default=None,
        help="Credential type for application auth. Overrides ANGLERFISH_APP_CREDENTIAL_MODE.",
    )
    parser.add_argument(
        "--canary-type",
        choices=("outlook", "sharepoint", "onedrive"),
        default=None,
        help="Canary type. Skips canary type prompt when provided.",
    )
    # Non-interactive / automation mode flags
    parser.add_argument(
        "--non-interactive",
        action="store_true",
        help="Read all parameters from CLI args and env vars without interactive prompts.",
    )
    parser.add_argument(
        "--template",
        default=None,
        metavar="NAME",
        help="Template name (case-insensitive). Required in --non-interactive mode.",
    )
    parser.add_argument(
        "--target",
        default=None,
        metavar="VALUE",
        help=("Deployment target: mailbox UPN (Outlook), site name (SharePoint), or UPN (OneDrive)."),
    )
    parser.add_argument(
        "--delivery-mode",
        choices=("draft", "send"),
        default=None,
        dest="delivery_mode",
        help="Delivery mode: 'draft' or 'send' for Outlook.",
    )
    parser.add_argument(
        "--folder-path",
        default=None,
        metavar="PATH",
        dest="folder_path",
        help="SharePoint or OneDrive destination folder path (e.g. HR/Restricted).",
    )
    parser.add_argument(
        "--filename",
        default=None,
        metavar="NAME",
        help="SharePoint or OneDrive canary filename.",
    )
    parser.add_argument(
        "--var",
        action="append",
        metavar="KEY=VALUE",
        dest="vars",
        default=[],
        help="Template variable override in KEY=VALUE format (repeatable).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        dest="dry_run",
        help=(
            "Validate configuration, authenticate, and show deployment plan without performing any write operations."
        ),
    )
    parser.add_argument(
        "--output-json",
        default=None,
        metavar="PATH",
        dest="output_json",
        help="Write deployment record JSON to this file path after a successful deployment.",
    )
    parser.add_argument(
        "--demo",
        action="store_true",
        help="Run in offline demo mode. Skips authentication and Graph API calls.",
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Enable debug logging for API calls and auth flow.",
    )

    subparsers = parser.add_subparsers(dest="subcommand")

    cleanup_parser = subparsers.add_parser("cleanup", help="Remove a deployed canary artifact.")
    cleanup_parser.add_argument("record", metavar="RECORD", help="Path to deployment record JSON.")
    cleanup_parser.add_argument(
        "--non-interactive",
        action="store_true",
        help="Skip confirmation prompt.",
    )
    cleanup_parser.add_argument(
        "--tenant-id",
        default=None,
        help="Microsoft Entra tenant ID. Overrides ANGLERFISH_TENANT_ID for this run.",
    )
    cleanup_parser.add_argument(
        "--client-id",
        default=None,
        help="Microsoft Entra application (client) ID. Overrides ANGLERFISH_CLIENT_ID for this run.",
    )
    cleanup_parser.add_argument(
        "--credential-mode",
        choices=("auto", "secret", "certificate"),
        default=None,
        help="Credential type for application auth. Overrides ANGLERFISH_APP_CREDENTIAL_MODE.",
    )
    list_parser = subparsers.add_parser("list", help="List deployed canary artifacts.")
    list_parser.add_argument(
        "--records-dir",
        default=str(Path.home() / ".anglerfish" / "records"),
        metavar="DIR",
        dest="records_dir",
        help=("Directory containing deployment record JSON files. Default: ~/.anglerfish/records/"),
    )

    monitor_parser = subparsers.add_parser("monitor", help="Monitor audit logs for canary access events.")
    monitor_parser.add_argument(
        "--records-dir",
        default=str(Path.home() / ".anglerfish" / "records"),
        metavar="DIR",
        dest="records_dir",
        help="Directory containing deployment record JSON files.",
    )
    monitor_parser.add_argument(
        "--tenant-id",
        default=None,
        help="Microsoft Entra tenant ID. Overrides ANGLERFISH_TENANT_ID.",
    )
    monitor_parser.add_argument(
        "--client-id",
        default=None,
        help="Microsoft Entra application (client) ID. Overrides ANGLERFISH_CLIENT_ID.",
    )
    monitor_parser.add_argument(
        "--credential-mode",
        choices=("auto", "secret", "certificate"),
        default=None,
        help="Credential type for application auth.",
    )
    monitor_parser.add_argument(
        "--interval",
        type=int,
        default=300,
        metavar="SECONDS",
        help="Poll interval in seconds (default: 300).",
    )
    monitor_parser.add_argument(
        "--once",
        action="store_true",
        help="Poll once and exit instead of running a continuous loop.",
    )
    monitor_parser.add_argument(
        "--exclude-app-id",
        action="append",
        default=[],
        metavar="APP_ID",
        dest="exclude_app_ids",
        help="App/client IDs to exclude from matching (repeatable).",
    )
    monitor_parser.add_argument(
        "--state-file",
        default=None,
        metavar="PATH",
        dest="state_file",
        help="Persistent state file (default: ~/.anglerfish/monitor-state.json).",
    )
    monitor_parser.add_argument(
        "--alert-log",
        default=None,
        metavar="PATH",
        dest="alert_log",
        help="JSONL alert log file.",
    )
    monitor_parser.add_argument(
        "--slack-webhook-url",
        default=None,
        metavar="URL",
        dest="slack_webhook_url",
        help="Slack incoming webhook URL for alert notifications.",
    )
    monitor_parser.add_argument(
        "--no-console",
        action="store_true",
        default=False,
        dest="no_console",
        help="Suppress Rich console alert output (daemon mode).",
    )
    monitor_parser.add_argument(
        "--demo",
        action="store_true",
        default=False,
        help="Print a simulated alert and exit (no auth required).",
    )
    monitor_parser.add_argument(
        "--count",
        type=int,
        default=1,
        metavar="N",
        dest="demo_count",
        help="Number of simulated alerts to print in --demo mode (default: 1).",
    )

    batch_parser = subparsers.add_parser("batch", help="Deploy multiple canaries from a YAML manifest.")
    batch_parser.add_argument("manifest", metavar="MANIFEST", help="Path to batch manifest YAML file.")
    batch_parser.add_argument(
        "--output-dir",
        default=str(Path.home() / ".anglerfish" / "records"),
        metavar="DIR",
        dest="output_dir",
        help="Directory for deployment record JSON files. Default: ~/.anglerfish/records/",
    )
    batch_parser.add_argument(
        "--dry-run",
        action="store_true",
        dest="dry_run",
        help="Validate manifest and authenticate without deploying.",
    )
    batch_parser.add_argument(
        "--demo",
        action="store_true",
        help="Run in offline demo mode (no auth, no API calls).",
    )
    batch_parser.add_argument(
        "--tenant-id",
        default=None,
        help="Microsoft Entra tenant ID. Overrides ANGLERFISH_TENANT_ID.",
    )
    batch_parser.add_argument(
        "--client-id",
        default=None,
        help="Microsoft Entra application (client) ID. Overrides ANGLERFISH_CLIENT_ID.",
    )
    batch_parser.add_argument(
        "--credential-mode",
        choices=("auto", "secret", "certificate"),
        default=None,
        help="Credential type for application auth.",
    )

    verify_parser = subparsers.add_parser("verify", help="Check that deployed canaries still exist.")
    verify_parser.add_argument(
        "record",
        nargs="?",
        default=None,
        metavar="RECORD",
        help="Path to a single deployment record JSON file.",
    )
    verify_parser.add_argument(
        "--records-dir",
        default=None,
        metavar="DIR",
        dest="records_dir",
        help="Directory containing deployment record JSON files.",
    )
    verify_parser.add_argument(
        "--demo",
        action="store_true",
        default=False,
        help="Show simulated verify output (no auth required).",
    )
    verify_parser.add_argument(
        "--tenant-id",
        default=None,
        help="Microsoft Entra tenant ID. Overrides ANGLERFISH_TENANT_ID.",
    )
    verify_parser.add_argument(
        "--client-id",
        default=None,
        help="Microsoft Entra application (client) ID. Overrides ANGLERFISH_CLIENT_ID.",
    )
    verify_parser.add_argument(
        "--credential-mode",
        choices=("auto", "secret", "certificate"),
        default=None,
        help="Credential type for application auth.",
    )

    dashboard_parser = subparsers.add_parser("dashboard", help="Live TUI dashboard for canary monitoring.")
    dashboard_parser.add_argument(
        "--records-dir",
        default=str(Path.home() / ".anglerfish" / "records"),
        metavar="DIR",
        dest="records_dir",
        help="Directory containing deployment record JSON files.",
    )
    dashboard_parser.add_argument(
        "--poll-interval",
        type=int,
        default=300,
        metavar="SECONDS",
        dest="poll_interval",
        help="Audit log poll interval in seconds (default: 300).",
    )
    dashboard_parser.add_argument(
        "--verify-interval",
        type=int,
        default=300,
        metavar="SECONDS",
        dest="verify_interval",
        help="Health check refresh interval in seconds (default: 300).",
    )
    dashboard_parser.add_argument(
        "--alert-log",
        default=None,
        metavar="PATH",
        dest="alert_log",
        help="JSONL alert log file (loads history on startup).",
    )
    dashboard_parser.add_argument(
        "--exclude-app-id",
        action="append",
        default=[],
        metavar="APP_ID",
        dest="exclude_app_ids",
        help="App/client IDs to exclude from matching (repeatable).",
    )
    dashboard_parser.add_argument(
        "--credential-mode",
        choices=("auto", "secret", "certificate"),
        default=None,
        help="Credential type for application auth.",
    )
    dashboard_parser.add_argument(
        "--tenant-id",
        default=None,
        help="Microsoft Entra tenant ID. Overrides ANGLERFISH_TENANT_ID.",
    )
    dashboard_parser.add_argument(
        "--client-id",
        default=None,
        help="Microsoft Entra application (client) ID. Overrides ANGLERFISH_CLIENT_ID.",
    )
    dashboard_parser.add_argument(
        "--demo",
        action="store_true",
        default=False,
        help="Run with simulated data (no auth required).",
    )

    return parser.parse_args(list(argv) if argv is not None else sys.argv[1:])


def _prompt_auth_setup(
    args: argparse.Namespace,
    console: Console,
    *,
    auth_mode: str = "application",
    non_interactive: bool = False,
) -> str | None:
    selected_auth_mode = auth_mode.strip().lower()
    if selected_auth_mode not in ("application", "delegated"):
        raise AuthenticationError(f"Unsupported auth mode: {auth_mode}")

    cli_tenant_id = str(args.tenant_id or "").strip()
    if cli_tenant_id:
        os.environ["ANGLERFISH_TENANT_ID"] = cli_tenant_id

    cli_client_id = str(args.client_id or "").strip()
    if cli_client_id:
        os.environ["ANGLERFISH_CLIENT_ID"] = cli_client_id

    if not os.environ.get("ANGLERFISH_TENANT_ID", "").strip():
        if non_interactive:
            raise AuthenticationError(
                "ANGLERFISH_TENANT_ID is not set. Provide it via environment variable or --tenant-id."
            )
        console.print("ANGLERFISH_TENANT_ID is not set. Please provide your tenant ID.")
        tenant_id = questionary.text(
            "Entra Directory (tenant) ID:",
            validate=_validate_non_empty,
            style=_STYLE,
            qmark=_QMARK,
        ).ask()
        if tenant_id is None:
            return None
        tenant_value = tenant_id.strip()
        if tenant_value:
            os.environ["ANGLERFISH_TENANT_ID"] = tenant_value

    if not os.environ.get("ANGLERFISH_CLIENT_ID", "").strip():
        if non_interactive:
            raise AuthenticationError(
                "ANGLERFISH_CLIENT_ID is not set. Provide it via environment variable or --client-id."
            )
        console.print("ANGLERFISH_CLIENT_ID is not set. Let's configure it now.")
        client_id = questionary.text(
            "Entra Application (client) ID:", validate=_validate_non_empty, style=_STYLE, qmark=_QMARK
        ).ask()
        if client_id is None:
            return None
        os.environ["ANGLERFISH_CLIENT_ID"] = client_id.strip()

    os.environ["ANGLERFISH_AUTH_MODE"] = selected_auth_mode
    if selected_auth_mode == "delegated":
        return "delegated"

    current_mode = args.credential_mode or os.environ.get("ANGLERFISH_APP_CREDENTIAL_MODE", "auto").strip().lower()
    if current_mode not in ("auto", "secret", "certificate"):
        current_mode = "auto"

    has_secret = bool(os.environ.get("ANGLERFISH_CLIENT_SECRET", "").strip())
    has_certificate = bool(
        os.environ.get("ANGLERFISH_CLIENT_CERT_PFX_PATH", "").strip()
        or os.environ.get("ANGLERFISH_CLIENT_CERT_PRIVATE_KEY_PATH", "").strip()
        or os.environ.get("ANGLERFISH_CLIENT_CERT_PUBLIC_CERT_PATH", "").strip()
        or os.environ.get("ANGLERFISH_CLIENT_CERT_THUMBPRINT", "").strip()
    )

    if current_mode == "auto":
        if has_secret and has_certificate:
            if non_interactive:
                # Default to secret when both are present and mode is unspecified.
                current_mode = "secret"
            else:
                selected = questionary.select(
                    "Both secret and certificate settings are present. Which should be used for this run?",
                    choices=[
                        questionary.Choice("Client secret", value="secret"),
                        questionary.Choice("Certificate", value="certificate"),
                    ],
                    style=_STYLE,
                    qmark=_QMARK,
                    pointer=_POINTER,
                ).ask()
                if selected is None:
                    return None
                current_mode = selected
        elif has_secret:
            current_mode = "secret"
        elif has_certificate:
            current_mode = "certificate"
        else:
            if non_interactive:
                raise AuthenticationError(
                    "No application credentials found. "
                    "Set ANGLERFISH_CLIENT_SECRET or certificate environment variables, "
                    "or use --credential-mode to specify the credential type."
                )
            selected = questionary.select(
                "Choose application credential type:",
                choices=[
                    questionary.Choice("Client secret", value="secret"),
                    questionary.Choice("Certificate", value="certificate"),
                ],
                style=_STYLE,
                qmark=_QMARK,
                pointer=_POINTER,
            ).ask()
            if selected is None:
                return None
            current_mode = selected

    if current_mode == "secret":
        if not has_secret:
            if non_interactive:
                raise AuthenticationError("Credential mode is 'secret' but ANGLERFISH_CLIENT_SECRET is not set.")
            secret = questionary.password(
                "Client secret:", validate=_validate_non_empty, style=_STYLE, qmark=_QMARK
            ).ask()
            if secret is None:
                return None
            os.environ["ANGLERFISH_CLIENT_SECRET"] = secret
        os.environ["ANGLERFISH_APP_CREDENTIAL_MODE"] = "secret"
        return "secret"

    # current_mode == "certificate"
    pfx_path = os.environ.get("ANGLERFISH_CLIENT_CERT_PFX_PATH", "").strip()
    key_path = os.environ.get("ANGLERFISH_CLIENT_CERT_PRIVATE_KEY_PATH", "").strip()
    thumbprint = os.environ.get("ANGLERFISH_CLIENT_CERT_THUMBPRINT", "").strip()

    if not pfx_path and not key_path:
        if non_interactive:
            raise AuthenticationError(
                "Credential mode is 'certificate' but no certificate path is set. "
                "Set ANGLERFISH_CLIENT_CERT_PFX_PATH or ANGLERFISH_CLIENT_CERT_PRIVATE_KEY_PATH."
            )
        cert_kind = questionary.select(
            "Choose certificate input type:",
            choices=[
                questionary.Choice("PFX file", value="pfx"),
                questionary.Choice("PEM private key + thumbprint", value="pem"),
            ],
            style=_STYLE,
            qmark=_QMARK,
            pointer=_POINTER,
        ).ask()
        if cert_kind is None:
            return None

        if cert_kind == "pfx":
            pfx = questionary.text(
                "Path to .pfx certificate file:", validate=_validate_file_path, style=_STYLE, qmark=_QMARK
            ).ask()
            if pfx is None:
                return None
            os.environ["ANGLERFISH_CLIENT_CERT_PFX_PATH"] = pfx.strip()
            pfx_passphrase = questionary.password(
                "PFX passphrase (leave blank if none):", style=_STYLE, qmark=_QMARK
            ).ask()
            if pfx_passphrase is None:
                return None
            os.environ["ANGLERFISH_CLIENT_CERT_PASSPHRASE"] = pfx_passphrase
        else:
            key = questionary.text(
                "Path to PEM private key file:", validate=_validate_file_path, style=_STYLE, qmark=_QMARK
            ).ask()
            if key is None:
                return None
            os.environ["ANGLERFISH_CLIENT_CERT_PRIVATE_KEY_PATH"] = key.strip()
            cert_thumbprint = questionary.text(
                "Certificate thumbprint (hex, no colons):",
                validate=_validate_non_empty,
                style=_STYLE,
                qmark=_QMARK,
            ).ask()
            if cert_thumbprint is None:
                return None
            os.environ["ANGLERFISH_CLIENT_CERT_THUMBPRINT"] = cert_thumbprint.strip()

            cert_file = questionary.text("Path to PEM public certificate (optional):", style=_STYLE, qmark=_QMARK).ask()
            if cert_file is None:
                return None
            if cert_file.strip():
                os.environ["ANGLERFISH_CLIENT_CERT_PUBLIC_CERT_PATH"] = cert_file.strip()

            key_passphrase = questionary.password(
                "Private key passphrase (leave blank if none):", style=_STYLE, qmark=_QMARK
            ).ask()
            if key_passphrase is None:
                return None
            os.environ["ANGLERFISH_CLIENT_CERT_PASSPHRASE"] = key_passphrase

    if key_path and not thumbprint:
        if non_interactive:
            raise AuthenticationError("ANGLERFISH_CLIENT_CERT_THUMBPRINT is required when using PEM private key auth.")
        cert_thumbprint = questionary.text(
            "Certificate thumbprint (hex, no colons):",
            validate=_validate_non_empty,
            style=_STYLE,
            qmark=_QMARK,
        ).ask()
        if cert_thumbprint is None:
            return None
        os.environ["ANGLERFISH_CLIENT_CERT_THUMBPRINT"] = cert_thumbprint.strip()

    os.environ["ANGLERFISH_APP_CREDENTIAL_MODE"] = "certificate"
    return "certificate"


def _print_banner(console: Console) -> None:
    title = Text.assemble(
        ("  \U0001f3af Anglerfish", "bold blue"),
        ("  v", "dim"),
        (__version__, "dim"),
    )
    subtitle = Text("Microsoft 365 Canary Deployment", style="dim")
    banner = Text()
    banner.append_text(title)
    banner.append("\n")
    banner.append_text(subtitle)
    console.print(Panel(banner, expand=False, padding=(1, 4)))


def _step_rule(console: Console, step: int, total: int, title: str) -> None:
    console.print()
    console.rule(f"[bold]Step {step} of {total} \u00b7 {title}[/bold]")
    console.print()


def _print_summary_table(console: Console, rows: list[tuple[str, str]]) -> None:
    table = Table(show_header=True, header_style="bold", expand=False)
    table.add_column("Setting", style="cyan")
    table.add_column("Value")
    for setting, value in rows:
        table.add_row(setting, value)
    console.print(table)
    console.print()


def _print_success(console: Console, result: dict[str, str]) -> None:
    table = Table(show_header=False, show_edge=False, padding=(0, 2))
    table.add_column("Key", style="bold")
    table.add_column("Value")
    for key, value in result.items():
        table.add_row(key, str(value))
    panel = Panel(
        table,
        title="[bold green]\u2713 Canary Deployed Successfully[/bold green]",
        border_style="green",
        expand=False,
        padding=(1, 2),
    )
    console.print()
    console.print(panel)
    console.print()


def _print_error(console: Console, message: str) -> None:
    console.print()
    console.print(
        Panel(
            str(message),
            title="[bold red]Error[/bold red]",
            border_style="red",
            expand=False,
            padding=(1, 2),
        )
    )


def _find_graph_api_error(exc: BaseException) -> GraphApiError | None:
    current: BaseException | None = exc
    seen: set[int] = set()
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        if isinstance(current, GraphApiError):
            return current
        current = current.__cause__ or current.__context__
    return None


def _format_exception_message(exc: BaseException) -> str:
    message = str(exc)
    graph_error = _find_graph_api_error(exc)
    if graph_error is None:
        return message

    lines = [message]
    if graph_error.method and graph_error.path:
        lines.append(f"Graph request: {graph_error.method} {graph_error.path}")
    elif graph_error.path:
        lines.append(f"Graph request path: {graph_error.path}")
    if graph_error.request_id:
        lines.append(f"Graph request-id: {graph_error.request_id}")
    if graph_error.client_request_id:
        lines.append(f"Graph client-request-id: {graph_error.client_request_id}")
    return "\n".join(lines)


def _print_auth_success(console: Console, *, auth_mode: str = "application") -> None:
    if auth_mode == "delegated":
        console.print("[bold green]\u2713[/bold green] Authenticated using [green]delegated permissions[/green]")
        return
    console.print("[bold green]\u2713[/bold green] Authenticated using [green]application permissions[/green]")


def _print_cleanup_summary(console: Console, record: dict) -> None:
    canary_type = str(record.get("type", record.get("canary_type", ""))).strip().lower()
    rows: list[tuple[str, str]] = [("Canary type", canary_type)]
    if canary_type == "outlook":
        delivery_mode = str(record.get("delivery_mode", "draft")).strip()
        rows.append(("Delivery mode", delivery_mode))
        rows.append(("Target user", str(record.get("target_user", ""))))
        if delivery_mode == "draft":
            rows.append(("Folder ID", str(record.get("folder_id", ""))))
        else:
            rows.append(("Inbox message ID", str(record.get("inbox_message_id", ""))))
    elif canary_type == "sharepoint":
        rows.append(("Site ID", str(record.get("site_id", ""))))
        rows.append(("Folder path", str(record.get("folder_path", ""))))
        rows.append(("File", str(record.get("uploaded_files", ""))))
        item_id = str(record.get("item_id", "")).strip()
        if item_id:
            rows.append(("Item ID", item_id))
    elif canary_type == "onedrive":
        rows.append(("Target user", str(record.get("target_user", ""))))
        rows.append(("Folder path", str(record.get("folder_path", ""))))
        rows.append(("File", str(record.get("uploaded_files", ""))))
        item_id = str(record.get("item_id", "")).strip()
        if item_id:
            rows.append(("Item ID", item_id))
    _print_summary_table(console, rows)


def _print_cleanup_success(console: Console, result: dict[str, str]) -> None:
    table = Table(show_header=False, show_edge=False, padding=(0, 2))
    table.add_column("Key", style="bold")
    table.add_column("Value")
    for key, value in result.items():
        table.add_row(key, str(value))
    panel = Panel(
        table,
        title="[bold green]\u2713 Canary Removed[/bold green]",
        border_style="green",
        expand=False,
        padding=(1, 2),
    )
    console.print()
    console.print(panel)
    console.print()


def _run_list(args: argparse.Namespace, console: Console) -> int:
    """List all deployment records in a directory as a Rich table."""
    records_dir = Path(args.records_dir)

    if not records_dir.exists():
        console.print(f"[yellow]Records directory not found:[/yellow] {records_dir}")
        console.print(
            "[dim]Deploy with --output-json pointing into this directory, "
            "or pass --records-dir to specify a different path.[/dim]"
        )
        return 0

    record_files = sorted(records_dir.glob("*.json"), key=lambda p: p.stat().st_mtime)
    if not record_files:
        console.print("[yellow]No deployment records found in[/yellow] " + str(records_dir))
        return 0

    table = Table(
        title=f"Deployed Canary Artifacts  ({records_dir})",
        box=box.SIMPLE_HEAVY,
        show_lines=False,
        highlight=True,
    )
    table.add_column("ID", style="dim", no_wrap=True)
    table.add_column("Type", style="cyan", no_wrap=True)
    table.add_column("Template")
    table.add_column("Target")
    table.add_column("Deployed", no_wrap=True)
    table.add_column("Status", no_wrap=True)

    for record_file in record_files:
        try:
            record = read_deployment_record(record_file)
        except DeploymentError:
            continue  # Skip malformed records silently

        record_id = record_file.stem[:12]
        canary_type = str(record.get("canary_type", record.get("type", "unknown")))
        template_name = str(record.get("template_name", "—"))
        target = str(record.get("target_user") or record.get("site_name") or "—")
        timestamp = str(record.get("timestamp", "—"))

        try:
            dt = datetime.datetime.fromisoformat(timestamp)
            deployed_str = dt.strftime("%Y-%m-%d %H:%M UTC")
        except (ValueError, TypeError):
            deployed_str = timestamp

        status = str(record.get("status", "active"))
        if status == "active":
            status_markup = "[green]active[/green]"
        elif status == "cleaned_up":
            status_markup = "[dim]cleaned_up[/dim]"
        else:
            status_markup = f"[dim]{status}[/dim]"

        table.add_row(record_id, canary_type, template_name, target, deployed_str, status_markup)

    console.print(table)
    return 0


def _run_cleanup(args: argparse.Namespace, console: Console) -> int:
    _print_banner(console)
    non_interactive = args.non_interactive
    demo = getattr(args, "demo", False)
    total_steps = 2 if demo else 3

    try:
        # Step 1: Read Record
        _step_rule(console, 1, total_steps, "Read Record")
        record = read_deployment_record(args.record)
        canary_type = str(record.get("type", record.get("canary_type", ""))).strip().lower()
        if canary_type not in ("outlook", "sharepoint", "onedrive"):
            raise DeploymentError(f"Unknown canary type in record: '{canary_type}'.")
        _print_cleanup_summary(console, record)

        if demo:
            _step_rule(console, 2, total_steps, "Remove (simulated)")
            _print_cleanup_success(console, {"status": "removed (demo)", "canary_type": canary_type})
            console.print("[bold yellow]Demo mode — no API calls were made.[/bold yellow]")
            return 0

        # Step 2: Authentication
        _step_rule(console, 2, total_steps, "Authentication")
        selected = _prompt_auth_setup(args, console, auth_mode="application", non_interactive=non_interactive)
        if selected is None:
            return 130
        console.print("Authenticating with Microsoft Graph...")
        token = authenticate(auth_mode="application", app_credential_mode=selected)
        _print_auth_success(console, auth_mode="application")
        graph = GraphClient(token)

        # Step 3: Remove
        _step_rule(console, 3, total_steps, "Remove")
        if not non_interactive:
            confirmed = questionary.confirm("Remove this canary?", default=False, style=_STYLE, qmark=_QMARK).ask()
            if not confirmed:
                console.print("[yellow]Cancelled.[/yellow]")
                return 0

        if canary_type == "outlook":
            result = outlook_remove_canary(graph, record)
        elif canary_type == "onedrive":
            result = onedrive_remove_canary(graph, record)
        else:
            result = sharepoint_remove_canary(graph, record)

        _print_cleanup_success(console, result)
        try:
            update_deployment_status(args.record, "cleaned_up")
        except DeploymentError:
            pass  # Best-effort; do not fail cleanup if record can't be updated
        return 0

    except (AuthenticationError, DeploymentError, GraphApiError, AnglerfishError) as exc:
        _print_error(console, _format_exception_message(exc))
        return 1
    except KeyboardInterrupt:
        console.print("\n[yellow]Cancelled.[/yellow]")
        return 130


def _render_deploy_template(
    template: OutlookTemplate | SharePointTemplate | OneDriveTemplate,
    *,
    canary_type: str,
    console: Console,
    non_interactive: bool,
    cli_var_values: dict[str, str],
) -> OutlookTemplate | SharePointTemplate | OneDriveTemplate | None:
    if not template.variables:
        return template

    var_values: dict[str, str] = {}
    skipped_sharepoint_vars = {"site_name", "folder_path", "canary_url"}
    skipped_onedrive_vars = {"folder_path", "canary_url"}
    if canary_type == "sharepoint":
        if isinstance(template, SharePointTemplate):
            # SharePoint site and folder are collected with dedicated prompts.
            var_values["site_name"] = template.site_name
            var_values["folder_path"] = template.folder_path
        # Canary callback is intentionally no longer prompted.
        var_values["canary_url"] = ""
    elif canary_type == "onedrive":
        if isinstance(template, OneDriveTemplate):
            var_values["folder_path"] = template.folder_path
        var_values["canary_url"] = ""

    for var in template.variables:
        name = str(var.get("name", "")).strip()
        if canary_type == "sharepoint" and name in skipped_sharepoint_vars:
            continue
        if canary_type == "onedrive" and name in skipped_onedrive_vars:
            continue

        if non_interactive:
            # Use --var overrides first, then fall back to template default.
            default = str(var.get("default", ""))
            value = cli_var_values.get(name, default)
            if not value and not default:
                raise DeploymentError(
                    f"Variable '{name}' is required but not set. Pass --var {name}=<value> in --non-interactive mode."
                )
            var_values[name] = value
        else:
            default = var.get("default", "")
            answer = questionary.text(
                f"{var.get('description', var['name'])}:",
                default=default,
                validate=_validate_non_empty if not default else _validate_variable_value,
                style=_STYLE,
                qmark=_QMARK,
            ).ask()
            if answer is None:
                return None
            var_values[name] = answer.strip()

    return render_template(template, var_values)


def _run_sharepoint_deploy(
    args: argparse.Namespace,
    console: Console,
    template: OutlookTemplate | SharePointTemplate | OneDriveTemplate,
    non_interactive: bool,
    total_steps: int,
    cli_var_values: dict[str, str],
) -> int:
    if not isinstance(template, SharePointTemplate):
        raise TemplateError("Selected template is not a SharePoint template.")

    # Step 2: Authentication
    _step_rule(console, 2, total_steps, "Authentication")

    app_credential_mode = _prompt_auth_setup(args, console, auth_mode="application", non_interactive=non_interactive)
    if app_credential_mode is None:
        console.print("[yellow]Cancelled.[/yellow]")
        return 130

    console.print("Authenticating with Microsoft Graph...")
    token = authenticate(
        auth_mode="application",
        app_credential_mode=app_credential_mode,
    )
    graph = GraphClient(token)

    _print_auth_success(console, auth_mode="application")

    selected_site_id = ""
    if non_interactive:
        if not args.target:
            raise DeploymentError(
                "--target (SharePoint site name) is required in --non-interactive mode. "
                "Run `anglerfish --canary-type sharepoint` interactively to search and select sites."
            )
        site_name = args.target.strip()
    else:
        site_search = questionary.text(
            "Search SharePoint sites:",
            default=template.site_name,
            validate=_validate_non_empty,
            style=_STYLE,
            qmark=_QMARK,
        ).ask()
        if site_search is None:
            console.print("[yellow]Cancelled.[/yellow]")
            return 130

        with console.status("[bold green]Discovering SharePoint sites..."):
            discovered_sites = _search_sharepoint_sites(graph, site_search.strip())

        if discovered_sites:
            site_choice = questionary.select(
                "Select SharePoint site:",
                choices=[questionary.Choice(site["label"], value=site["id"]) for site in discovered_sites]
                + [questionary.Choice("Enter site name manually", value="__manual__")],
                style=_STYLE,
                qmark=_QMARK,
                pointer=_POINTER,
            ).ask()
            if site_choice is None:
                console.print("[yellow]Cancelled.[/yellow]")
                return 130

            if site_choice == "__manual__":
                site_name = questionary.text(
                    "SharePoint site name:",
                    default=template.site_name,
                    validate=_validate_non_empty,
                    style=_STYLE,
                    qmark=_QMARK,
                ).ask()
                if site_name is None:
                    console.print("[yellow]Cancelled.[/yellow]")
                    return 130
                site_name = site_name.strip()
            else:
                selected = next(site for site in discovered_sites if site["id"] == site_choice)
                site_name = selected["name"]
                selected_site_id = selected["id"]
        else:
            site_name = questionary.text(
                "SharePoint site name:",
                default=template.site_name,
                validate=_validate_non_empty,
                style=_STYLE,
                qmark=_QMARK,
            ).ask()
            if site_name is None:
                console.print("[yellow]Cancelled.[/yellow]")
                return 130
            site_name = site_name.strip()

    if non_interactive:
        if not args.folder_path:
            raise DeploymentError("--folder-path is required for SharePoint in --non-interactive mode.")
        normalized_folder_path = _normalize_sharepoint_folder_path(args.folder_path)
        if not normalized_folder_path:
            raise DeploymentError(f"--folder-path '{args.folder_path}' normalizes to an empty path.")
        if not args.filename:
            raise DeploymentError("--filename is required for SharePoint in --non-interactive mode.")
        filename_input = args.filename.strip()
    else:
        folder_path = questionary.text(
            "Destination folder path:",
            default=_normalize_sharepoint_folder_path(template.folder_path),
            validate=_validate_sharepoint_folder_path,
            style=_STYLE,
            qmark=_QMARK,
        ).ask()
        if folder_path is None:
            console.print("[yellow]Cancelled.[/yellow]")
            return 130
        normalized_folder_path = _normalize_sharepoint_folder_path(folder_path)

        filename_input = questionary.text(
            "Canary filename:",
            default=template.filenames[0],
            validate=_validate_single_filename,
            style=_STYLE,
            qmark=_QMARK,
        ).ask()
        if filename_input is None:
            console.print("[yellow]Cancelled.[/yellow]")
            return 130

    template = dataclasses.replace(
        template,
        site_name=site_name,
        folder_path=normalized_folder_path,
        filenames=[filename_input.strip()],
    )

    # Step 3: Review
    _step_rule(console, 3, total_steps, "Review")

    summary_rows: list[tuple[str, str]] = [
        ("Type", "sharepoint"),
        ("App credential mode", app_credential_mode or "env/default"),
    ]
    if args.dry_run:
        summary_rows.append(("Mode", "DRY RUN — no writes"))
    if selected_site_id:
        summary_rows.append(("Site id", selected_site_id))
    summary_rows.extend(
        [
            ("Template", template.name),
            ("Site name", template.site_name),
            ("Folder path", template.folder_path),
            ("Filename", template.filenames[0]),
        ]
    )
    _print_summary_table(console, summary_rows)

    if args.dry_run:
        console.print("[bold yellow]Dry run complete. No canary deployed.[/bold yellow]")
        return 0

    if not non_interactive:
        should_deploy = questionary.confirm("Deploy this canary?", default=False, style=_STYLE, qmark=_QMARK).ask()
        if not should_deploy:
            console.print("[yellow]Cancelled.[/yellow]")
            return 0

    # Step 4: Deploy
    _step_rule(console, 4, total_steps, "Deploy")

    deployer = SharePointDeployer(graph, template)
    with console.status("[bold green]Deploying canary..."):
        result = deployer.deploy(
            template.site_name,
            folder_path=template.folder_path,
            filenames=template.filenames,
            site_id=selected_site_id,
        )

    _print_success(console, result)
    if args.output_json:
        write_deployment_record(
            args.output_json,
            {
                "canary_type": "sharepoint",
                "template_name": template.name,
                "auth_mode": "application",
                "status": "active",
                **result,
            },
        )
        console.print(f"[dim]Deployment record written to {args.output_json}[/dim]")
    return 0


def _run_outlook_deploy(
    args: argparse.Namespace,
    console: Console,
    template: OutlookTemplate | SharePointTemplate | OneDriveTemplate,
    non_interactive: bool,
    total_steps: int,
    cli_var_values: dict[str, str],
) -> int:
    if not isinstance(template, OutlookTemplate):
        raise TemplateError("Selected template is not an Outlook template.")

    if non_interactive:
        delivery_mode = args.delivery_mode
        if delivery_mode not in ("draft", "send"):
            raise DeploymentError("--delivery-mode must be 'draft' or 'send' for Outlook in --non-interactive mode.")
    else:
        delivery_mode = questionary.select(
            "Select delivery mode:",
            choices=[
                questionary.Choice("Draft in hidden folder (stealth default)", value="draft"),
                questionary.Choice("Send real email to target Inbox", value="send"),
            ],
            style=_STYLE,
            qmark=_QMARK,
            pointer=_POINTER,
        ).ask()
        if delivery_mode is None:
            console.print("[yellow]Cancelled.[/yellow]")
            return 130

    if delivery_mode == "draft" and not non_interactive:
        folder_name = questionary.text(
            "Hidden folder name:",
            default=template.folder_name,
            validate=_validate_non_empty,
            style=_STYLE,
            qmark=_QMARK,
        ).ask()
        if folder_name is None:
            console.print("[yellow]Cancelled.[/yellow]")
            return 130
        template = dataclasses.replace(template, folder_name=folder_name.strip())

    if non_interactive:
        if not args.target:
            raise DeploymentError(
                "--target (mailbox UPN/email) is required for Outlook in --non-interactive mode. "
                "Example: --target user@contoso.com"
            )
        target_user = args.target.strip()
    else:
        target_user = questionary.text(
            "Target mailbox (UPN/email):",
            validate=_validate_email,
            style=_STYLE,
            qmark=_QMARK,
        ).ask()
        if target_user is None:
            console.print("[yellow]Cancelled.[/yellow]")
            return 130
        target_user = target_user.strip()

    # Step 2: Authentication
    _step_rule(console, 2, total_steps, "Authentication")

    app_credential_mode = _prompt_auth_setup(args, console, auth_mode="application", non_interactive=non_interactive)
    if app_credential_mode is None:
        console.print("[yellow]Cancelled.[/yellow]")
        return 130

    console.print("Authenticating with Microsoft Graph...")
    token = authenticate(
        auth_mode="application",
        app_credential_mode=app_credential_mode,
    )
    graph = GraphClient(token)

    _print_auth_success(console, auth_mode="application")

    # Step 3: Review
    _step_rule(console, 3, total_steps, "Review")

    summary_rows = [
        ("Type", "outlook"),
        ("Delivery mode", delivery_mode),
        ("App credential mode", app_credential_mode or "env/default"),
    ]
    if args.dry_run:
        summary_rows.append(("Mode", "DRY RUN — no writes"))
    summary_rows.append(("Template", template.name))
    if delivery_mode == "draft":
        summary_rows.append(("Hidden folder", template.folder_name))
    summary_rows.append(("Target", target_user))
    _print_summary_table(console, summary_rows)

    if args.dry_run:
        console.print("[bold yellow]Dry run complete. No canary deployed.[/bold yellow]")
        return 0

    if not non_interactive:
        should_deploy = questionary.confirm("Deploy this canary?", default=False, style=_STYLE, qmark=_QMARK).ask()
        if not should_deploy:
            console.print("[yellow]Cancelled.[/yellow]")
            return 0

    # Step 4: Deploy
    _step_rule(console, 4, total_steps, "Deploy")

    deployer = OutlookDeployer(graph, template)
    with console.status("[bold green]Deploying canary..."):
        result = deployer.deploy(target_user, delivery_mode=delivery_mode)

    _print_success(console, result)
    if args.output_json:
        write_deployment_record(
            args.output_json,
            {
                "canary_type": "outlook",
                "template_name": template.name,
                "auth_mode": "application",
                "status": "active",
                **result,
            },
        )
        console.print(f"[dim]Deployment record written to {args.output_json}[/dim]")
    return 0


def _run_demo_deploy(
    console: Console,
    canary_type: str,
    template: OutlookTemplate | SharePointTemplate | OneDriveTemplate,
) -> int:
    """Print simulated deployment output for demo/offline mode."""
    console.print()
    console.rule("[bold]Simulated Deployment (demo mode)[/bold]")
    console.print()
    rows: list[tuple[str, str]] = [
        ("Mode", "DEMO — no API calls"),
        ("Canary type", canary_type),
        ("Template", template.name),
    ]
    if isinstance(template, OutlookTemplate):
        rows.append(("Subject", template.subject))
        rows.append(("Sender", f"{template.sender_name} <{template.sender_email}>"))
    elif isinstance(template, SharePointTemplate):
        rows.append(("Site", template.site_name))
        rows.append(("Folder", template.folder_path))
        rows.append(("Filename", template.filenames[0] if template.filenames else "—"))
    elif isinstance(template, OneDriveTemplate):
        rows.append(("Folder", template.folder_path))
        rows.append(("Filename", template.filenames[0] if template.filenames else "—"))
    _print_summary_table(console, rows)
    _print_success(console, {"status": "deployed (demo)", "canary_type": canary_type, "template": template.name})
    console.print("[bold yellow]Demo mode — no authentication or Graph API calls were made.[/bold yellow]")
    return 0


def _run_onedrive_deploy(
    args: argparse.Namespace,
    console: Console,
    template: OutlookTemplate | SharePointTemplate | OneDriveTemplate,
    non_interactive: bool,
    total_steps: int,
    cli_var_values: dict[str, str],
) -> int:
    if not isinstance(template, OneDriveTemplate):
        raise TemplateError("Selected template is not a OneDrive template.")

    # Step 2: Authentication
    _step_rule(console, 2, total_steps, "Authentication")

    app_credential_mode = _prompt_auth_setup(args, console, auth_mode="application", non_interactive=non_interactive)
    if app_credential_mode is None:
        console.print("[yellow]Cancelled.[/yellow]")
        return 130

    console.print("Authenticating with Microsoft Graph...")
    token = authenticate(
        auth_mode="application",
        app_credential_mode=app_credential_mode,
    )
    graph = GraphClient(token)

    _print_auth_success(console, auth_mode="application")

    if non_interactive:
        if not args.target:
            raise DeploymentError(
                "--target (UPN/email) is required for OneDrive in --non-interactive mode. "
                "Example: --target user@contoso.com"
            )
        target_user = args.target.strip()
    else:
        target_user = questionary.text(
            "Target user (UPN/email):",
            validate=_validate_email,
            style=_STYLE,
            qmark=_QMARK,
        ).ask()
        if target_user is None:
            console.print("[yellow]Cancelled.[/yellow]")
            return 130
        target_user = target_user.strip()

    if non_interactive:
        folder_path = args.folder_path.strip() if args.folder_path else template.folder_path
        if not args.filename:
            raise DeploymentError("--filename is required for OneDrive in --non-interactive mode.")
        filename_input = args.filename.strip()
    else:
        folder_path = questionary.text(
            "Destination folder path:",
            default=template.folder_path,
            style=_STYLE,
            qmark=_QMARK,
        ).ask()
        if folder_path is None:
            console.print("[yellow]Cancelled.[/yellow]")
            return 130
        folder_path = folder_path.strip()

        filename_input = questionary.text(
            "Canary filename:",
            default=template.filenames[0],
            validate=_validate_single_filename,
            style=_STYLE,
            qmark=_QMARK,
        ).ask()
        if filename_input is None:
            console.print("[yellow]Cancelled.[/yellow]")
            return 130

    template = dataclasses.replace(
        template,
        folder_path=folder_path,
        filenames=[filename_input.strip()],
    )

    # Step 3: Review
    _step_rule(console, 3, total_steps, "Review")

    summary_rows: list[tuple[str, str]] = [
        ("Type", "onedrive"),
        ("App credential mode", app_credential_mode or "env/default"),
    ]
    if args.dry_run:
        summary_rows.append(("Mode", "DRY RUN — no writes"))
    summary_rows.extend(
        [
            ("Template", template.name),
            ("Target user", target_user),
            ("Folder path", template.folder_path),
            ("Filename", template.filenames[0]),
        ]
    )
    _print_summary_table(console, summary_rows)

    if args.dry_run:
        console.print("[bold yellow]Dry run complete. No canary deployed.[/bold yellow]")
        return 0

    if not non_interactive:
        should_deploy = questionary.confirm("Deploy this canary?", default=False, style=_STYLE, qmark=_QMARK).ask()
        if not should_deploy:
            console.print("[yellow]Cancelled.[/yellow]")
            return 0

    # Step 4: Deploy
    _step_rule(console, 4, total_steps, "Deploy")

    deployer = OneDriveDeployer(graph, template)
    with console.status("[bold green]Deploying canary..."):
        result = deployer.deploy(
            target_user,
            folder_path=template.folder_path,
            filenames=template.filenames,
        )

    _print_success(console, result)
    if args.output_json:
        write_deployment_record(
            args.output_json,
            {
                "canary_type": "onedrive",
                "template_name": template.name,
                "auth_mode": "application",
                "status": "active",
                **result,
            },
        )
        console.print(f"[dim]Deployment record written to {args.output_json}[/dim]")
    return 0


def _run_monitor(args: argparse.Namespace, console: Console) -> int:
    """Run the canary access monitoring loop."""
    from .alerts import AlertDispatcher
    from .audit import AuditClient
    from .config import (
        MONITOR_ALERT_LOG,
        MONITOR_NO_CONSOLE,
        MONITOR_SLACK_WEBHOOK,
        MONITOR_STATE_FILE,
        TENANT_ID,
    )
    from .monitor import CanaryIndex, _TokenManager, load_records, render_demo_alert, run_monitor
    from .state import StateManager

    _print_banner(console)

    if getattr(args, "demo", False):
        render_demo_alert(console, count=getattr(args, "demo_count", 1))
        return 0

    records = load_records(args.records_dir)
    if not records:
        console.print(f"[yellow]No active deployment records found in {args.records_dir}[/yellow]")
        console.print(
            "[dim]Deploy canaries with --output-json to create records, "
            "or pass --records-dir to specify a different path.[/dim]"
        )
        return 1

    canary_index = CanaryIndex(records)
    console.print(f"Loaded [bold]{canary_index.count}[/bold] active canary record(s).")

    # Auth
    cli_tenant_id = str(args.tenant_id or "").strip()
    if cli_tenant_id:
        os.environ["ANGLERFISH_TENANT_ID"] = cli_tenant_id
    cli_client_id = str(args.client_id or "").strip()
    if cli_client_id:
        os.environ["ANGLERFISH_CLIENT_ID"] = cli_client_id

    tenant_id = cli_tenant_id or os.environ.get("ANGLERFISH_TENANT_ID", TENANT_ID).strip()
    if not tenant_id:
        raise AuthenticationError(
            "ANGLERFISH_TENANT_ID is required for monitoring. Set it via environment variable or --tenant-id."
        )

    token = authenticate_management_api(args.credential_mode)
    audit_client = AuditClient(token, tenant_id)

    exclude_ids = {aid.strip().lower() for aid in args.exclude_app_ids if aid.strip()}

    # State persistence.
    state_file = args.state_file or MONITOR_STATE_FILE or None
    state_manager = StateManager(state_file) if state_file else StateManager()

    # Alert dispatcher.
    no_console = args.no_console or MONITOR_NO_CONSOLE
    alert_log = args.alert_log or MONITOR_ALERT_LOG or None
    slack_webhook = getattr(args, "slack_webhook_url", None) or MONITOR_SLACK_WEBHOOK or None
    dispatcher = AlertDispatcher(
        console=None if no_console else console,
        alert_log=alert_log,
        slack_webhook_url=slack_webhook,
    )

    # Token manager for automatic refresh.
    token_mgr = _TokenManager(token, args.credential_mode)

    return run_monitor(
        audit_client,
        canary_index,
        interval=args.interval,
        once=args.once,
        exclude_app_ids=exclude_ids or None,
        console=console,
        state_manager=state_manager,
        dispatcher=dispatcher,
        token_manager=token_mgr,
    )


def _run_batch(args: argparse.Namespace, console: Console) -> int:
    """Run batch deployment from a YAML manifest."""
    from .batch import parse_manifest, run_batch

    console.print()
    console.rule("[bold]Batch Deployment[/bold]")
    console.print()

    specs = parse_manifest(args.manifest)
    console.print(f"Loaded {len(specs)} canary definition(s) from manifest.")

    if getattr(args, "demo", False):
        results = run_batch(specs, graph=None, output_dir=args.output_dir, dry_run=True)
        console.print("[bold yellow]Demo mode — no authentication or Graph API calls were made.[/bold yellow]")
    else:
        app_credential_mode = _prompt_auth_setup(args, console, auth_mode="application", non_interactive=True)
        console.print("Authenticating with Microsoft Graph...")
        token = authenticate(auth_mode="application", app_credential_mode=app_credential_mode)
        graph = GraphClient(token)
        _print_auth_success(console, auth_mode="application")

        results = run_batch(
            specs,
            graph=graph,
            output_dir=args.output_dir,
            dry_run=getattr(args, "dry_run", False),
        )

    table = Table(box=box.ROUNDED, title="Batch Results")
    table.add_column("#", style="dim")
    table.add_column("Type")
    table.add_column("Target")
    table.add_column("Template")
    table.add_column("Status")
    table.add_column("Record")

    for r in results:
        if r.get("dry_run"):
            status = "[yellow]DRY RUN[/yellow]"
        elif r["success"]:
            status = "[green]OK[/green]"
        else:
            status = f"[red]FAILED: {r.get('error', '?')}[/red]"
        record = r.get("record_path", "—")
        table.add_row(str(r["index"]), r["canary_type"], r["target"], r["template"], status, record)

    console.print()
    console.print(table)

    succeeded = sum(1 for r in results if r["success"])
    failed = len(results) - succeeded
    console.print(f"\n[bold]{succeeded} succeeded, {failed} failed[/bold]")

    return 1 if failed > 0 else 0


def _run_verify(args: argparse.Namespace, console: Console) -> int:
    """Verify deployed canaries still exist via Graph API."""
    from .monitor import load_records
    from .verify import VerifyResult, VerifyStatus, run_verify

    _print_banner(console)

    if getattr(args, "demo", False):
        # Demo mode: show simulated output.
        console.print("Verifying [bold]3[/bold] deployment record(s)...\n")
        results = [
            VerifyResult(
                canary_type="outlook",
                template_name="Fake Password Reset",
                target="cfo@contoso.com",
                status=VerifyStatus.OK,
            ),
            VerifyResult(
                canary_type="sharepoint",
                template_name="Employee Salary Bands",
                target="HRSite",
                status=VerifyStatus.GONE,
                detail="404 Not Found",
            ),
            VerifyResult(
                canary_type="onedrive",
                template_name="VPN Credentials Backup",
                target="j.smith@contoso.com",
                status=VerifyStatus.OK,
            ),
        ]
    else:
        # Collect records.
        records: list[tuple[str, dict]] = []
        if args.record:
            rec = read_deployment_record(args.record)
            records.append((args.record, rec))
        elif args.records_dir:
            records = load_records(args.records_dir)
        else:
            default_dir = str(Path.home() / ".anglerfish" / "records")
            records = load_records(default_dir)

        if not records:
            console.print("[yellow]No deployment records found to verify.[/yellow]")
            return 1

        console.print(f"Verifying [bold]{len(records)}[/bold] deployment record(s)...\n")
        # Authenticate.
        app_credential_mode = _prompt_auth_setup(args, console, auth_mode="application", non_interactive=True)
        console.print("Authenticating with Microsoft Graph...")
        token = authenticate(auth_mode="application", app_credential_mode=app_credential_mode)
        graph = GraphClient(token)
        _print_auth_success(console, auth_mode="application")

        results = run_verify(records, graph)

    # Render table.
    table = Table(box=box.ROUNDED, title="Canary Verification")
    table.add_column("Type", style="dim")
    table.add_column("Template")
    table.add_column("Target")
    table.add_column("Status")

    any_bad = False
    for r in results:
        if r.status == VerifyStatus.OK:
            status_str = "[green]OK[/green]"
        elif r.status == VerifyStatus.GONE:
            status_str = "[red]GONE[/red]"
            any_bad = True
        else:
            status_str = f"[yellow]ERROR: {r.detail}[/yellow]"
            any_bad = True
        table.add_row(r.canary_type, r.template_name, r.target, status_str)

    console.print(table)

    ok_count = sum(1 for r in results if r.status == VerifyStatus.OK)
    gone_count = sum(1 for r in results if r.status == VerifyStatus.GONE)
    error_count = sum(1 for r in results if r.status == VerifyStatus.ERROR)
    console.print(f"\n[bold]{ok_count} OK, {gone_count} gone, {error_count} error(s)[/bold]")

    if getattr(args, "demo", False):
        console.print("[bold yellow]Demo mode — no Graph API calls were made.[/bold yellow]")

    return 1 if any_bad else 0


def _run_dashboard(args: argparse.Namespace) -> int:
    """Launch the Textual TUI dashboard."""
    from .dashboard import AnglerDashboard

    app = AnglerDashboard(
        demo=getattr(args, "demo", False),
        records_dir=args.records_dir,
        poll_interval=args.poll_interval,
        verify_interval=args.verify_interval,
        alert_log=args.alert_log or "",
        exclude_app_ids=args.exclude_app_ids,
        credential_mode=args.credential_mode,
    )
    app.run()
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv)
    if getattr(args, "verbose", False):
        logging.basicConfig(level=logging.DEBUG, format="%(name)s %(levelname)s %(message)s")
    console = Console()
    if args.version:
        console.print(__version__)
        return 0

    if args.subcommand == "cleanup":
        return _run_cleanup(args, console)

    if args.subcommand == "list":
        return _run_list(args, console)

    if args.subcommand == "monitor":
        try:
            return _run_monitor(args, console)
        except (AuthenticationError, AuditApiError, DeploymentError, MonitorError) as exc:
            _print_error(console, _format_exception_message(exc))
            return 1
        except KeyboardInterrupt:
            console.print("\n[yellow]Cancelled.[/yellow]")
            return 130

    if args.subcommand == "batch":
        try:
            return _run_batch(args, console)
        except (AuthenticationError, DeploymentError, TemplateError, GraphApiError) as exc:
            _print_error(console, _format_exception_message(exc))
            return 1
        except KeyboardInterrupt:
            console.print("\n[yellow]Cancelled.[/yellow]")
            return 130

    if args.subcommand == "verify":
        try:
            return _run_verify(args, console)
        except (AuthenticationError, DeploymentError, GraphApiError) as exc:
            _print_error(console, _format_exception_message(exc))
            return 1

    if args.subcommand == "dashboard":
        try:
            return _run_dashboard(args)
        except (AuthenticationError, AuditApiError, MonitorError) as exc:
            _print_error(console, _format_exception_message(exc))
            return 1
        except KeyboardInterrupt:
            return 0

    _print_banner(console)

    non_interactive = args.non_interactive
    total_steps = 4

    try:
        # Parse --var KEY=VALUE arguments up front so errors surface early.
        cli_var_values = _parse_var_args(args.vars)

        # Non-interactive mode: require --canary-type.
        if non_interactive and not args.canary_type:
            raise DeploymentError(
                "--canary-type is required in --non-interactive mode. Options: outlook, sharepoint, onedrive."
            )

        # Step 1: Canary configuration
        _step_rule(console, 1, total_steps, "Canary Configuration")

        if args.canary_type:
            canary_type = args.canary_type
        else:
            canary_type = questionary.select(
                "Select canary type:",
                choices=[
                    questionary.Choice("Outlook (hidden email)", value="outlook"),
                    questionary.Choice("SharePoint (canary document)", value="sharepoint"),
                    questionary.Choice("OneDrive (canary file in personal storage)", value="onedrive"),
                ],
                style=_STYLE,
                qmark=_QMARK,
                pointer=_POINTER,
            ).ask()
            if canary_type is None:
                console.print("[yellow]Cancelled.[/yellow]")
                return 130

        available_templates = list_templates(canary_type)
        if not available_templates:
            console.print(f"[red]No {canary_type.title()} templates found.[/red]")
            return 1

        if non_interactive:
            if not args.template:
                raise DeploymentError(
                    f"--template is required in --non-interactive mode. "
                    f"Run `anglerfish --canary-type {canary_type}` interactively to see available templates."
                )
            template_path = _find_template_by_name(canary_type, args.template)
        else:
            template_path = questionary.select(
                "Select template:",
                choices=[
                    questionary.Choice(f"{item['name']} - {item['description']}", value=item["path"])
                    for item in available_templates
                ],
                style=_STYLE,
                qmark=_QMARK,
                pointer=_POINTER,
            ).ask()
            if template_path is None:
                console.print("[yellow]Cancelled.[/yellow]")
                return 130

        template = load_template(template_path)
        rendered_template = _render_deploy_template(
            template,
            canary_type=canary_type,
            console=console,
            non_interactive=non_interactive,
            cli_var_values=cli_var_values,
        )
        if rendered_template is None:
            console.print("[yellow]Cancelled.[/yellow]")
            return 130

        if getattr(args, "demo", False):
            return _run_demo_deploy(console, canary_type, rendered_template)

        if canary_type == "sharepoint":
            return _run_sharepoint_deploy(
                args,
                console,
                rendered_template,
                non_interactive,
                total_steps,
                cli_var_values,
            )

        if canary_type == "onedrive":
            return _run_onedrive_deploy(
                args,
                console,
                rendered_template,
                non_interactive,
                total_steps,
                cli_var_values,
            )

        return _run_outlook_deploy(
            args,
            console,
            rendered_template,
            non_interactive,
            total_steps,
            cli_var_values,
        )

    except (AuthenticationError, TemplateError, DeploymentError, GraphApiError) as exc:
        _print_error(console, _format_exception_message(exc))
        return 1
    except AnglerfishError as exc:
        _print_error(console, _format_exception_message(exc))
        return 1
    except KeyboardInterrupt:
        console.print("\n[yellow]Cancelled.[/yellow]")
        return 130
