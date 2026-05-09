"""Deploy, cleanup, list, and verify subcommands + helpers."""

from __future__ import annotations

import argparse
import dataclasses
import datetime
import os
from pathlib import Path

import questionary
from rich import box
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from ..auth import authenticate
from ..deployers.outlook import OutlookDeployer
from ..deployers.outlook import remove_canary as outlook_remove_canary
from ..deployers.outlook import trigger_canary_access as outlook_trigger_canary_access
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
    AuthPromptResult,
    _POINTER,
    _QMARK,
    _STYLE,
    _prompt_auth_setup,
    _validate_email,
    _validate_non_empty,
)


def _normalize_auth_prompt_result(result: AuthPromptResult | str | None) -> AuthPromptResult | None:
    if result is None:
        return None
    if isinstance(result, AuthPromptResult):
        return result
    return AuthPromptResult(credential_mode=str(result))


def _clear_prompted_env_values(auth_result: AuthPromptResult) -> None:
    for name, value in auth_result.restore_env_vars:
        os.environ[name] = value
    for name in auth_result.clear_env_vars:
        os.environ.pop(name, None)


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


def _print_demo_access_success(console: Console, result: dict[str, str]) -> None:
    table = Table(show_header=False, show_edge=False, padding=(0, 2))
    table.add_column("Key", style="bold")
    table.add_column("Value")
    for key, value in result.items():
        table.add_row(key, str(value))
    panel = Panel(
        table,
        title="[bold green]\u2713 Canary Access Triggered[/bold green]",
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
        title=f"Deployed Outlook Canary Artifacts  ({records_dir})",
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

    row_count = 0
    for record_file in record_files:
        try:
            record = read_deployment_record(record_file)
        except DeploymentError:
            continue  # Skip malformed records silently

        record_id = record_file.stem[:12]
        canary_type = str(record.get("canary_type", record.get("type", "unknown"))).strip().lower()
        if canary_type != "outlook":
            continue
        template_name = str(record.get("template_name", "\u2014"))
        target = str(record.get("target_user") or "\u2014")
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
        row_count += 1

    if row_count:
        console.print(table)
    else:
        console.print("[yellow]No Outlook deployment records found in[/yellow] " + str(records_dir))
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
        if canary_type != "outlook":
            raise DeploymentError("Only outlook canaries are supported in this release.")
        _print_cleanup_summary(console, record)

        if demo:
            _step_rule(console, 2, total_steps, "Remove (simulated)")
            _print_cleanup_success(console, {"status": "removed (demo)", "canary_type": canary_type})
            console.print("[bold yellow]Demo mode \u2014 no API calls were made.[/bold yellow]")
            return 0

        # Step 2: Authentication
        _step_rule(console, 2, total_steps, "Authentication")
        auth_result = _normalize_auth_prompt_result(
            _prompt_auth_setup(args, console, auth_mode="application", non_interactive=non_interactive)
        )
        if auth_result is None:
            return 130
        console.print("Authenticating with Microsoft Graph...")
        try:
            token = authenticate(auth_mode="application", app_credential_mode=auth_result.credential_mode)
        finally:
            _clear_prompted_env_values(auth_result)
        _print_auth_success(console)
        graph = GraphClient(token)

        # Step 3: Remove
        _step_rule(console, 3, total_steps, "Remove")
        if not non_interactive:
            confirmed = questionary.confirm("Remove this canary?", default=False, style=_STYLE, qmark=_QMARK).ask()
            if not confirmed:
                console.print("[yellow]Cancelled.[/yellow]")
                return 0

        result = outlook_remove_canary(graph, record)

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


def _run_demo_access(args: argparse.Namespace, console: Console) -> int:
    _print_banner(console)
    non_interactive = args.non_interactive

    try:
        _step_rule(console, 1, 3, "Read Record")
        record = read_deployment_record(args.record)
        canary_type = str(record.get("type", record.get("canary_type", ""))).strip().lower()
        if canary_type != "outlook":
            raise DeploymentError("Only outlook canaries are supported in this release.")
        _print_cleanup_summary(console, record)

        if not non_interactive:
            confirmed = questionary.confirm(
                "Read this canary through Graph to generate authorized audit evidence?",
                default=False,
                style=_STYLE,
                qmark=_QMARK,
            ).ask()
            if not confirmed:
                console.print("[yellow]Cancelled.[/yellow]")
                return 0

        _step_rule(console, 2, 3, "Authentication")
        auth_result = _normalize_auth_prompt_result(
            _prompt_auth_setup(args, console, auth_mode="application", non_interactive=non_interactive)
        )
        if auth_result is None:
            return 130
        console.print("Authenticating with Microsoft Graph...")
        try:
            token = authenticate(auth_mode="application", app_credential_mode=auth_result.credential_mode)
        finally:
            _clear_prompted_env_values(auth_result)
        _print_auth_success(console)
        graph = GraphClient(token)

        _step_rule(console, 3, 3, "Trigger Access")
        result = outlook_trigger_canary_access(graph, record)
        _print_demo_access_success(console, result)
        console.print(
            "[dim]Unified Audit Log ingestion is delayed. Run `anglerfish monitor --once` after the "
            "MailItemsAccessed event is available.[/dim]"
        )
        return 0
    except (AuthenticationError, DeploymentError, GraphApiError, AnglerfishError) as exc:
        _print_error(console, _format_exception_message(exc))
        return 1
    except KeyboardInterrupt:
        console.print("\n[yellow]Cancelled.[/yellow]")
        return 130


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

    auth_result = _normalize_auth_prompt_result(
        _prompt_auth_setup(args, console, auth_mode="application", non_interactive=non_interactive)
    )
    if auth_result is None:
        console.print("[yellow]Cancelled.[/yellow]")
        return 130

    console.print("Authenticating with Microsoft Graph...")
    try:
        token = authenticate(
            auth_mode="application",
            app_credential_mode=auth_result.credential_mode,
        )
    finally:
        _clear_prompted_env_values(auth_result)
    graph = GraphClient(token)

    _print_auth_success(console)

    # Step 3: Review
    _step_rule(console, 3, total_steps, "Review")

    summary_rows = [
        ("Type", "outlook"),
        ("Delivery mode", delivery_mode),
        ("App credential mode", auth_result.credential_mode or "env/default"),
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
    delivery_mode: str | None,
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
    if canary_type == "outlook" and delivery_mode:
        rows.append(("Delivery mode", delivery_mode))
    rows.append(("Subject", template.subject))
    rows.append(("Sender", f"{template.sender_name} <{template.sender_email}>"))
    _print_summary_table(console, rows)
    _print_success(console, {"status": "deployed (demo)", "canary_type": canary_type, "template": template.name})
    console.print("[bold yellow]Demo mode \u2014 no authentication or Graph API calls were made.[/bold yellow]")
    return 0


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
                canary_type="outlook",
                template_name="Payroll Direct Deposit Update",
                target="hr@contoso.com",
                status=VerifyStatus.GONE,
                detail="Draft folder not found (404)",
            ),
            VerifyResult(
                canary_type="outlook",
                template_name="Wire Transfer Exception",
                target="finance@contoso.com",
                status=VerifyStatus.ERROR,
                detail="Verify only supports draft-mode outlook records",
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
        pending_graph_checks: list[tuple[int, tuple[str, dict]]] = []
        ordered_results: list[VerifyResult | None] = [None] * len(records)

        for index, record_item in enumerate(records):
            _record_path, record = record_item
            canary_type = str(record.get("canary_type") or record.get("type", ""))
            template_name = str(record.get("template_name", ""))

            if canary_type != "outlook":
                ordered_results[index] = VerifyResult(
                    canary_type=canary_type,
                    template_name=template_name,
                    target="",
                    status=VerifyStatus.ERROR,
                    detail=f"Unsupported canary type: {canary_type}",
                )
                continue

            delivery_mode = str(record.get("delivery_mode", "draft")).strip().lower()
            target_user = str(record.get("target_user", ""))
            if delivery_mode == "send":
                ordered_results[index] = VerifyResult(
                    canary_type="outlook",
                    template_name=template_name,
                    target=target_user,
                    status=VerifyStatus.ERROR,
                    detail="Verify only supports draft-mode outlook records",
                )
                continue

            folder_id = str(record.get("folder_id", ""))
            if not target_user or not folder_id:
                ordered_results[index] = VerifyResult(
                    canary_type="outlook",
                    template_name=template_name,
                    target=target_user,
                    status=VerifyStatus.ERROR,
                    detail="Record missing target_user or folder_id",
                )
                continue

            pending_graph_checks.append((index, record_item))

        if pending_graph_checks:
            # Authenticate only when at least one draft-mode Outlook record requires Graph verification.
            auth_result = _normalize_auth_prompt_result(
                _prompt_auth_setup(args, console, auth_mode="application", non_interactive=True)
            )
            if auth_result is None:
                return 130
            console.print("Authenticating with Microsoft Graph...")
            try:
                token = authenticate(auth_mode="application", app_credential_mode=auth_result.credential_mode)
            finally:
                _clear_prompted_env_values(auth_result)
            graph = GraphClient(token)
            _print_auth_success(console)

            graph_results = run_verify([record_item for _index, record_item in pending_graph_checks], graph)
            for (index, _record_item), graph_result in zip(pending_graph_checks, graph_results):
                ordered_results[index] = graph_result

        results = [result for result in ordered_results if result is not None]

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
