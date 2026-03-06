"""Tests for batch deployment manifest parsing and orchestration."""

from __future__ import annotations

import dataclasses

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
