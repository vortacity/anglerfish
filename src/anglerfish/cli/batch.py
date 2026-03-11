"""Batch subcommand."""

from __future__ import annotations

import argparse

from rich import box
from rich.console import Console
from rich.table import Table

from ..auth import authenticate
from ..graph import GraphClient
from ._main import _print_auth_success
from .prompts import _prompt_auth_setup


def _run_batch(args: argparse.Namespace, console: Console) -> int:
    """Run batch deployment from a YAML manifest."""
    from ..batch import parse_manifest, run_batch

    console.print()
    console.rule("[bold]Batch Deployment[/bold]")
    console.print()

    specs = parse_manifest(args.manifest)
    console.print(f"Loaded {len(specs)} canary definition(s) from manifest.")

    if getattr(args, "demo", False):
        results = run_batch(specs, graph=None, output_dir=args.output_dir, dry_run=True)
        console.print("[bold yellow]Demo mode \u2014 no authentication or Graph API calls were made.[/bold yellow]")
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
        record = r.get("record_path", "\u2014")
        table.add_row(str(r["index"]), r["canary_type"], r["target"], r["template"], status, record)

    console.print()
    console.print(table)

    succeeded = sum(1 for r in results if r["success"])
    failed = len(results) - succeeded
    console.print(f"\n[bold]{succeeded} succeeded, {failed} failed[/bold]")

    return 1 if failed > 0 else 0
