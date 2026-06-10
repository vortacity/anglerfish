"""Alert dispatcher with pluggable output channels."""

from __future__ import annotations

import json
import logging
import math
import os
from dataclasses import asdict
from pathlib import Path
from typing import TYPE_CHECKING
from urllib.parse import urlsplit

import requests
from rich.console import Console
from rich.markup import escape
from rich.panel import Panel

if TYPE_CHECKING:
    from .monitor import CanaryAlert

logger = logging.getLogger(__name__)
_DEFAULT_WEBHOOK_TIMEOUT_SECONDS = 10.0
_WEBHOOK_TIMEOUT_ENV = "ANGLERFISH_ALERT_WEBHOOK_TIMEOUT"


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
        slack_webhook_url: str | None = None,
    ):
        self._console = console
        self._alert_log = Path(alert_log) if alert_log else None
        self._slack_webhook_url = slack_webhook_url

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

        if self._slack_webhook_url is not None:
            try:
                _post_slack(self._slack_webhook_url, alert)
            except Exception:
                logger.warning("Slack alert POST failed", exc_info=True)


# ------------------------------------------------------------------
# Console channel
# ------------------------------------------------------------------


def _render_console(console: Console, alert: CanaryAlert) -> None:
    """Print a Rich panel for a canary access alert.

    Alert fields originate from audit events influenced by the accessing actor
    (e.g. ClientInfoString), so they are escaped to prevent Rich console-markup
    injection or alert spoofing.
    """
    lines = [
        f"[bold]Type:[/bold]        {escape(alert.canary_type)}",
        f"[bold]Canary:[/bold]      {escape(alert.template_name)}",
        f"[bold]Artifact:[/bold]    {escape(alert.artifact_label)}",
        f"[bold]Accessed by:[/bold] {escape(alert.accessed_by)}",
        f"[bold]Source IP:[/bold]   {escape(alert.source_ip)}",
        f"[bold]Timestamp:[/bold]   {escape(alert.timestamp)}",
        f"[bold]Operation:[/bold]   {escape(alert.operation)}",
    ]
    if alert.client_info:
        lines.append(f"[bold]Client:[/bold]     {escape(alert.client_info)}")
    lines.append(f"[bold]Record:[/bold]     {escape(alert.record_path)}")

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
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
    try:
        if hasattr(os, "fchmod"):  # POSIX only; os.open mode already applied otherwise
            os.fchmod(fd, 0o600)
        with os.fdopen(fd, "a", encoding="utf-8") as fh:
            fd = -1
            fh.write(json.dumps(record, default=str) + "\n")
            fh.flush()
            os.fsync(fh.fileno())
    finally:
        if fd >= 0:
            os.close(fd)


# ------------------------------------------------------------------
# Slack channel
# ------------------------------------------------------------------


def _post_slack(url: str, alert: CanaryAlert) -> None:
    """POST a Block Kit message to a Slack incoming webhook."""
    if urlsplit(url).scheme != "https":
        # Refuse to send alert payloads (which carry tenant/actor metadata) over
        # cleartext or to a non-URL value.
        logger.warning("Slack webhook URL is not https; skipping Slack alert")
        return
    blocks = [
        {
            "type": "header",
            "text": {
                "type": "plain_text",
                "text": f"Canary Alert: {alert.canary_type} canary accessed",
            },
        },
        {
            "type": "section",
            "fields": [
                {"type": "mrkdwn", "text": f"*Canary:*\n{alert.template_name}"},
                {"type": "mrkdwn", "text": f"*Operation:*\n{alert.operation}"},
                {"type": "mrkdwn", "text": f"*Accessed by:*\n{alert.accessed_by}"},
                {"type": "mrkdwn", "text": f"*Source IP:*\n{alert.source_ip}"},
                {"type": "mrkdwn", "text": f"*Timestamp:*\n{alert.timestamp}"},
                {"type": "mrkdwn", "text": f"*Artifact:*\n{alert.artifact_label}"},
            ],
        },
        {
            "type": "context",
            "elements": [
                {"type": "mrkdwn", "text": f"Record: `{alert.record_path}`"},
            ],
        },
    ]
    payload = {"text": f"Canary Alert: {alert.template_name} accessed by {alert.accessed_by}", "blocks": blocks}
    resp = requests.post(url, json=payload, timeout=_webhook_timeout(), allow_redirects=False)
    if not resp.ok:
        # Do not log the webhook URL itself; it is a bearer secret.
        logger.warning("Slack POST returned HTTP %d", resp.status_code)


def _webhook_timeout() -> float:
    """Return the configured webhook timeout, falling back to the default."""
    raw = os.environ.get(_WEBHOOK_TIMEOUT_ENV, "").strip()
    if not raw:
        return _DEFAULT_WEBHOOK_TIMEOUT_SECONDS
    try:
        timeout = float(raw)
    except ValueError:
        logger.warning("%s must be a positive number; using default timeout", _WEBHOOK_TIMEOUT_ENV)
        return _DEFAULT_WEBHOOK_TIMEOUT_SECONDS
    if not math.isfinite(timeout) or timeout <= 0:
        logger.warning("%s must be a positive number; using default timeout", _WEBHOOK_TIMEOUT_ENV)
        return _DEFAULT_WEBHOOK_TIMEOUT_SECONDS
    return timeout
