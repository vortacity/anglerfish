"""Alert dispatcher with pluggable output channels."""

from __future__ import annotations

import json
import logging
from dataclasses import asdict
from pathlib import Path
from typing import TYPE_CHECKING

import requests
from rich.console import Console
from rich.panel import Panel

if TYPE_CHECKING:
    from .monitor import CanaryAlert

logger = logging.getLogger(__name__)


class AlertDispatcher:
    """Fan-out alerts to multiple channels.

    Each channel is independently try/excepted so one failure
    does not prevent delivery to other channels.
    """

    def __init__(
        self,
        *,
        console: Console | None = None,
        alert_log: str | Path | None = None,
        webhook_url: str | None = None,
    ):
        self._console = console
        self._alert_log = Path(alert_log) if alert_log else None
        self._webhook_url = webhook_url

    def dispatch(self, alert: CanaryAlert) -> None:
        """Send an alert to all configured channels."""
        if self._console is not None:
            try:
                _render_console(self._console, alert)
            except Exception:
                logger.warning("Console alert rendering failed", exc_info=True)

        if self._alert_log is not None:
            try:
                _append_jsonl(self._alert_log, alert)
            except Exception:
                logger.warning("JSONL alert logging failed", exc_info=True)

        if self._webhook_url is not None:
            try:
                _post_webhook(self._webhook_url, alert)
            except Exception:
                logger.warning("Webhook alert POST failed", exc_info=True)


# ------------------------------------------------------------------
# Console channel
# ------------------------------------------------------------------


def _render_console(console: Console, alert: CanaryAlert) -> None:
    """Print a Rich panel for a canary access alert."""
    lines = [
        f"[bold]Type:[/bold]        {alert.canary_type}",
        f"[bold]Canary:[/bold]      {alert.template_name}",
        f"[bold]Artifact:[/bold]    {alert.artifact_label}",
        f"[bold]Accessed by:[/bold] {alert.accessed_by}",
        f"[bold]Source IP:[/bold]   {alert.source_ip}",
        f"[bold]Timestamp:[/bold]   {alert.timestamp}",
        f"[bold]Operation:[/bold]   {alert.operation}",
    ]
    if alert.client_info:
        lines.append(f"[bold]Client:[/bold]     {alert.client_info}")
    lines.append(f"[bold]Record:[/bold]     {alert.record_path}")

    panel = Panel(
        "\n".join(lines),
        title="[bold red]CANARY ACCESS DETECTED[/bold red]",
        border_style="red",
        expand=False,
    )
    console.print(panel)


# ------------------------------------------------------------------
# JSONL file channel
# ------------------------------------------------------------------


def _append_jsonl(path: Path, alert: CanaryAlert) -> None:
    """Append one JSON object per line to the alert log."""
    path.parent.mkdir(parents=True, exist_ok=True)
    record = asdict(alert)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(record, default=str) + "\n")


# ------------------------------------------------------------------
# Webhook channel
# ------------------------------------------------------------------


def _post_webhook(url: str, alert: CanaryAlert) -> None:
    """HTTP POST alert as JSON. Fire-and-forget with warning on failure."""
    payload = asdict(alert)
    resp = requests.post(url, json=payload, timeout=10)
    if not resp.ok:
        logger.warning("Webhook POST to %s returned HTTP %d", url, resp.status_code)
