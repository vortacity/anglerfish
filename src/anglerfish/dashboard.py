"""Textual TUI dashboard for canary monitoring."""

from __future__ import annotations

import random
from datetime import datetime, timezone

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal
from textual.widgets import DataTable, Footer, Header, RichLog, Static

from . import __version__
from .monitor import CanaryAlert
from .verify import VerifyResult, VerifyStatus


# ------------------------------------------------------------------
# Demo data provider
# ------------------------------------------------------------------

_DEMO_RECORDS: list[tuple[str, dict]] = [
    (
        "~/.anglerfish/records/outlook-cfo-draft.json",
        {
            "canary_type": "outlook",
            "template_name": "Fake Password Reset",
            "target_user": "cfo@contoso.com",
            "folder_name": "IT Notifications",
            "folder_id": "folder-demo-1",
            "internet_message_id": "<demo-msg-1@contoso.com>",
            "subject": "Password Reset Required",
            "status": "active",
        },
    ),
    (
        "~/.anglerfish/records/outlook-hr-send.json",
        {
            "canary_type": "outlook",
            "template_name": "Benefits Update",
            "target_user": "hr@contoso.com",
            "folder_name": "Benefits",
            "folder_id": "folder-demo-2",
            "internet_message_id": "<demo-msg-2@contoso.com>",
            "subject": "Benefits Enrollment",
            "status": "active",
        },
    ),
    (
        "~/.anglerfish/records/sharepoint-hr-salary.json",
        {
            "canary_type": "sharepoint",
            "template_name": "Employee Salary Bands",
            "site_name": "HRSite",
            "site_id": "contoso.sharepoint.com,site-demo-1,web-demo-1",
            "item_id": "item-demo-1",
            "uploaded_files": "salary_bands_2026.xlsx",
            "status": "active",
        },
    ),
    (
        "~/.anglerfish/records/sharepoint-finance-budget.json",
        {
            "canary_type": "sharepoint",
            "template_name": "Q1 Budget Draft",
            "site_name": "FinanceSite",
            "site_id": "contoso.sharepoint.com,site-demo-2,web-demo-2",
            "item_id": "item-demo-2",
            "uploaded_files": "q1_budget_draft.docx",
            "status": "active",
        },
    ),
    (
        "~/.anglerfish/records/onedrive-vpn-config.json",
        {
            "canary_type": "onedrive",
            "template_name": "VPN Credentials Backup",
            "target_user": "j.smith@contoso.com",
            "item_id": "item-demo-3",
            "uploaded_files": "vpn_config.txt",
            "status": "active",
        },
    ),
]

_DEMO_ATTACKERS = [
    ("attacker@evil.com", "203.0.113.42"),
    ("scout@evil.com", "198.51.100.7"),
    ("recon@badactor.net", "192.0.2.99"),
    ("phisher@shady.org", "198.51.100.15"),
    ("apt29@cozylair.ru", "203.0.113.55"),
]

_DEMO_OPERATIONS = {
    "outlook": "MailItemsAccessed",
    "sharepoint": "FileAccessed",
    "onedrive": "FileAccessed",
}


class DemoDataProvider:
    """Synthetic data for --demo mode. No API calls."""

    def __init__(self) -> None:
        self._records = _DEMO_RECORDS
        self._verify_statuses = [
            VerifyStatus.OK,
            VerifyStatus.OK,
            VerifyStatus.GONE,
            VerifyStatus.OK,
            VerifyStatus.OK,
        ]

    def records(self) -> list[tuple[str, dict]]:
        return list(self._records)

    def verify_results(self) -> list[VerifyResult]:
        results: list[VerifyResult] = []
        for i, (_, rec) in enumerate(self._records):
            status = self._verify_statuses[i]
            target = rec.get("target_user") or rec.get("site_name", "")
            detail = "404 Not Found" if status == VerifyStatus.GONE else ""
            results.append(
                VerifyResult(
                    canary_type=rec["canary_type"],
                    template_name=rec["template_name"],
                    target=target,
                    status=status,
                    detail=detail,
                )
            )
        return results

    def generate_alert(self) -> CanaryAlert:
        rec_path, rec = random.choice(self._records)  # nosec B311 — demo data only
        attacker, ip = random.choice(_DEMO_ATTACKERS)  # nosec B311
        canary_type = rec["canary_type"]
        now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        artifact = rec.get("internet_message_id") or rec.get("item_id", "")
        return CanaryAlert(
            canary_type=canary_type,
            template_name=rec["template_name"],
            artifact_label=f"demo: {artifact}",
            accessed_by=attacker,
            source_ip=ip,
            timestamp=now,
            operation=_DEMO_OPERATIONS.get(canary_type, "FileAccessed"),
            client_info="Client=DemoMode",
            record_path=rec_path,
        )

    def cycle_verify_status(self) -> None:
        """Rotate one random status to simulate changes."""
        idx = random.randint(0, len(self._verify_statuses) - 1)  # nosec B311 — demo data only
        current = self._verify_statuses[idx]
        choices = [s for s in VerifyStatus if s != current]
        self._verify_statuses[idx] = random.choice(choices)  # nosec B311


# ------------------------------------------------------------------
# Status styling
# ------------------------------------------------------------------

_STATUS_STYLES = {
    VerifyStatus.OK: "green",
    VerifyStatus.GONE: "red",
    VerifyStatus.ERROR: "yellow",
}


# ------------------------------------------------------------------
# Textual dashboard app
# ------------------------------------------------------------------


class AnglerDashboard(App):
    """Full-screen canary monitoring dashboard."""

    TITLE = "Anglerfish Dashboard"
    CSS = """
    Horizontal {
        height: 1fr;
    }
    DataTable {
        width: 1fr;
    }
    RichLog {
        width: 1fr;
        border-left: solid $accent;
    }
    #stats-bar {
        dock: bottom;
        height: 3;
        padding: 0 1;
        background: $surface;
        color: $text;
    }
    """
    BINDINGS = [
        Binding("q", "quit", "Quit"),
        Binding("r", "refresh", "Refresh"),
    ]

    def __init__(
        self,
        *,
        demo: bool = False,
        records_dir: str = "",
        poll_interval: int = 300,
        verify_interval: int = 300,
        alert_log: str = "",
        exclude_app_ids: list[str] | None = None,
        credential_mode: str | None = None,
    ) -> None:
        super().__init__()
        self._demo = demo
        self._records_dir = records_dir
        self._poll_interval = poll_interval
        self._verify_interval = verify_interval
        self._alert_log = alert_log
        self._exclude_app_ids = exclude_app_ids or []
        self._credential_mode = credential_mode
        self._demo_provider: DemoDataProvider | None = None
        self._alert_count = 0
        self._last_poll = ""
        self._started_at = datetime.now(timezone.utc)

    def compose(self) -> ComposeResult:
        yield Header()
        with Horizontal():
            yield DataTable(id="canary-table")
            yield RichLog(id="alert-feed", markup=True)
        yield Static(id="stats-bar")
        yield Footer()

    def on_mount(self) -> None:
        self.sub_title = f"v{__version__}"
        table = self.query_one("#canary-table", DataTable)
        table.add_columns("#", "Type", "Template", "Target", "Status")

        if self._demo:
            self._demo_provider = DemoDataProvider()
            self._populate_demo_canaries()
            self._update_stats()
            self.set_interval(self._poll_interval, self._demo_poll_tick)
            self.set_interval(self._verify_interval, self._demo_verify_tick)
        else:
            self._init_live_mode()

    def _populate_demo_canaries(self) -> None:
        assert self._demo_provider is not None  # nosec B101 — demo-only guard
        table = self.query_one("#canary-table", DataTable)
        for i, result in enumerate(self._demo_provider.verify_results(), start=1):
            style = _STATUS_STYLES.get(result.status, "white")
            table.add_row(
                str(i),
                result.canary_type,
                result.template_name,
                result.target,
                f"[{style}]{result.status.value}[/{style}]",
            )

    def _demo_poll_tick(self) -> None:
        assert self._demo_provider is not None  # nosec B101 — demo-only guard
        alert = self._demo_provider.generate_alert()
        self._append_alert(alert)

    def _demo_verify_tick(self) -> None:
        assert self._demo_provider is not None  # nosec B101 — demo-only guard
        self._demo_provider.cycle_verify_status()
        self._refresh_canary_table_demo()

    def _refresh_canary_table_demo(self) -> None:
        assert self._demo_provider is not None  # nosec B101 — demo-only guard
        table = self.query_one("#canary-table", DataTable)
        table.clear()
        for i, result in enumerate(self._demo_provider.verify_results(), start=1):
            style = _STATUS_STYLES.get(result.status, "white")
            table.add_row(
                str(i),
                result.canary_type,
                result.template_name,
                result.target,
                f"[{style}]{result.status.value}[/{style}]",
            )

    def _append_alert(self, alert: CanaryAlert) -> None:
        feed = self.query_one("#alert-feed", RichLog)
        self._alert_count += 1
        self._last_poll = datetime.now(timezone.utc).strftime("%H:%M UTC")
        feed.write(
            f"[bold red]{alert.timestamp}  {alert.canary_type.upper()}[/bold red]\n"
            f"  {alert.accessed_by}\n"
            f"  {alert.template_name}\n"
            f"  {alert.source_ip}\n"
        )
        self._update_stats()

    def _update_stats(self) -> None:
        bar = self.query_one("#stats-bar", Static)
        now = datetime.now(timezone.utc)
        uptime = now - self._started_at
        minutes = int(uptime.total_seconds() // 60)
        if self._demo_provider:
            canary_count = len(self._demo_provider.records())
        elif hasattr(self, "_canary_count"):
            canary_count = self._canary_count
        else:
            canary_count = 0
        last = self._last_poll or "\u2014"
        bar.update(
            f"Canaries: {canary_count}  |  Alerts: {self._alert_count}  |  Last poll: {last}  |  Uptime: {minutes}m"
        )

    def action_refresh(self) -> None:
        if self._demo and self._demo_provider:
            self._demo_poll_tick()
            self._demo_verify_tick()
        elif not self._demo:
            self._live_poll_tick()
            self._run_live_verify()

    def _init_live_mode(self) -> None:
        """Initialize live API mode: load records, auth, start polling."""
        import os

        from .audit import AuditClient
        from .config import TENANT_ID
        from .monitor import CanaryIndex, _TokenManager, load_records
        from .state import StateManager

        feed = self.query_one("#alert-feed", RichLog)

        records = load_records(self._records_dir)
        if not records:
            feed.write(f"[yellow]No active records in {self._records_dir}[/yellow]")
            self._update_stats()
            return

        self._canary_index = CanaryIndex(records)
        self._live_records = records
        self._canary_count = self._canary_index.count

        table = self.query_one("#canary-table", DataTable)
        for i, (path, rec) in enumerate(records, start=1):
            table.add_row(
                str(i),
                rec.get("canary_type", ""),
                rec.get("template_name", ""),
                rec.get("target_user") or rec.get("site_name", ""),
                "[dim]...[/dim]",
            )

        feed.write("[bold]Authenticating...[/bold]")
        try:
            from .auth import authenticate, authenticate_management_api

            graph_token = authenticate(
                auth_mode="application",
                app_credential_mode=self._credential_mode,
            )
            from .graph import GraphClient

            self._graph = GraphClient(graph_token)

            tenant_id = os.environ.get("ANGLERFISH_TENANT_ID", TENANT_ID).strip()
            mgmt_token = authenticate_management_api(self._credential_mode)
            self._audit_client = AuditClient(mgmt_token, tenant_id)
            self._token_manager = _TokenManager(mgmt_token, self._credential_mode)
            self._tenant_id = tenant_id

            self._state_manager = StateManager()

            feed.write("[green]Authenticated.[/green]")
        except Exception as exc:
            feed.write(f"[red]Auth failed: {exc}[/red]")
            self._update_stats()
            return

        self._exclude_ids = {aid.strip().lower() for aid in self._exclude_app_ids if aid.strip()} or None

        if self._alert_log:
            self._load_alert_history()

        self._run_live_verify()

        self._update_stats()

        self.set_interval(self._poll_interval, self._live_poll_tick)
        self.set_interval(self._verify_interval, self._run_live_verify)

    def _run_live_verify(self) -> None:
        """Run verify checks and update the canary table."""
        from .verify import verify_record

        if not hasattr(self, "_live_records"):
            return

        table = self.query_one("#canary-table", DataTable)
        table.clear()

        for i, (path, rec) in enumerate(self._live_records, start=1):
            canary_type = rec.get("canary_type", "")
            template_name = rec.get("template_name", "")
            target = rec.get("target_user") or rec.get("site_name", "")
            try:
                result = verify_record(self._graph, rec)
                style = _STATUS_STYLES.get(result.status, "white")
                status_text = f"[{style}]{result.status.value}[/{style}]"
            except Exception:
                status_text = "[yellow]ERROR[/yellow]"
            table.add_row(str(i), canary_type, template_name, target, status_text)

    def _live_poll_tick(self) -> None:
        """Poll audit API for new events."""
        from .audit import CONTENT_TYPES

        if not hasattr(self, "_audit_client"):
            return

        if hasattr(self, "_token_manager"):
            from .audit import AuditClient

            fresh_token = self._token_manager.get_token()
            self._audit_client = AuditClient(
                fresh_token,
                self._tenant_id,
                base_url=self._audit_client.base_url,
                retries=self._audit_client.retries,
                timeout=self._audit_client.timeout,
            )

        now = datetime.now(timezone.utc)
        if not hasattr(self, "_last_poll_end"):
            from datetime import timedelta

            self._last_poll_end = now - timedelta(hours=1)

        start_time = self._last_poll_end
        end_time = now

        from datetime import timedelta

        if (end_time - start_time).total_seconds() > 24 * 3600:
            start_time = end_time - timedelta(hours=24)

        feed = self.query_one("#alert-feed", RichLog)

        for content_type in CONTENT_TYPES:
            try:
                blobs = self._audit_client.list_content(content_type, start_time, end_time)
            except Exception as exc:
                feed.write(f"[yellow]Poll error ({content_type}): {exc}[/yellow]")
                continue

            for blob in blobs:
                content_uri = blob.get("contentUri") or ""
                if not content_uri:
                    continue
                try:
                    events = self._audit_client.fetch_content(content_uri)
                except Exception:  # nosec B112 — skip individual blob failures to keep polling
                    continue

                for event in events:
                    if not isinstance(event, dict):
                        continue
                    event_id = str(event.get("Id") or "")
                    if event_id and hasattr(self, "_state_manager"):
                        if self._state_manager.is_seen(event_id):
                            continue
                        self._state_manager.mark_seen(event_id)

                    alert = self._canary_index.match(event, exclude_app_ids=self._exclude_ids)
                    if alert:
                        self._append_alert(alert)

        self._last_poll_end = end_time
        self._last_poll = now.strftime("%H:%M UTC")
        if hasattr(self, "_state_manager"):
            self._state_manager.record_poll(end_time.isoformat(), alerts=0)
            self._state_manager.save()
        self._update_stats()

    def _load_alert_history(self) -> None:
        """Load existing alert log JSONL into the feed."""
        import json
        from pathlib import Path

        log_path = Path(self._alert_log)
        if not log_path.is_file():
            return
        feed = self.query_one("#alert-feed", RichLog)
        try:
            for line in log_path.read_text(encoding="utf-8").strip().splitlines():
                data = json.loads(line)
                alert = CanaryAlert(**data)
                feed.write(
                    f"[dim]{alert.timestamp}  {alert.canary_type.upper()}[/dim]\n"
                    f"  {alert.accessed_by}\n"
                    f"  {alert.template_name}\n"
                    f"  {alert.source_ip}\n"
                )
                self._alert_count += 1
        except Exception:
            feed.write("[yellow]Could not load alert history.[/yellow]")
