"""Tests for batch deployment manifest parsing and orchestration."""

from __future__ import annotations

import dataclasses

import pytest
import yaml

from anglerfish.batch import parse_manifest
from anglerfish.exceptions import DeploymentError
from anglerfish.models import CanarySpec


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
    manifest.write_text(yaml.dump({
        "canaries": [
            {"canary_type": "outlook", "template": "Fake Password Reset", "target": "cfo@contoso.com"},
        ]
    }))
    specs = parse_manifest(manifest)
    assert len(specs) == 1
    assert specs[0].canary_type == "outlook"
    assert specs[0].template == "Fake Password Reset"
    assert specs[0].target == "cfo@contoso.com"


def test_parse_manifest_merges_default_vars(tmp_path):
    manifest = tmp_path / "manifest.yaml"
    manifest.write_text(yaml.dump({
        "defaults": {"vars": {"company": "Contoso"}},
        "canaries": [
            {"canary_type": "outlook", "template": "T", "target": "u@e.com", "vars": {"name": "Alice"}},
        ]
    }))
    specs = parse_manifest(manifest)
    assert specs[0].vars == {"company": "Contoso", "name": "Alice"}


def test_parse_manifest_entry_vars_override_defaults(tmp_path):
    manifest = tmp_path / "manifest.yaml"
    manifest.write_text(yaml.dump({
        "defaults": {"vars": {"company": "Contoso"}},
        "canaries": [
            {"canary_type": "outlook", "template": "T", "target": "u@e.com", "vars": {"company": "Fabrikam"}},
        ]
    }))
    specs = parse_manifest(manifest)
    assert specs[0].vars["company"] == "Fabrikam"


def test_parse_manifest_all_fields(tmp_path):
    manifest = tmp_path / "manifest.yaml"
    manifest.write_text(yaml.dump({
        "canaries": [{
            "canary_type": "sharepoint",
            "template": "Employee Salary Bands",
            "target": "HRSite",
            "folder_path": "Compensation/Restricted",
            "filename": "salaries.txt",
            "vars": {"quarter": "Q1"},
        }]
    }))
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
    manifest.write_text(yaml.dump({
        "canaries": [{"canary_type": "outlook", "template": "T"}]
    }))
    with pytest.raises(DeploymentError, match="target"):
        parse_manifest(manifest)


def test_parse_manifest_invalid_canary_type(tmp_path):
    manifest = tmp_path / "manifest.yaml"
    manifest.write_text(yaml.dump({
        "canaries": [{"canary_type": "teams", "template": "T", "target": "u@e.com"}]
    }))
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
