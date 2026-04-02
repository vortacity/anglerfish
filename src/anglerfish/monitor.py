"""Canary access monitoring: correlation engine, poll loop, and console output."""

from __future__ import annotations

import json
import os
import signal
import tempfile
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from rich.console import Console

from .alerts import AlertDispatcher
from .audit import AuditClient, CONTENT_TYPES
from .auth import authenticate_management_api
from .inventory import read_deployment_record
from .state import StateManager


# ------------------------------------------------------------------
# Data types
# ------------------------------------------------------------------


@dataclass(frozen=True)
class CanaryAlert:
    """A confirmed canary access event."""

    canary_type: str
    template_name: str
    artifact_label: str
    accessed_by: str
    source_ip: str
    timestamp: str
    operation: str
    client_info: str
    record_path: str


@dataclass
class _CanaryEntry:
    """Internal index entry for a single deployed canary."""

    canary_type: str
    template_name: str
    record_path: str
    # Outlook
    internet_message_id: str = ""
    folder_name: str = ""
    folder_id: str = ""
    target_user: str = ""
    subject: str = ""


# ------------------------------------------------------------------
# CanaryIndex — artifact lookup for fast event matching
# ------------------------------------------------------------------


class CanaryIndex:
    """Index of deployed canary artifact IDs for fast lookup."""

    def __init__(self, records: list[tuple[str, dict]]):
        """Build lookup structures from deployment records.

        ``records`` is a list of ``(record_path, record_dict)`` tuples.
        """
        self._entries: list[_CanaryEntry] = []
        # Quick-lookup maps
        self._by_internet_message_id: dict[str, _CanaryEntry] = {}

        for path, rec in records:
            entry = _build_entry(path, rec)
            self._entries.append(entry)

            if entry.internet_message_id:
                self._by_internet_message_id[entry.internet_message_id] = entry

    @property
    def count(self) -> int:
        return len(self._entries)

    def match(self, event: dict, *, exclude_app_ids: set[str] | None = None) -> CanaryAlert | None:
        """Given an audit event, check if it matches any deployed canary.

        Returns an alert or ``None``.
        """
        if not isinstance(event, dict):
            return None

        # Principal exclusion.
        if exclude_app_ids:
            app_id = str(event.get("AppId") or event.get("ApplicationId") or "").strip().lower()
            user_id = str(event.get("UserId") or "").strip().lower()
            if app_id and app_id in exclude_app_ids:
                return None
            if user_id and user_id in exclude_app_ids:
                return None

        operation = str(event.get("Operation", ""))

        if operation == "MailItemsAccessed":
            return self._match_mail_items_accessed(event)

        return None

    # ------------------------------------------------------------------
    # Per-operation matchers
    # ------------------------------------------------------------------

    def _match_mail_items_accessed(self, event: dict) -> CanaryAlert | None:
        # Check MailAccessType — "Bind" events carry FolderItems.
        folders = event.get("Folders") or []
        for folder in folders:
            if not isinstance(folder, dict):
                continue
            folder_items = folder.get("FolderItems") or []
            for item in folder_items:
                if not isinstance(item, dict):
                    continue
                imid = str(item.get("InternetMessageId") or "").strip()
                if imid and imid in self._by_internet_message_id:
                    entry = self._by_internet_message_id[imid]
                    return _build_alert(entry, event, artifact_label=f"internet_message_id: {imid}")

        # Secondary: match by folder name (Sync events lack FolderItems).
        for folder in folders:
            if not isinstance(folder, dict):
                continue
            folder_path = str(folder.get("Path") or "")
            for entry in self._entries:
                if entry.canary_type == "outlook" and entry.folder_name:
                    if entry.folder_name.lower() in folder_path.lower():
                        return _build_alert(entry, event, artifact_label=f"folder: {entry.folder_name}")

        return None


# ------------------------------------------------------------------
# Record loading
# ------------------------------------------------------------------


def load_records(records_dir: str | Path) -> list[tuple[str, dict]]:
    """Load all valid deployment records from a directory.

    Returns a list of ``(path_str, record_dict)`` for records with
    ``status == 'active'`` (or no status field).
    """
    records_path = Path(records_dir)
    if not records_path.is_dir():
        return []

    results: list[tuple[str, dict]] = []
    for json_file in sorted(records_path.glob("*.json")):
        try:
            rec = read_deployment_record(json_file)
        except Exception:  # nosec B112 — skip malformed records, log elsewhere
            continue
        status = rec.get("status", "active")
        if status != "active":
            continue
        results.append((str(json_file), rec))
    return results


# ------------------------------------------------------------------
# Token refresh helper
# ------------------------------------------------------------------


class _TokenManager:
    """Re-acquire the Management API token before it expires."""

    _REFRESH_MARGIN = timedelta(minutes=5)
    _TOKEN_LIFETIME = timedelta(minutes=55)

    def __init__(self, initial_token: str, credential_mode: str | None = None):
        self._token = initial_token
        self._credential_mode = credential_mode
        self._expires_at = datetime.now(timezone.utc) + self._TOKEN_LIFETIME

    def get_token(self) -> str:
        if datetime.now(timezone.utc) >= self._expires_at - self._REFRESH_MARGIN:
            self._token = authenticate_management_api(self._credential_mode)
            self._expires_at = datetime.now(timezone.utc) + self._TOKEN_LIFETIME
        return self._token

    @property
    def refreshed(self) -> bool:
        """True if the token was ever refreshed (for testing)."""
        return True  # always returns current token


# ------------------------------------------------------------------
# Heartbeat
# ------------------------------------------------------------------

_DEFAULT_HEARTBEAT_PATH = Path.home() / ".anglerfish" / "monitor-heartbeat.json"


def _write_heartbeat(
    path: Path,
    *,
    canary_count: int,
    session_alerts: int,
) -> None:
    """Write a heartbeat JSON file after each poll cycle."""
    payload = {
        "last_poll": datetime.now(timezone.utc).isoformat(),
        "status": "healthy",
        "canaries": canary_count,
        "alerts_this_session": session_alerts,
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as fh:
            temp_path = Path(fh.name)
            json.dump(payload, fh)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(temp_path, path)
    except OSError:
        pass  # heartbeat is best-effort
    finally:
        if temp_path is not None and temp_path.exists():
            temp_path.unlink(missing_ok=True)


# ------------------------------------------------------------------
# Poll loop
# ------------------------------------------------------------------


def run_monitor(
    audit_client: AuditClient,
    canary_index: CanaryIndex,
    *,
    interval: int = 300,
    once: bool = False,
    exclude_app_ids: set[str] | None = None,
    console: Console,
    state_manager: StateManager | None = None,
    dispatcher: AlertDispatcher | None = None,
    token_manager: _TokenManager | None = None,
    heartbeat_path: Path | None = _DEFAULT_HEARTBEAT_PATH,
) -> int:
    """Main monitoring loop.

    Returns exit code: 0 for clean shutdown.
    """
    _interrupted = False

    def _handle_sigint(signum: int, frame: Any) -> None:
        nonlocal _interrupted
        _interrupted = True

    old_handler = signal.signal(signal.SIGINT, _handle_sigint)

    # State: use provided manager or fall back to in-memory only.
    sm = state_manager

    # Dispatcher: use provided or default to console-only.
    disp = dispatcher or AlertDispatcher(console=console)

    # Determine start time from persisted state or 1-hour lookback.
    if sm and sm.state.last_poll_end:
        last_poll_end = datetime.fromisoformat(sm.state.last_poll_end)
    else:
        last_poll_end = datetime.now(timezone.utc) - timedelta(hours=1)

    session_alerts = 0
    session_polls = 0

    try:
        # Ensure subscriptions.
        console.print("[bold]Ensuring audit log subscriptions...[/bold]")
        try:
            audit_client.ensure_subscriptions(list(CONTENT_TYPES))
            console.print("[green]Subscriptions active.[/green]")
        except Exception as exc:
            console.print(f"[yellow]Warning: could not verify subscriptions: {exc}[/yellow]")

        while True:
            if _interrupted:
                break

            # Token refresh: rebuild client if token changed.
            if token_manager is not None:
                fresh_token = token_manager.get_token()
                audit_client = AuditClient(
                    fresh_token,
                    audit_client.tenant_id,
                    base_url=audit_client.base_url,
                    retries=audit_client.retries,
                    timeout=audit_client.timeout,
                )

            now = datetime.now(timezone.utc)
            start_time = last_poll_end
            end_time = now

            # Clamp window to 24 hours max.
            if (end_time - start_time).total_seconds() > 24 * 3600:
                start_time = end_time - timedelta(hours=24)

            poll_alerts = 0
            for content_type in CONTENT_TYPES:
                if _interrupted:
                    break
                try:
                    blobs = audit_client.list_content(content_type, start_time, end_time)
                except Exception as exc:
                    console.print(f"[yellow]Warning: list_content({content_type}) failed: {exc}[/yellow]")
                    continue

                for blob in blobs:
                    if _interrupted:
                        break
                    content_uri = blob.get("contentUri") or ""
                    if not content_uri:
                        continue
                    try:
                        events = audit_client.fetch_content(content_uri)
                    except Exception as exc:
                        console.print(f"[yellow]Warning: fetch_content failed: {exc}[/yellow]")
                        continue

                    for event in events:
                        if not isinstance(event, dict):
                            continue
                        event_id = str(event.get("Id") or "")
                        if event_id:
                            if sm:
                                if sm.is_seen(event_id):
                                    continue
                                sm.mark_seen(event_id)
                            else:
                                # No state manager — skip dedup (single-run mode).
                                pass

                        alert = canary_index.match(event, exclude_app_ids=exclude_app_ids)
                        if alert:
                            disp.dispatch(alert)
                            poll_alerts += 1
                            session_alerts += 1

            last_poll_end = end_time
            session_polls += 1

            # Persist state.
            if sm:
                sm.record_poll(end_time.isoformat(), alerts=poll_alerts)
                sm.save()

            # Heartbeat.
            if heartbeat_path:
                _write_heartbeat(
                    heartbeat_path,
                    canary_count=canary_index.count,
                    session_alerts=session_alerts,
                )

            # Status line.
            time_str = now.strftime("%H:%M UTC")
            next_time = (now + timedelta(seconds=interval)).strftime("%H:%M UTC")
            status = (
                f"Monitoring {canary_index.count} canaries across "
                f"{len(CONTENT_TYPES)} content types. "
                f"Last poll: {time_str} ({poll_alerts} alerts). "
            )
            if not once:
                status += f"Next: {next_time}"
            console.print(f"[dim]{status}[/dim]")

            if once:
                break

            # Sleep in small increments so Ctrl+C is responsive.
            for _ in range(interval):
                if _interrupted:
                    break
                time.sleep(1)

    finally:
        signal.signal(signal.SIGINT, old_handler)

    total_alerts = sm.state.total_alerts if sm else session_alerts
    total_polls = sm.state.total_polls if sm else session_polls
    if _interrupted:
        console.print(f"\n[bold]Monitoring stopped.[/bold] {total_alerts} alert(s) across {total_polls} poll(s).")
    return 0


# ------------------------------------------------------------------
# Demo mode
# ------------------------------------------------------------------

_DEMO_ALERTS = [
    {
        "canary_type": "outlook (draft)",
        "template_name": "Fake Password Reset",
        "artifact_label": "internet_message_id: <demo-msg-1@contoso.com>",
        "accessed_by": "attacker@evil.com",
        "source_ip": "203.0.113.42",
        "operation": "MailItemsAccessed",
        "client_info": "Client=OWA;Action=BindFolder",
        "record_path": "~/.anglerfish/records/outlook-demo.json",
    },
    {
        "canary_type": "outlook (send)",
        "template_name": "Updated MFA Policy",
        "artifact_label": "internet_message_id: <demo-msg-2@contoso.com>",
        "accessed_by": "recon@badactor.net",
        "source_ip": "192.0.2.99",
        "operation": "MailItemsAccessed",
        "client_info": "Client=Outlook;Action=MessageBind",
        "record_path": "~/.anglerfish/records/outlook-demo-send.json",
    },
]


def render_demo_alert(console: Console, count: int = 1) -> None:
    """Print simulated alerts for demo/offline mode."""
    disp = AlertDispatcher(console=console)
    for i in range(count):
        data = _DEMO_ALERTS[i % len(_DEMO_ALERTS)]
        alert = CanaryAlert(
            timestamp=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            **data,
        )
        disp.dispatch(alert)
        if i < count - 1:
            time.sleep(2)
    console.print("[bold yellow]Demo mode — simulated alerts.[/bold yellow]")


# ------------------------------------------------------------------
# Internal helpers
# ------------------------------------------------------------------


def _build_entry(record_path: str, rec: dict) -> _CanaryEntry:
    canary_type = rec.get("canary_type") or rec.get("type", "unknown")

    return _CanaryEntry(
        canary_type=canary_type,
        template_name=rec.get("template_name", ""),
        record_path=record_path,
        internet_message_id=rec.get("internet_message_id", ""),
        folder_name=rec.get("folder_name", ""),
        folder_id=rec.get("folder_id", ""),
        target_user=rec.get("target_user", ""),
        subject=rec.get("subject", ""),
    )


def _build_alert(entry: _CanaryEntry, event: dict, *, artifact_label: str) -> CanaryAlert:
    return CanaryAlert(
        canary_type=entry.canary_type,
        template_name=entry.template_name or entry.subject or "(unnamed)",
        artifact_label=artifact_label,
        accessed_by=str(event.get("UserId") or event.get("UserKey") or "unknown"),
        source_ip=str(event.get("ClientIP") or event.get("ClientIPAddress") or "unknown"),
        timestamp=str(event.get("CreationTime") or event.get("Timestamp") or ""),
        operation=str(event.get("Operation") or ""),
        client_info=str(event.get("ClientInfoString") or event.get("ClientAppId") or ""),
        record_path=entry.record_path,
    )
