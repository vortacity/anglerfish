"""Monitor subcommand."""

from __future__ import annotations

import argparse
import os
from datetime import timedelta

from rich.console import Console

from ..auth import AuthConfig, authenticate_management_api_with_expiry
from ..exceptions import AuthenticationError
from ._main import _print_banner
from .prompts import _prompt_auth_setup


def _normalize_auth_prompt_result(result: AuthConfig | str | None) -> AuthConfig | None:
    """Tolerate legacy stubs that return a bare credential-mode string."""
    if result is None:
        return None
    if isinstance(result, AuthConfig):
        return result
    return AuthConfig(credential_mode=str(result))


def _run_monitor(args: argparse.Namespace, console: Console) -> int:
    """Run the canary access monitoring loop."""
    from ..alerts import AlertDispatcher
    from ..audit import AuditClient
    from ..config import (
        MONITOR_ALERT_LOG,
        MONITOR_NO_CONSOLE,
        MONITOR_SLACK_WEBHOOK,
        MONITOR_STATE_FILE,
        MONITOR_TEAMS_WEBHOOK,
        MONITOR_WEBHOOK_HMAC_SECRET,
        MONITOR_WEBHOOK_URL,
    )
    from ..monitor import CanaryIndex, _TokenManager, load_records, render_demo_alert, run_monitor
    from ..state import StateManager

    _print_banner(console)

    if getattr(args, "demo", False):
        render_demo_alert(console, count=getattr(args, "demo_count", 1))
        return 0

    lookback_hours = max(float(getattr(args, "cleaned_up_lookback_hours", 24.0)), 0.0)
    records = load_records(args.records_dir, cleaned_up_lookback=timedelta(hours=lookback_hours))
    if not records:
        console.print(f"[yellow]No active or recently cleaned deployment records found in {args.records_dir}[/yellow]")
        console.print(
            "[dim]Deploy canaries with --output-json to create records, "
            "or pass --records-dir to specify a different path.[/dim]"
        )
        return 1

    canary_index = CanaryIndex(records)
    console.print(f"Loaded [bold]{canary_index.count}[/bold] monitored canary record(s).")

    # Auth
    cli_tenant_id = str(args.tenant_id or "").strip()
    tenant_id = cli_tenant_id or os.environ.get("ANGLERFISH_TENANT_ID", "").strip()
    if not tenant_id:
        raise AuthenticationError(
            "ANGLERFISH_TENANT_ID is required for monitoring. Set it via environment variable or --tenant-id."
        )

    auth_config = _normalize_auth_prompt_result(_prompt_auth_setup(args, console, auth_mode="application"))
    if auth_config is None:
        return 130
    token, token_expires_in = authenticate_management_api_with_expiry(auth_config=auth_config)
    audit_client = AuditClient(token, tenant_id)

    exclude_ids = {aid.strip().lower() for aid in args.exclude_app_ids if aid.strip()}

    # State persistence.
    state_file = args.state_file or MONITOR_STATE_FILE or None
    state_manager = StateManager(state_file) if state_file else StateManager()

    # Alert dispatcher.
    no_console = args.no_console or MONITOR_NO_CONSOLE
    alert_log = args.alert_log or MONITOR_ALERT_LOG or None
    slack_webhook = getattr(args, "slack_webhook_url", None) or MONITOR_SLACK_WEBHOOK or None
    teams_webhook = getattr(args, "teams_webhook_url", None) or MONITOR_TEAMS_WEBHOOK or None
    webhook_url = getattr(args, "webhook_url", None) or MONITOR_WEBHOOK_URL or None
    dispatcher = AlertDispatcher(
        console=None if no_console else console,
        alert_log=alert_log,
        slack_webhook_url=slack_webhook,
        teams_webhook_url=teams_webhook,
        webhook_url=webhook_url,
        webhook_hmac_secret=MONITOR_WEBHOOK_HMAC_SECRET or None,
    )

    # Token manager for automatic refresh.
    token_mgr = _TokenManager(
        token,
        auth_config=auth_config,
        expires_in=token_expires_in,
    )

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
