"""Tests for the canary-type registry and lifecycle plugin dispatch."""

from __future__ import annotations

import json
from datetime import datetime

import pytest

from anglerfish.deployers import registry
from anglerfish.deployers.base import BaseDeployer, CanaryMatcher, CanaryType
from anglerfish.exceptions import DeploymentError
from anglerfish.inventory import DeploymentRecord
from anglerfish.models import CanaryAlert, VerifyResult, VerifyStatus
from anglerfish.monitor import CanaryIndex, load_records
from anglerfish.verify import verify_record


def test_outlook_is_registered():
    assert "outlook" in registry.supported_canary_types()
    assert registry.get_canary_type("outlook").name == "outlook"


def test_lookup_is_case_and_whitespace_tolerant():
    assert registry.find_canary_type(" Outlook ") is not None
    assert registry.find_canary_type("") is None
    assert registry.find_canary_type("sharepoint") is None


def test_get_canary_type_unknown_raises_with_supported_list():
    with pytest.raises(DeploymentError, match="Unsupported canary type 'sharepoint'.*outlook"):
        registry.get_canary_type("sharepoint")


def test_all_audit_content_types_includes_exchange():
    assert "Audit.Exchange" in registry.all_audit_content_types()


# ------------------------------------------------------------------
# End-to-end plugin contract: registering one class is sufficient for
# the monitor, verify, and audit-subscription paths to pick a type up.
# ------------------------------------------------------------------


class _FakeMatcher(CanaryMatcher):
    def __init__(self, records):
        self._records = list(records)

    @property
    def count(self) -> int:
        return len(self._records)

    def match(self, event: dict, *, now: datetime | None = None) -> CanaryAlert | None:
        if event.get("Operation") != "FileAccessed":
            return None
        path, rec = self._records[0]
        return CanaryAlert(
            canary_type=rec.canary_type,
            template_name=rec.template_name,
            artifact_label="fake",
            accessed_by="x",
            source_ip="x",
            timestamp="",
            operation="FileAccessed",
            client_info="",
            record_path=path,
        )


class _FakeType(CanaryType):
    name = "faketype"
    audit_content_types = ("Audit.SharePoint",)

    def create_deployer(self, graph, template) -> BaseDeployer:
        raise NotImplementedError

    def remove(self, graph, record):
        return {"removed": "true"}

    def trigger_access(self, graph, record):
        return {"triggered": "true"}

    def verify(self, graph, record) -> VerifyResult:
        return VerifyResult(
            canary_type=self.name,
            template_name=record.template_name,
            target=record.target_user,
            status=VerifyStatus.OK,
        )

    def build_matcher(self, records) -> CanaryMatcher:
        return _FakeMatcher(records)


@pytest.fixture
def fake_type():
    registry.register(_FakeType())
    yield
    registry._REGISTRY.pop("faketype", None)


def test_registered_type_flows_through_monitor_and_verify(fake_type, tmp_path):
    record = {
        "timestamp": "2026-06-01T00:00:00+00:00",
        "canary_type": "faketype",
        "template_name": "Fake File",
        "status": "active",
    }
    (tmp_path / "rec.json").write_text(json.dumps(record), encoding="utf-8")

    # load_records keeps the record because its type is registered.
    records = load_records(tmp_path)
    assert len(records) == 1

    # CanaryIndex builds the plugin's matcher and routes events to it.
    index = CanaryIndex(records)
    assert index.count == 1
    alert = index.match({"Operation": "FileAccessed"})
    assert alert is not None
    assert alert.canary_type == "faketype"
    assert index.match({"Operation": "MailItemsAccessed"}) is None

    # verify_record dispatches to the plugin.
    result = verify_record(graph=object(), record=DeploymentRecord.from_dict(record))
    assert result.status == VerifyStatus.OK

    # The audit subscription list includes the plugin's content types.
    assert "Audit.SharePoint" in registry.all_audit_content_types()


def test_unregistered_type_records_are_skipped_by_load_records(tmp_path):
    record = {
        "timestamp": "2026-06-01T00:00:00+00:00",
        "canary_type": "faketype",
        "status": "active",
    }
    (tmp_path / "rec.json").write_text(json.dumps(record), encoding="utf-8")
    assert load_records(tmp_path) == []


def test_unregistered_type_verify_returns_error():
    record = DeploymentRecord.from_dict({"canary_type": "sharepoint", "template_name": "t"})
    result = verify_record(graph=object(), record=record)
    assert result.status == VerifyStatus.ERROR
    assert "Unsupported canary type" in result.detail
