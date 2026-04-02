"""Deploy, cleanup, list, and verify subcommands + helpers."""

from __future__ import annotations

import argparse
import dataclasses
import datetime
from pathlib import Path

import questionary
from rich import box
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from ..auth import authenticate
from ..deployers.outlook import OutlookDeployer
from ..deployers.outlook import remove_canary as outlook_remove_canary
from ..exceptions import (
    AnglerfishError,
    AuthenticationError,
    DeploymentError,
    GraphApiError,
)
from ..graph import GraphClient
from ..inventory import read_deployment_record, update_deployment_status, write_deployment_record
from ..models import OutlookTemplate
from ._main import (
    _format_exception_message,
    _print_auth_success,
    _print_banner,
    _print_error,
    _print_success,
    _print_summary_table,
    _step_rule,
)
from .prompts import (
    _POINTER,
    _QMARK,
    _STYLE,
    _prompt_auth_setup,
    _validate_email,
    _validate_non_empty,
)


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
        template_name = str(record.get("template_name", "\u2014"))
        target = str(record.get("target_user") or record.get("site_name") or "\u2014")
        timestamp = str(record.get("timestamp", "\u2014"))

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
            console.print("[bold yellow]Demo mode \u2014 no API calls were made.[/bold yellow]")
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
            raise DeploymentError("OneDrive cleanup is no longer supported.")
        else:
            raise DeploymentError("SharePoint cleanup is no longer supported.")

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


def _run_sharepoint_deploy(
    args: argparse.Namespace,
    console: Console,
    template: OutlookTemplate,
    non_interactive: bool,
    total_steps: int,
    cli_var_values: dict[str, str],
) -> int:
    raise DeploymentError("SharePoint deployment is no longer supported.")


def _run_outlook_deploy(
    args: argparse.Namespace,
    console: Console,
    template: OutlookTemplate,
    non_interactive: bool,
    total_steps: int,
    cli_var_values: dict[str, str],
) -> int:
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
        summary_rows.append(("Mode", "DRY RUN \u2014 no writes"))
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
    template: OutlookTemplate,
) -> int:
    """Print simulated deployment output for demo/offline mode."""
    console.print()
    console.rule("[bold]Simulated Deployment (demo mode)[/bold]")
    console.print()
    rows: list[tuple[str, str]] = [
        ("Mode", "DEMO \u2014 no API calls"),
        ("Canary type", canary_type),
        ("Template", template.name),
    ]
    rows.append(("Subject", template.subject))
    rows.append(("Sender", f"{template.sender_name} <{template.sender_email}>"))
    _print_summary_table(console, rows)
    _print_success(console, {"status": "deployed (demo)", "canary_type": canary_type, "template": template.name})
    console.print("[bold yellow]Demo mode \u2014 no authentication or Graph API calls were made.[/bold yellow]")
    return 0


def _run_onedrive_deploy(
    args: argparse.Namespace,
    console: Console,
    template: OutlookTemplate,
    non_interactive: bool,
    total_steps: int,
    cli_var_values: dict[str, str],
) -> int:
    raise DeploymentError("OneDrive deployment is no longer supported.")


def _run_verify(args: argparse.Namespace, console: Console) -> int:
    """Verify deployed canaries still exist via Graph API."""
    from ..monitor import load_records
    from ..verify import VerifyResult, VerifyStatus, run_verify

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
        console.print("[bold yellow]Demo mode \u2014 no Graph API calls were made.[/bold yellow]")

    return 1 if any_bad else 0
