"""Tests for the TUI dashboard module."""

from __future__ import annotations

import pytest
from textual.widgets import DataTable, RichLog, Static

from anglerfish.dashboard import DemoDataProvider
from anglerfish.monitor import CanaryAlert
from anglerfish.verify import VerifyResult, VerifyStatus


class TestDemoDataProvider:
    def test_records_returns_five_entries(self):
        provider = DemoDataProvider()
        records = provider.records()
        assert len(records) == 5

    def test_records_have_required_keys(self):
        provider = DemoDataProvider()
        for path, rec in provider.records():
            assert isinstance(path, str)
            assert "canary_type" in rec
            assert "template_name" in rec

    def test_records_cover_all_canary_types(self):
        provider = DemoDataProvider()
        types = {rec["canary_type"] for _, rec in provider.records()}
        assert types == {"outlook", "sharepoint", "onedrive"}

    def test_verify_results_returns_list(self):
        provider = DemoDataProvider()
        results = provider.verify_results()
        assert len(results) == 5
        assert all(isinstance(r, VerifyResult) for r in results)

    def test_verify_results_include_mixed_statuses(self):
        provider = DemoDataProvider()
        results = provider.verify_results()
        statuses = {r.status for r in results}
        assert VerifyStatus.OK in statuses
        assert VerifyStatus.GONE in statuses

    def test_generate_alert_returns_canary_alert(self):
        provider = DemoDataProvider()
        alert = provider.generate_alert()
        assert isinstance(alert, CanaryAlert)
        assert alert.canary_type in ("outlook", "sharepoint", "onedrive")
        assert alert.accessed_by
        assert alert.source_ip

    def test_cycle_verify_status_changes_a_status(self):
        import random

        random.seed(42)
        provider = DemoDataProvider()
        before = list(provider._verify_statuses)
        provider.cycle_verify_status()
        after = provider._verify_statuses
        assert before != after
        assert all(isinstance(s, VerifyStatus) for s in after)


class TestAnglerDashboardApp:
    @pytest.mark.asyncio
    async def test_app_mounts_all_panels_in_demo_mode(self):
        from anglerfish.dashboard import AnglerDashboard

        app = AnglerDashboard(demo=True)
        async with app.run_test() as _pilot:
            assert app.query_one(DataTable) is not None
            assert app.query_one(RichLog) is not None
            assert app.query_one("#stats-bar", Static) is not None

    @pytest.mark.asyncio
    async def test_canary_table_populated_in_demo_mode(self):
        from anglerfish.dashboard import AnglerDashboard

        app = AnglerDashboard(demo=True)
        async with app.run_test() as _pilot:
            table = app.query_one(DataTable)
            assert table.row_count == 5

    @pytest.mark.asyncio
    async def test_q_key_exits_app(self):
        from anglerfish.dashboard import AnglerDashboard

        app = AnglerDashboard(demo=True)
        async with app.run_test() as pilot:
            await pilot.press("q")


class TestLiveModeInit:
    def test_live_mode_sets_records_dir(self, tmp_path):
        """Live mode stores the records dir."""
        import json

        from anglerfish.dashboard import AnglerDashboard

        rec = {
            "canary_type": "outlook",
            "template_name": "Test",
            "target_user": "user@test.com",
            "folder_id": "f1",
            "internet_message_id": "<test@test.com>",
            "timestamp": "2026-03-07T00:00:00Z",
            "status": "active",
        }
        rec_file = tmp_path / "test.json"
        rec_file.write_text(json.dumps(rec))

        app = AnglerDashboard(
            demo=False,
            records_dir=str(tmp_path),
            poll_interval=9999,
            verify_interval=9999,
        )
        assert app._records_dir == str(tmp_path)
