"""Tests for the TUI dashboard module."""

from __future__ import annotations

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
