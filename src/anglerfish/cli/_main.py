"""Arg parser, main() dispatch, banner, and print helpers."""

from __future__ import annotations

import argparse
import logging
import math
import sys
from pathlib import Path
from typing import Sequence

from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from .. import __version__
from ..exceptions import (
    AnglerfishError,
    AuditApiError,
    AuthenticationError,
    DeploymentError,
    GraphApiError,
    MonitorError,
)
from ..templates import find_template_by_name as _find_template_by_name, list_templates, load_template
from .prompts import _parse_var_args, _render_deploy_template

_ASCII_BANNER = (
    "    ___                __          _____      __  \n"
    "   /   |  ____  ____ _/ /__  _____/ __(_)____/ /_ \n"
    "  / /| | / __ \\/ __ `/ / _ \\/ ___/ /_/ / ___/ __ \\\n"
    " / ___ |/ / / / /_/ / /  __/ /  / __/ (__  ) / / /\n"
    "/_/  |_/_/ /_/\\__, /_/\\___/_/  /_/ /_/____/_/ /_/ \n"
    "             /____/                               \n"
)
_MAX_CLEANED_UP_LOOKBACK_HOURS = 8760.0


def _print_banner(console: Console) -> None:
    banner = Text()
    banner.append(_ASCII_BANNER, style="bold blue")
    banner.append("\n")
    banner.append("Microsoft 365 Canary Deployment", style="dim")
    banner.append("  v", style="dim")
    banner.append(__version__, style="dim")
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


def _cleaned_up_lookback_hours(value: str) -> float:
    try:
        parsed = float(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"invalid float value: {value!r}") from exc
    if not math.isfinite(parsed):
        raise argparse.ArgumentTypeError("value must be a finite number")
    if parsed > _MAX_CLEANED_UP_LOOKBACK_HOURS:
        raise argparse.ArgumentTypeError(f"value must be at most {_MAX_CLEANED_UP_LOOKBACK_HOURS:g} hours")
    return parsed


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


def _print_auth_success(console: Console, **_unused: object) -> None:
    console.print("[bold green]\u2713[/bold green] Authenticated using [green]application permissions[/green]")


def _apply_non_interactive_demo_defaults(args: argparse.Namespace) -> None:
    if not args.canary_type:
        args.canary_type = "outlook"
    if not args.template:
        args.template = "Fake Password Reset"
    if not args.delivery_mode:
        args.delivery_mode = "draft"


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
        choices=("outlook",),
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
        help="Deployment target: mailbox UPN/email for Outlook.",
    )
    parser.add_argument(
        "--delivery-mode",
        choices=("draft", "send"),
        default=None,
        dest="delivery_mode",
        help="Delivery mode: 'draft' or 'send' for Outlook.",
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
        "--demo",
        action="store_true",
        default=argparse.SUPPRESS,
        help="Simulate cleanup without authentication or Graph API calls.",
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
        "--cleaned-up-lookback-hours",
        type=_cleaned_up_lookback_hours,
        default=24.0,
        metavar="HOURS",
        help=("Include cleaned-up records this many hours after cleanup for late audit-log correlation (default: 24)."),
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

    demo_access_parser = subparsers.add_parser(
        "demo-access",
        help="Read a deployed Outlook canary to generate authorized audit evidence.",
    )
    demo_access_parser.add_argument("record", metavar="RECORD", help="Path to deployment record JSON.")
    demo_access_parser.add_argument(
        "--non-interactive",
        action="store_true",
        help="Skip confirmation prompt.",
    )
    demo_access_parser.add_argument(
        "--tenant-id",
        default=None,
        help="Microsoft Entra tenant ID. Overrides ANGLERFISH_TENANT_ID for this run.",
    )
    demo_access_parser.add_argument(
        "--client-id",
        default=None,
        help="Microsoft Entra application (client) ID. Overrides ANGLERFISH_CLIENT_ID for this run.",
    )
    demo_access_parser.add_argument(
        "--credential-mode",
        choices=("auto", "secret", "certificate"),
        default=None,
        help="Credential type for application auth. Overrides ANGLERFISH_APP_CREDENTIAL_MODE.",
    )

    return parser.parse_args(list(argv) if argv is not None else sys.argv[1:])


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv)
    if getattr(args, "verbose", False):
        logging.basicConfig(level=logging.DEBUG, format="%(name)s %(levelname)s %(message)s")
    console = Console()
    if args.version:
        console.print(__version__)
        return 0

    if args.subcommand == "cleanup":
        from .deploy import _run_cleanup

        return _run_cleanup(args, console)

    if args.subcommand == "list":
        from .deploy import _run_list

        return _run_list(args, console)

    if args.subcommand == "monitor":
        from .monitor import _run_monitor

        try:
            return _run_monitor(args, console)
        except (AuthenticationError, AuditApiError, DeploymentError, MonitorError) as exc:
            _print_error(console, _format_exception_message(exc))
            return 1
        except KeyboardInterrupt:
            console.print("\n[yellow]Cancelled.[/yellow]")
            return 130

    if args.subcommand == "verify":
        from .deploy import _run_verify

        try:
            return _run_verify(args, console)
        except (AuthenticationError, DeploymentError, GraphApiError) as exc:
            _print_error(console, _format_exception_message(exc))
            return 1

    if args.subcommand == "demo-access":
        from .deploy import _run_demo_access

        return _run_demo_access(args, console)

    _print_banner(console)

    # In demo mode, auto-enable non-interactive when stdin is not a TTY
    # (e.g. CI, subprocess, Docker) to avoid questionary crashes.
    non_interactive = args.non_interactive
    if not non_interactive and args.demo and not sys.stdin.isatty():
        non_interactive = True
    if non_interactive and args.demo:
        _apply_non_interactive_demo_defaults(args)
    total_steps = 4

    try:
        import questionary

        from .deploy import _run_demo_deploy, _run_outlook_deploy
        from .prompts import _POINTER, _QMARK, _STYLE

        # Parse --var KEY=VALUE arguments up front so errors surface early.
        cli_var_values = _parse_var_args(args.vars)

        # Non-interactive mode: require --canary-type.
        if non_interactive and not args.canary_type:
            raise DeploymentError("--canary-type is required in --non-interactive mode. Options: outlook.")

        # Step 1: Canary configuration
        _step_rule(console, 1, total_steps, "Canary Configuration")

        if args.canary_type:
            canary_type = args.canary_type
        else:
            canary_type = questionary.select(
                "Select canary type:",
                choices=[
                    questionary.Choice("Outlook (hidden email)", value="outlook"),
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
            return _run_demo_deploy(console, canary_type, rendered_template, args.delivery_mode)

        return _run_outlook_deploy(
            args,
            console,
            rendered_template,
            non_interactive,
            total_steps,
            cli_var_values,
        )

    except (AuthenticationError, DeploymentError, GraphApiError) as exc:
        _print_error(console, _format_exception_message(exc))
        return 1
    except AnglerfishError as exc:
        _print_error(console, _format_exception_message(exc))
        return 1
    except KeyboardInterrupt:
        console.print("\n[yellow]Cancelled.[/yellow]")
        return 130
