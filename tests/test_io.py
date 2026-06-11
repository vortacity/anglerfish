"""Tests for the shared atomic-write and timestamp helpers."""

import json
import os
import stat
import sys

import pytest

from anglerfish._io import as_utc, parse_utc_datetime, write_json_atomic
from anglerfish.exceptions import MonitorError

from datetime import datetime, timezone


# ------------------------------------------------------------------
# parse_utc_datetime
# ------------------------------------------------------------------


def test_parse_utc_datetime_empty_returns_none():
    assert parse_utc_datetime("") is None
    assert parse_utc_datetime("   ") is None
    assert parse_utc_datetime(None) is None


def test_parse_utc_datetime_invalid_returns_none():
    assert parse_utc_datetime("not-a-date") is None
    assert parse_utc_datetime(object()) is None


def test_parse_utc_datetime_z_suffix_handled():
    result = parse_utc_datetime("2026-02-19T12:00:00Z")
    assert result == datetime(2026, 2, 19, 12, 0, 0, tzinfo=timezone.utc)


def test_parse_utc_datetime_naive_gets_utc():
    result = parse_utc_datetime("2026-02-19T12:00:00")
    assert result == datetime(2026, 2, 19, 12, 0, 0, tzinfo=timezone.utc)


def test_parse_utc_datetime_offset_normalized_to_utc():
    result = parse_utc_datetime("2026-02-19T14:00:00+02:00")
    assert result == datetime(2026, 2, 19, 12, 0, 0, tzinfo=timezone.utc)


def test_as_utc_naive_and_aware():
    naive = datetime(2026, 2, 19, 12, 0, 0)
    assert as_utc(naive).tzinfo == timezone.utc
    aware = datetime(2026, 2, 19, 12, 0, 0, tzinfo=timezone.utc)
    assert as_utc(aware) == aware


# ------------------------------------------------------------------
# write_json_atomic
# ------------------------------------------------------------------


def test_write_json_atomic_roundtrip(tmp_path):
    path = tmp_path / "out.json"
    write_json_atomic(path, {"a": 1}, error_cls=MonitorError)
    assert json.loads(path.read_text(encoding="utf-8")) == {"a": 1}


def test_write_json_atomic_overwrites_existing(tmp_path):
    path = tmp_path / "out.json"
    path.write_text("{}", encoding="utf-8")
    write_json_atomic(path, {"b": 2}, error_cls=MonitorError)
    assert json.loads(path.read_text(encoding="utf-8")) == {"b": 2}


@pytest.mark.skipif(not hasattr(os, "fchmod"), reason="requires POSIX fchmod")
def test_write_json_atomic_restricts_permissions(tmp_path):
    path = tmp_path / "out.json"
    write_json_atomic(path, {"a": 1}, error_cls=MonitorError)
    assert stat.S_IMODE(path.stat().st_mode) == 0o600


def test_write_json_atomic_raises_error_cls_with_label(tmp_path):
    missing_parent = tmp_path / "nope" / "out.json"
    with pytest.raises(MonitorError, match="monitor state"):
        write_json_atomic(missing_parent, {"a": 1}, error_cls=MonitorError, label="monitor state")


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX permission semantics")
def test_write_json_atomic_leaves_no_temp_file_on_failure(tmp_path):
    target_dir = tmp_path / "dir"
    target_dir.mkdir()
    path = target_dir / "out.json"
    os.chmod(target_dir, 0o500)  # writable temp file creation fails
    try:
        with pytest.raises(MonitorError):
            write_json_atomic(path, {"a": 1}, error_cls=MonitorError)
        assert list(target_dir.iterdir()) == []
    finally:
        os.chmod(target_dir, 0o700)
