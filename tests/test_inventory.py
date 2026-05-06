import json
import stat
from pathlib import Path

import pytest

from anglerfish.exceptions import DeploymentError
from anglerfish.inventory import (
    read_deployment_record,
    update_deployment_status,
    write_deployment_record,
)


def test_update_deployment_status_happy_path(tmp_path):
    record_file = tmp_path / "record.json"
    write_deployment_record(str(record_file), {"canary_type": "outlook", "status": "active"})

    update_deployment_status(str(record_file), "cleaned_up")

    data = json.loads(record_file.read_text())
    assert data["status"] == "cleaned_up"


def test_update_deployment_status_sets_status_updated_at(tmp_path):
    record_file = tmp_path / "record.json"
    write_deployment_record(record_file, {"canary_type": "outlook", "status": "active"})

    update_deployment_status(record_file, "cleaned_up")

    data = json.loads(record_file.read_text())
    assert data["status"] == "cleaned_up"
    assert "status_updated_at" in data


def test_update_deployment_status_preserves_timestamp(tmp_path):
    record_file = tmp_path / "record.json"
    write_deployment_record(str(record_file), {"canary_type": "outlook", "status": "active"})

    original_data = json.loads(record_file.read_text())
    original_timestamp = original_data["timestamp"]

    update_deployment_status(str(record_file), "cleaned_up")

    updated_data = json.loads(record_file.read_text())
    assert updated_data["timestamp"] == original_timestamp
    assert updated_data["canary_type"] == "outlook"


def test_update_deployment_status_missing_file(tmp_path):
    missing = tmp_path / "nonexistent.json"
    with pytest.raises(DeploymentError):
        update_deployment_status(str(missing), "cleaned_up")


def test_read_deployment_record_requires_timestamp(tmp_path):
    record_file = tmp_path / "record.json"
    record_file.write_text(json.dumps({"canary_type": "outlook"}), encoding="utf-8")

    with pytest.raises(DeploymentError, match="missing required field 'timestamp'"):
        read_deployment_record(record_file)


def test_read_deployment_record_requires_canary_type_or_type(tmp_path):
    record_file = tmp_path / "record.json"
    record_file.write_text(json.dumps({"timestamp": "2026-01-01T00:00:00+00:00"}), encoding="utf-8")

    with pytest.raises(DeploymentError, match="missing required field 'canary_type' or 'type'"):
        read_deployment_record(record_file)


def test_read_deployment_record_requires_object(tmp_path):
    record_file = tmp_path / "record.json"
    record_file.write_text(json.dumps(["not", "an", "object"]), encoding="utf-8")

    with pytest.raises(DeploymentError, match="not a valid JSON object"):
        read_deployment_record(record_file)


def test_write_deployment_record_uses_atomic_replace(monkeypatch, tmp_path):
    from anglerfish import inventory

    record_file = tmp_path / "record.json"
    replace_calls: list[tuple[Path, Path]] = []
    original_replace = inventory.os.replace

    def tracked_replace(src, dst):
        replace_calls.append((Path(src), Path(dst)))
        return original_replace(src, dst)

    monkeypatch.setattr(inventory.os, "replace", tracked_replace)
    write_deployment_record(record_file, {"canary_type": "outlook", "status": "active"})

    assert len(replace_calls) == 1
    temp_path, destination = replace_calls[0]
    assert temp_path.parent == record_file.parent
    assert destination == record_file
    assert not temp_path.exists()


def test_write_deployment_record_fsyncs_before_replace(monkeypatch, tmp_path):
    from anglerfish import inventory

    record_file = tmp_path / "record.json"
    fsync_calls: list[int] = []
    monkeypatch.setattr(inventory.os, "fsync", lambda fd: fsync_calls.append(fd))

    write_deployment_record(record_file, {"canary_type": "outlook", "status": "active"})

    assert len(fsync_calls) == 1


def test_write_deployment_record_uses_0600_permissions(tmp_path):
    record_file = tmp_path / "record.json"
    write_deployment_record(record_file, {"canary_type": "outlook", "status": "active"})
    assert stat.S_IMODE(record_file.stat().st_mode) == 0o600
