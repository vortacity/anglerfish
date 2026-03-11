"""Dashboard subcommand."""

from __future__ import annotations

import argparse


def _run_dashboard(args: argparse.Namespace) -> int:
    """Launch the Textual TUI dashboard."""
    from ..dashboard import AnglerDashboard

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
