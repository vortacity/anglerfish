"""Canary access monitoring: correlation engine, poll loop, and console output."""

from __future__ import annotations

import logging
import os
import signal
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Sequence

from rich.console import Console

from ._io import as_utc, parse_utc_datetime, write_json_atomic
from .alerts import AlertDispatcher
from .audit import AuditClient, CONTENT_TYPES
from .auth import authenticate_management_api_with_expiry
from .exceptions import MonitorError
from .inventory import DeploymentRecord, coerce_record, read_deployment_record
from .state import StateManager

logger = logging.getLogger(__name__)


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
    canary_id: str = ""
    expires_at: datetime | None = None


# ------------------------------------------------------------------
# CanaryIndex — artifact lookup for fast event matching
# ------------------------------------------------------------------


class CanaryIndex:
    """Index of deployed canary artifact IDs for fast lookup."""

    def __init__(self, records: Sequence[tuple[str, DeploymentRecord | dict]]):
        """Build lookup structures from deployment records.

        ``records`` is a list of ``(record_path, record)`` tuples.
        """
        self._entries: list[_CanaryEntry] = []
        # Quick-lookup maps
        self._by_internet_message_id: dict[str, _CanaryEntry] = {}

        for path, rec in records:
            entry = _build_entry(path, coerce_record(rec))
            self._entries.append(entry)

            if entry.internet_message_id:
                self._by_internet_message_id[entry.internet_message_id] = entry

    @property
    def count(self) -> int:
        return len(self._entries)

    def match(
        self,
        event: dict,
        *,
        exclude_app_ids: set[str] | None = None,
        now: datetime | None = None,
    ) -> CanaryAlert | None:
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
            return self._match_mail_items_accessed(event, now=now)

        return None

    # ------------------------------------------------------------------
    # Per-operation matchers
    # ------------------------------------------------------------------

    def _match_mail_items_accessed(self, event: dict, *, now: datetime | None = None) -> CanaryAlert | None:
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
                    if _entry_is_expired(entry, now):
                        continue
                    return _build_alert(entry, event, artifact_label=f"internet_message_id: {imid}")

        # Secondary: match by folder name (Sync events lack FolderItems).
        for folder in folders:
            if not isinstance(folder, dict):
                continue
            event_folder_id = str(folder.get("Id") or "").strip()
            folder_path = str(folder.get("Path") or "")
            for entry in self._entries:
                if _entry_is_expired(entry, now):
                    continue
                if entry.canary_type != "outlook":
                    continue
                if entry.folder_id and event_folder_id and entry.folder_id == event_folder_id:
                    return _build_alert(entry, event, artifact_label=f"folder_id: {entry.folder_id}")
                if entry.canary_id and entry.folder_name:
                    folder_path_lower = folder_path.casefold()
                    if (
                        entry.canary_id.casefold() in folder_path_lower
                        and entry.folder_name.casefold() in folder_path_lower
                    ):
                        return _build_alert(entry, event, artifact_label=f"folder: {entry.folder_name}")

        return None


# ------------------------------------------------------------------
# Record loading
# ------------------------------------------------------------------


def load_records(
    records_dir: str | Path,
    *,
    cleaned_up_lookback: timedelta | None = None,
    now: datetime | None = None,
) -> list[tuple[str, DeploymentRecord]]:
    """Load all valid deployment records from a directory.

    Returns a list of ``(path_str, record)`` for records with
    ``status == 'active'`` (or no status field), plus recently cleaned records
    when requested, that still belong to the supported Outlook monitoring
    surface.
    """
    records_path = Path(records_dir)
    if not records_path.is_dir():
        return []

    current_time = now or datetime.now(timezone.utc)
    results: list[tuple[str, DeploymentRecord]] = []
    for json_file in sorted(records_path.glob("*.json")):
        # Skip records that are unreadable, corrupt, or incomplete, but log the
        # skip so an operator knows a deployed canary dropped out of monitoring.
        try:
            rec = read_deployment_record(json_file)
        except Exception as exc:
            logger.warning("Skipping unreadable deployment record %s: %s", json_file, exc.__class__.__name__)
            continue
        expires_at: datetime | None = None
        if rec.status == "active":
            include = True
        elif rec.status == "cleaned_up" and cleaned_up_lookback is not None:
            include = _within_cleaned_up_lookback(rec, current_time, cleaned_up_lookback)
            if include:
                updated = parse_utc_datetime(rec.status_updated_at)
                if updated is not None:
                    expires_at = updated + cleaned_up_lookback
        else:
            include = False
        if not include:
            continue
        if rec.canary_type != "outlook":
            continue
        rec.monitor_expires_at = expires_at
        results.append((str(json_file), rec))
    return results


def _within_cleaned_up_lookback(rec: DeploymentRecord, now: datetime, lookback: timedelta) -> bool:
    if lookback < timedelta(0):
        return False
    updated = parse_utc_datetime(rec.status_updated_at)
    if updated is None:
        return False
    age = as_utc(now) - updated
    return timedelta(0) <= age <= lookback


def _entry_is_expired(entry: _CanaryEntry, now: datetime | None) -> bool:
    if entry.expires_at is None:
        return False
    current_time = as_utc(now or datetime.now(timezone.utc))
    return current_time > entry.expires_at


# ------------------------------------------------------------------
# Token refresh helper
# ------------------------------------------------------------------


class _TokenManager:
    """Re-acquire the Management API token before it expires."""

    _REFRESH_MARGIN = timedelta(minutes=5)
    _DEFAULT_LIFETIME = timedelta(minutes=55)

    def __init__(
        self,
        initial_token: str,
        credential_mode: str | None = None,
        *,
        prompted_env: dict[str, str] | None = None,
        expires_in: int | None = None,
    ):
        self._token = initial_token
        self._credential_mode = credential_mode
        self._lifetime = self._lifetime_from_expires_in(expires_in)
        self._expires_at = datetime.now(timezone.utc) + self._lifetime
        self._prompted_env = dict(prompted_env or {})

    @classmethod
    def _lifetime_from_expires_in(cls, expires_in: int | None) -> timedelta:
        if expires_in is None or expires_in <= 0:
            return cls._DEFAULT_LIFETIME
        return timedelta(seconds=expires_in)

    def get_token(self) -> str:
        # Tenant policy can issue tokens shorter than the margin; never let the
        # margin consume the whole lifetime or every call would re-authenticate.
        margin = min(self._REFRESH_MARGIN, self._lifetime / 2)
        if datetime.now(timezone.utc) >= self._expires_at - margin:
            previous_env = {name: os.environ.get(name) for name in self._prompted_env}
            try:
                for name, value in self._prompted_env.items():
                    os.environ[name] = value
                self._token, expires_in = authenticate_management_api_with_expiry(self._credential_mode)
                self._lifetime = self._lifetime_from_expires_in(expires_in)
                self._expires_at = datetime.now(timezone.utc) + self._lifetime
            finally:
                for name, previous_value in previous_env.items():
                    if previous_value is None:
                        os.environ.pop(name, None)
                    else:
                        os.environ[name] = previous_value
        return self._token


# ------------------------------------------------------------------
# Heartbeat
# ------------------------------------------------------------------

_DEFAULT_HEARTBEAT_PATH = Path.home() / ".anglerfish" / "monitor-heartbeat.json"


def _write_heartbeat(
    path: Path,
    *,
    canary_count: int,
    session_alerts: int,
    status: str = "healthy",
) -> None:
    """Write a heartbeat JSON file after each poll cycle."""
    payload = {
        "last_poll": datetime.now(timezone.utc).isoformat(),
        "status": status,
        "canaries": canary_count,
        "alerts_this_session": session_alerts,
    }
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        write_json_atomic(path, payload, error_cls=MonitorError, label="monitor heartbeat", indent=None)
    except (MonitorError, OSError):
        pass  # heartbeat is best-effort


# ------------------------------------------------------------------
# Poll loop
# ------------------------------------------------------------------

# The Management Activity API serves at most 24 hours per content listing and
# retains content for roughly 7 days.
_MAX_POLL_WINDOW = timedelta(hours=24)
_CONTENT_RETENTION = timedelta(days=7)


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
    # _parse_record_datetime tolerates the 'Z' suffix (rejected by Python 3.10's
    # fromisoformat) and normalizes naive timestamps to aware UTC.
    persisted = parse_utc_datetime(sm.state.last_poll_end) if sm else None
    if persisted is not None:
        last_poll_end = persisted
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

        def _refresh_token(current: str | None) -> str | None:
            """Refresh via the token manager, surviving transient auth failures.

            A long-running monitor must not die because one ~hourly refresh hit
            an AAD blip; keep the current token and retry next cycle.
            """
            if token_manager is None:
                return current
            try:
                return token_manager.get_token()
            except Exception as exc:
                console.print(f"[yellow]Warning: token refresh failed: {exc}. Will retry next cycle.[/yellow]")
                return current

        # Seed with the current token so we only rebuild the client (and discard
        # its connection pool) when the token actually rotates.
        current_token = _refresh_token(None)

        while True:
            if _interrupted:
                break

            # Rebuild the client only when the refreshed token differs.
            fresh_token = _refresh_token(current_token)
            if fresh_token is not None and fresh_token != current_token:
                current_token = fresh_token
                audit_client = AuditClient(
                    fresh_token,
                    audit_client.tenant_id,
                    base_url=audit_client.base_url,
                    retries=audit_client.retries,
                    timeout=audit_client.timeout,
                )

            now = datetime.now(timezone.utc)

            # Content older than the retention window is gone; warn rather than
            # request a range the API cannot serve.
            retention_floor = now - _CONTENT_RETENTION
            if last_poll_end < retention_floor:
                console.print(
                    "[yellow]Warning: monitor was down longer than the audit content retention window; "
                    f"events between {last_poll_end:%Y-%m-%d %H:%M} and "
                    f"{retention_floor:%Y-%m-%d %H:%M} UTC are no longer retrievable.[/yellow]"
                )
                last_poll_end = retention_floor

            # Walk the backlog in <=24h windows (the API maximum) so downtime
            # longer than a day cannot silently skip events.
            windows: list[tuple[datetime, datetime]] = []
            cursor = last_poll_end
            while now - cursor > _MAX_POLL_WINDOW:
                windows.append((cursor, cursor + _MAX_POLL_WINDOW))
                cursor += _MAX_POLL_WINDOW
            windows.append((cursor, now))

            poll_alerts = 0
            all_windows_complete = True
            for start_time, end_time in windows:
                # Track whether the entire window was ingested. If any content
                # list or fetch failed (or we were interrupted mid-window), we
                # must NOT advance the watermark, or those events are skipped
                # forever.
                window_complete = True
                for content_type in CONTENT_TYPES:
                    if _interrupted:
                        window_complete = False
                        break
                    try:
                        blobs = audit_client.list_content(content_type, start_time, end_time)
                    except Exception as exc:
                        console.print(f"[yellow]Warning: list_content({content_type}) failed: {exc}[/yellow]")
                        window_complete = False
                        continue

                    for blob in blobs:
                        if _interrupted:
                            window_complete = False
                            break
                        if not isinstance(blob, dict):
                            continue
                        content_uri = blob.get("contentUri") or ""
                        if not content_uri:
                            continue
                        try:
                            events = audit_client.fetch_content(content_uri)
                        except Exception as exc:
                            console.print(f"[yellow]Warning: fetch_content failed: {exc}[/yellow]")
                            window_complete = False
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

                            alert = canary_index.match(event, exclude_app_ids=exclude_app_ids, now=now)
                            if alert:
                                disp.dispatch(alert)
                                poll_alerts += 1
                                session_alerts += 1

                # Only advance the watermark when the whole window was ingested.
                # Re-polling an incomplete window is safe: seen-ID dedup
                # suppresses any alerts that were already dispatched. Stop at
                # the first incomplete window so ingestion stays in order.
                if window_complete:
                    last_poll_end = end_time
                else:
                    all_windows_complete = False
                    break
            session_polls += 1

            # Persist state.
            if sm:
                sm.record_poll(last_poll_end.isoformat(), alerts=poll_alerts)
                sm.save()

            # Heartbeat.
            if heartbeat_path:
                _write_heartbeat(
                    heartbeat_path,
                    canary_count=canary_index.count,
                    session_alerts=session_alerts,
                    status="healthy" if all_windows_complete else "degraded",
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


_DEMO_BANNER = "[DEMO MODE — NOT A REAL EVENT]"


def render_demo_alert(console: Console, count: int = 1) -> None:
    """Print simulated alerts for demo/offline mode."""
    console.print(f"[bold yellow]{_DEMO_BANNER}[/bold yellow] Format demonstration only; no live tenant evidence.")
    disp = AlertDispatcher(console=console)
    for i in range(count):
        data = dict(_DEMO_ALERTS[i % len(_DEMO_ALERTS)])
        data["template_name"] = f"{_DEMO_BANNER} {data['template_name']}"
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


def _build_entry(record_path: str, rec: DeploymentRecord) -> _CanaryEntry:
    return _CanaryEntry(
        canary_type=rec.canary_type or "unknown",
        template_name=rec.template_name,
        record_path=record_path,
        internet_message_id=rec.internet_message_id,
        folder_name=rec.folder_name,
        folder_id=rec.folder_id,
        target_user=rec.target_user,
        subject=rec.subject,
        canary_id=rec.canary_id,
        expires_at=rec.monitor_expires_at,
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
