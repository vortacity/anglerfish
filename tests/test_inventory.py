import json
import stat
from pathlib import Path

import pytest

from anglerfish.exceptions import DeploymentError
from anglerfish.inventory import (
    DeploymentRecord,
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


def test_update_deployment_status_preserves_status_updated_at_for_same_status(tmp_path):
    record_file = tmp_path / "record.json"
    write_deployment_record(
        record_file,
        {
            "canary_type": "outlook",
            "status": "cleaned_up",
            "status_updated_at": "2026-05-06T10:00:00+00:00",
        },
    )

    update_deployment_status(record_file, "cleaned_up")

    data = json.loads(record_file.read_text())
    assert data["status"] == "cleaned_up"
    assert data["status_updated_at"] == "2026-05-06T10:00:00+00:00"


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
    from anglerfish import _io

    record_file = tmp_path / "record.json"
    replace_calls: list[tuple[Path, Path]] = []
    original_replace = _io.os.replace

    def tracked_replace(src, dst):
        replace_calls.append((Path(src), Path(dst)))
        return original_replace(src, dst)

    monkeypatch.setattr(_io.os, "replace", tracked_replace)
    write_deployment_record(record_file, {"canary_type": "outlook", "status": "active"})

    assert len(replace_calls) == 1
    temp_path, destination = replace_calls[0]
    assert temp_path.parent == record_file.parent
    assert destination == record_file
    assert not temp_path.exists()


def test_write_deployment_record_fsyncs_before_replace(monkeypatch, tmp_path):
    from anglerfish import _io

    record_file = tmp_path / "record.json"
    fsync_calls: list[int] = []
    monkeypatch.setattr(_io.os, "fsync", lambda fd: fsync_calls.append(fd))

    write_deployment_record(record_file, {"canary_type": "outlook", "status": "active"})

    assert len(fsync_calls) == 1


def test_write_deployment_record_uses_0600_permissions(tmp_path):
    record_file = tmp_path / "record.json"
    write_deployment_record(record_file, {"canary_type": "outlook", "status": "active"})
    assert stat.S_IMODE(record_file.stat().st_mode) == 0o600


def test_write_deployment_record_without_fchmod(tmp_path, monkeypatch):
    """On platforms without os.fchmod (e.g. Windows) writing must still succeed."""
    from anglerfish import _io

    monkeypatch.delattr(_io.os, "fchmod", raising=False)
    record_file = tmp_path / "record.json"
    write_deployment_record(record_file, {"canary_type": "outlook", "status": "active"})

    assert record_file.is_file()
    assert read_deployment_record(record_file).canary_type == "outlook"


# ------------------------------------------------------------------
# DeploymentRecord normalization (schema v2)
# ------------------------------------------------------------------


def test_record_canary_type_wins_over_legacy_type_alias():
    # Historically cleanup used type-wins while monitor/verify used
    # canary_type-wins; the normalizer resolves this in exactly one place.
    record = DeploymentRecord.from_dict({"canary_type": "outlook", "type": "sharepoint"})
    assert record.canary_type == "outlook"


def test_record_legacy_type_alias_accepted():
    record = DeploymentRecord.from_dict({"type": "Outlook"})
    assert record.canary_type == "outlook"


def test_record_verified_accepts_v1_strings_and_booleans():
    assert DeploymentRecord.from_dict({"canary_type": "outlook", "verified": "false"}).verified is False
    assert DeploymentRecord.from_dict({"canary_type": "outlook", "verified": "true"}).verified is True
    assert DeploymentRecord.from_dict({"canary_type": "outlook", "verified": False}).verified is False
    assert DeploymentRecord.from_dict({"canary_type": "outlook"}).verified is True


def test_record_tolerates_json_nulls():
    record = DeploymentRecord.from_dict(
        {"canary_type": "outlook", "delivery_mode": None, "target_user": None, "folder_id": None}
    )
    assert record.delivery_mode == "draft"
    assert record.target_user == ""
    assert record.folder_id == ""


def test_record_preserves_unknown_keys_round_trip(tmp_path):
    raw = {
        "timestamp": "2026-06-01T00:00:00+00:00",
        "type": "outlook",
        "verified": "false",
        "operator_note": "hand-added field",
    }
    path = tmp_path / "rec.json"
    path.write_text(json.dumps(raw), encoding="utf-8")

    update_deployment_status(path, "cleaned_up")

    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["schema_version"] == 2
    assert data["canary_type"] == "outlook"  # canonical key only
    assert "type" not in data
    assert data["verified"] is False  # real boolean after rewrite
    assert data["operator_note"] == "hand-added field"
    assert data["status"] == "cleaned_up"


def test_write_deployment_record_emits_schema_v2(tmp_path):
    path = tmp_path / "rec.json"
    write_deployment_record(path, {"canary_type": "outlook", "status": "active", "verified": "true"})
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["schema_version"] == 2
    assert data["verified"] is True
    assert data["timestamp"]
