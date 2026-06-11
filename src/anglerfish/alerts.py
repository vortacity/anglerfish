"""Alert dispatcher with pluggable output channels."""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
from dataclasses import asdict
from pathlib import Path
from typing import TYPE_CHECKING
from urllib.parse import urlsplit

from ._io import ensure_private_dir

import requests
from rich.console import Console
from rich.markup import escape
from rich.panel import Panel

if TYPE_CHECKING:
    from .models import CanaryAlert

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
        slack_webhook_url: str | None = None,
        teams_webhook_url: str | None = None,
        webhook_url: str | None = None,
        webhook_hmac_secret: str | None = None,
    ):
        self._console = console
        self._alert_log = Path(alert_log) if alert_log else None
        self._slack_webhook_url = slack_webhook_url
        self._teams_webhook_url = teams_webhook_url
        self._webhook_url = webhook_url
        self._webhook_hmac_secret = webhook_hmac_secret

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

        if self._teams_webhook_url is not None:
            try:
                _post_teams(self._teams_webhook_url, alert)
            except Exception:
                logger.warning("Teams alert POST failed", exc_info=True)

        if self._webhook_url is not None:
            try:
                _post_webhook(self._webhook_url, alert, hmac_secret=self._webhook_hmac_secret)
            except Exception:
                logger.warning("Webhook alert POST failed", exc_info=True)


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

    title = "CANARY TAMPERED" if alert.category == "tamper" else "CANARY ACCESS DETECTED"
    panel = Panel(
        "\n".join(lines),
        title=f"[bold red]{title}[/bold red]",
        border_style="red",
        expand=False,
    )
    console.print(panel)


# ------------------------------------------------------------------
# JSONL file channel
# ------------------------------------------------------------------


def _append_jsonl(path: Path, alert: CanaryAlert) -> None:
    """Append one JSON object per line to the alert log."""
    ensure_private_dir(path.parent)
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
    verb = "tampered" if alert.category == "tamper" else "accessed"
    blocks = [
        {
            "type": "header",
            "text": {
                "type": "plain_text",
                "text": f"Canary Alert: {alert.canary_type} canary {verb}",
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
    payload = {"text": f"Canary Alert: {alert.template_name} {verb} by {alert.accessed_by}", "blocks": blocks}
    resp = requests.post(url, json=payload, timeout=10, allow_redirects=False)
    if not resp.ok:
        # Do not log the webhook URL itself; it is a bearer secret.
        logger.warning("Slack POST returned HTTP %d", resp.status_code)


# ------------------------------------------------------------------
# Microsoft Teams channel
# ------------------------------------------------------------------


def _post_teams(url: str, alert: CanaryAlert) -> None:
    """POST an Adaptive Card to a Teams workflow (Power Automate) webhook."""
    if urlsplit(url).scheme != "https":
        # Refuse to send alert payloads (which carry tenant/actor metadata) over
        # cleartext or to a non-URL value.
        logger.warning("Teams webhook URL is not https; skipping Teams alert")
        return
    verb = "tampered" if alert.category == "tamper" else "accessed"
    facts = [
        {"title": "Canary", "value": alert.template_name},
        {"title": "Operation", "value": alert.operation},
        {"title": "Accessed by", "value": alert.accessed_by},
        {"title": "Source IP", "value": alert.source_ip},
        {"title": "Timestamp", "value": alert.timestamp},
        {"title": "Artifact", "value": alert.artifact_label},
    ]
    if alert.client_info:
        facts.append({"title": "Client", "value": alert.client_info})
    facts.append({"title": "Record", "value": alert.record_path})
    card = {
        "type": "AdaptiveCard",
        "$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
        "version": "1.4",
        "body": [
            {
                "type": "TextBlock",
                "size": "Large",
                "weight": "Bolder",
                "color": "Attention",
                "text": f"Canary Alert: {alert.canary_type} canary {verb}",
            },
            {"type": "FactSet", "facts": facts},
        ],
    }
    payload = {
        "type": "message",
        "attachments": [
            {
                "contentType": "application/vnd.microsoft.card.adaptive",
                "contentUrl": None,
                "content": card,
            }
        ],
    }
    resp = requests.post(url, json=payload, timeout=10, allow_redirects=False)
    if not resp.ok:
        # Do not log the webhook URL itself; it is a bearer secret.
        logger.warning("Teams POST returned HTTP %d", resp.status_code)


# ------------------------------------------------------------------
# Generic webhook channel
# ------------------------------------------------------------------

#: Version of the JSON body posted to the generic webhook.
WEBHOOK_SCHEMA_VERSION = 1


def _post_webhook(url: str, alert: CanaryAlert, *, hmac_secret: str | None = None) -> None:
    """POST the alert as JSON to a generic HTTPS webhook.

    When *hmac_secret* is configured, the raw request body is signed with
    HMAC-SHA256 and the hex digest is sent as
    ``X-Anglerfish-Signature: sha256=<digest>`` so receivers can verify
    authenticity and integrity.
    """
    if urlsplit(url).scheme != "https":
        logger.warning("Webhook URL is not https; skipping webhook alert")
        return
    payload = {"schema_version": WEBHOOK_SCHEMA_VERSION, **asdict(alert)}
    body = json.dumps(payload, default=str, separators=(",", ":")).encode("utf-8")
    headers = {"Content-Type": "application/json"}
    if hmac_secret:
        digest = hmac.new(hmac_secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
        headers["X-Anglerfish-Signature"] = f"sha256={digest}"
    resp = requests.post(url, data=body, headers=headers, timeout=10, allow_redirects=False)
    if not resp.ok:
        # Do not log the webhook URL itself; it may embed a bearer secret.
        logger.warning("Webhook POST returned HTTP %d", resp.status_code)
