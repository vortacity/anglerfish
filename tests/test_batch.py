"""Tests for batch deployment manifest parsing and orchestration."""

from __future__ import annotations

import dataclasses
from unittest.mock import MagicMock

import pytest
import yaml

from anglerfish.batch import parse_manifest, run_batch
from anglerfish.exceptions import DeploymentError
from anglerfish.models import CanarySpec, OneDriveTemplate, OutlookTemplate


def test_canary_spec_defaults():
    spec = CanarySpec(canary_type="outlook", template="Fake Password Reset", target="user@contoso.com")
    assert spec.canary_type == "outlook"
    assert spec.template == "Fake Password Reset"
    assert spec.target == "user@contoso.com"
    assert spec.delivery_mode is None
    assert spec.folder_path is None
    assert spec.filename is None
    assert spec.vars == {}


def test_canary_spec_is_frozen():
    spec = CanarySpec(canary_type="outlook", template="T", target="u@e.com")
    try:
        spec.canary_type = "sharepoint"
        assert False, "Should have raised FrozenInstanceError"
    except dataclasses.FrozenInstanceError:
        pass


# ---------------------------------------------------------------------------
# Tests for parse_manifest
# ---------------------------------------------------------------------------


def test_parse_manifest_minimal(tmp_path):
    manifest = tmp_path / "manifest.yaml"
    manifest.write_text(
        yaml.dump(
            {
                "canaries": [
                    {"canary_type": "outlook", "template": "Fake Password Reset", "target": "cfo@contoso.com"},
                ]
            }
        )
    )
    specs = parse_manifest(manifest)
    assert len(specs) == 1
    assert specs[0].canary_type == "outlook"
    assert specs[0].template == "Fake Password Reset"
    assert specs[0].target == "cfo@contoso.com"


def test_parse_manifest_merges_default_vars(tmp_path):
    manifest = tmp_path / "manifest.yaml"
    manifest.write_text(
        yaml.dump(
            {
                "defaults": {"vars": {"company": "Contoso"}},
                "canaries": [
                    {"canary_type": "outlook", "template": "T", "target": "u@e.com", "vars": {"name": "Alice"}},
                ],
            }
        )
    )
    specs = parse_manifest(manifest)
    assert specs[0].vars == {"company": "Contoso", "name": "Alice"}


def test_parse_manifest_entry_vars_override_defaults(tmp_path):
    manifest = tmp_path / "manifest.yaml"
    manifest.write_text(
        yaml.dump(
            {
                "defaults": {"vars": {"company": "Contoso"}},
                "canaries": [
                    {"canary_type": "outlook", "template": "T", "target": "u@e.com", "vars": {"company": "Fabrikam"}},
                ],
            }
        )
    )
    specs = parse_manifest(manifest)
    assert specs[0].vars["company"] == "Fabrikam"


def test_parse_manifest_all_fields(tmp_path):
    manifest = tmp_path / "manifest.yaml"
    manifest.write_text(
        yaml.dump(
            {
                "canaries": [
                    {
                        "canary_type": "sharepoint",
                        "template": "Employee Salary Bands",
                        "target": "HRSite",
                        "folder_path": "Compensation/Restricted",
                        "filename": "salaries.txt",
                        "vars": {"quarter": "Q1"},
                    }
                ]
            }
        )
    )
    specs = parse_manifest(manifest)
    assert specs[0].folder_path == "Compensation/Restricted"
    assert specs[0].filename == "salaries.txt"
    assert specs[0].vars == {"quarter": "Q1"}


def test_parse_manifest_missing_canaries_key(tmp_path):
    manifest = tmp_path / "manifest.yaml"
    manifest.write_text(yaml.dump({"defaults": {}}))
    with pytest.raises(DeploymentError, match="'canaries'"):
        parse_manifest(manifest)


def test_parse_manifest_empty_canaries_list(tmp_path):
    manifest = tmp_path / "manifest.yaml"
    manifest.write_text(yaml.dump({"canaries": []}))
    with pytest.raises(DeploymentError, match="at least one"):
        parse_manifest(manifest)


def test_parse_manifest_missing_required_field(tmp_path):
    manifest = tmp_path / "manifest.yaml"
    manifest.write_text(yaml.dump({"canaries": [{"canary_type": "outlook", "template": "T"}]}))
    with pytest.raises(DeploymentError, match="target"):
        parse_manifest(manifest)


def test_parse_manifest_invalid_canary_type(tmp_path):
    manifest = tmp_path / "manifest.yaml"
    manifest.write_text(yaml.dump({"canaries": [{"canary_type": "teams", "template": "T", "target": "u@e.com"}]}))
    with pytest.raises(DeploymentError, match="teams"):
        parse_manifest(manifest)


def test_parse_manifest_file_not_found():
    with pytest.raises(DeploymentError, match="not found"):
        parse_manifest("/nonexistent/manifest.yaml")


def test_parse_manifest_invalid_yaml(tmp_path):
    manifest = tmp_path / "manifest.yaml"
    manifest.write_text("canaries:\n  - [broken")
    with pytest.raises(DeploymentError, match="parse"):
        parse_manifest(manifest)


# ---------------------------------------------------------------------------
# Tests for run_batch
# ---------------------------------------------------------------------------


def _outlook_template():
    return OutlookTemplate(
        name="Fake Password Reset",
        description="desc",
        folder_name="IT Notifications",
        subject="Reset",
        body_html="<p>Reset</p>",
        sender_name="IT",
        sender_email="it@contoso.com",
        variables=[],
    )


def _onedrive_template():
    return OneDriveTemplate(
        name="VPN Credentials Backup",
        description="desc",
        folder_path="IT/Backups",
        filenames=["vpn_config.txt"],
        content_text="VPN config",
        variables=[],
    )


class FakeDeployer:
    def __init__(self, graph, template):
        self.graph = graph
        self.template = template

    def deploy(self, target_user, **kwargs):
        return {
            "type": "fake",
            "target_user": target_user,
            "status": "active",
        }


class FailingDeployer:
    def __init__(self, graph, template):
        pass

    def deploy(self, target_user, **kwargs):
        raise DeploymentError("Graph API 403: Forbidden")


def test_run_batch_deploys_all_canaries(tmp_path, monkeypatch):
    specs = [
        CanarySpec(
            canary_type="outlook", template="Fake Password Reset", target="cfo@contoso.com", delivery_mode="draft"
        ),
        CanarySpec(
            canary_type="onedrive",
            template="VPN Credentials Backup",
            target="j.smith@contoso.com",
            folder_path="IT/Backups",
            filename="vpn.txt",
        ),
    ]
    output_dir = tmp_path / "records"

    import anglerfish.batch as batch_mod

    monkeypatch.setattr(batch_mod, "_find_template_by_name", lambda ct, name: f"pkg://{ct}/fake.yaml")
    monkeypatch.setattr(
        batch_mod, "load_template", lambda path: _outlook_template() if "outlook" in path else _onedrive_template()
    )
    monkeypatch.setattr(batch_mod, "render_template", lambda template, values: template)
    monkeypatch.setattr(batch_mod, "OutlookDeployer", FakeDeployer)
    monkeypatch.setattr(batch_mod, "OneDriveDeployer", FakeDeployer)
    monkeypatch.setattr(batch_mod, "SharePointDeployer", FakeDeployer)

    graph = MagicMock()
    results = run_batch(specs, graph=graph, output_dir=output_dir)

    assert len(results) == 2
    assert all(r["success"] for r in results)
    records = list(output_dir.glob("*.json"))
    assert len(records) == 2


def test_run_batch_continues_on_failure(tmp_path, monkeypatch):
    specs = [
        CanarySpec(canary_type="outlook", template="T", target="fail@e.com", delivery_mode="draft"),
        CanarySpec(canary_type="onedrive", template="T", target="ok@e.com", folder_path="F", filename="f.txt"),
    ]
    output_dir = tmp_path / "records"

    import anglerfish.batch as batch_mod

    monkeypatch.setattr(batch_mod, "_find_template_by_name", lambda ct, name: f"pkg://{ct}/fake.yaml")
    monkeypatch.setattr(
        batch_mod, "load_template", lambda path: _outlook_template() if "outlook" in path else _onedrive_template()
    )
    monkeypatch.setattr(batch_mod, "render_template", lambda template, values: template)
    monkeypatch.setattr(batch_mod, "OutlookDeployer", FailingDeployer)
    monkeypatch.setattr(batch_mod, "OneDriveDeployer", FakeDeployer)
    monkeypatch.setattr(batch_mod, "SharePointDeployer", FakeDeployer)

    graph = MagicMock()
    results = run_batch(specs, graph=graph, output_dir=output_dir)

    assert len(results) == 2
    assert results[0]["success"] is False
    assert "403" in results[0]["error"]
    assert results[1]["success"] is True
    records = list(output_dir.glob("*.json"))
    assert len(records) == 1


def test_run_batch_dry_run_writes_no_records(tmp_path, monkeypatch):
    specs = [
        CanarySpec(canary_type="outlook", template="T", target="u@e.com", delivery_mode="draft"),
    ]
    output_dir = tmp_path / "records"

    import anglerfish.batch as batch_mod

    monkeypatch.setattr(batch_mod, "_find_template_by_name", lambda ct, name: "pkg://outlook/fake.yaml")
    monkeypatch.setattr(batch_mod, "load_template", lambda path: _outlook_template())
    monkeypatch.setattr(batch_mod, "render_template", lambda template, values: template)

    graph = MagicMock()
    results = run_batch(specs, graph=graph, output_dir=output_dir, dry_run=True)

    assert len(results) == 1
    assert results[0]["success"] is True
    assert results[0].get("dry_run") is True
    records = list(output_dir.glob("*.json")) if output_dir.exists() else []
    assert len(records) == 0
