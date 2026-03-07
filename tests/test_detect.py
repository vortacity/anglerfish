"""Tests for the SIEM query generator (detect module)."""

from __future__ import annotations

import json

import pytest

from anglerfish.detect import generate_query


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------


def _write_record(tmp_path, rec: dict) -> str:
    path = tmp_path / "record.json"
    path.write_text(json.dumps(rec))
    return str(path)


def _outlook_record() -> dict:
    return {
        "timestamp": "2026-03-01T00:00:00Z",
        "canary_type": "outlook",
        "target_user": "alice@contoso.com",
        "internet_message_id": "<canary-msg@contoso.com>",
        "folder_name": "IT Notifications",
    }


def _sharepoint_record() -> dict:
    return {
        "timestamp": "2026-03-01T00:00:00Z",
        "canary_type": "sharepoint",
        "uploaded_files": ["Salary_Bands.txt"],
        "site_name": "HR",
    }


def _onedrive_record() -> dict:
    return {
        "timestamp": "2026-03-01T00:00:00Z",
        "canary_type": "onedrive",
        "uploaded_files": ["VPN_Config.txt"],
        "target_user": "j.smith@contoso.com",
    }


# ------------------------------------------------------------------
# KQL
# ------------------------------------------------------------------


def test_kql_outlook(tmp_path):
    path = _write_record(tmp_path, _outlook_record())

    query = generate_query(path, fmt="kql")

    assert "MailItemsAccessed" in query
    assert "alice@contoso.com" in query
    assert "<canary-msg@contoso.com>" in query


def test_kql_sharepoint(tmp_path):
    path = _write_record(tmp_path, _sharepoint_record())

    query = generate_query(path, fmt="kql")

    assert "FileAccessed" in query
    assert "Salary_Bands.txt" in query
    assert "HR" in query


def test_kql_onedrive(tmp_path):
    path = _write_record(tmp_path, _onedrive_record())

    query = generate_query(path, fmt="kql")

    assert "FileAccessed" in query
    assert "VPN_Config.txt" in query


# ------------------------------------------------------------------
# Splunk SPL
# ------------------------------------------------------------------


def test_splunk_outlook(tmp_path):
    path = _write_record(tmp_path, _outlook_record())

    query = generate_query(path, fmt="splunk")

    assert "MailItemsAccessed" in query
    assert "alice@contoso.com" in query
    assert "o365" in query


def test_splunk_sharepoint(tmp_path):
    path = _write_record(tmp_path, _sharepoint_record())

    query = generate_query(path, fmt="splunk")

    assert "FileAccessed" in query
    assert "Salary_Bands.txt" in query


# ------------------------------------------------------------------
# OData filter
# ------------------------------------------------------------------


def test_odata_outlook(tmp_path):
    path = _write_record(tmp_path, _outlook_record())

    query = generate_query(path, fmt="odata")

    assert "MailItemsAccessed" in query
    assert "alice@contoso.com" in query


def test_odata_file(tmp_path):
    path = _write_record(tmp_path, _sharepoint_record())

    query = generate_query(path, fmt="odata")

    assert "FileAccessed" in query
    assert "Salary_Bands.txt" in query


# ------------------------------------------------------------------
# Unsupported format
# ------------------------------------------------------------------


def test_unsupported_format_raises(tmp_path):
    path = _write_record(tmp_path, _outlook_record())

    with pytest.raises(ValueError, match="Unsupported format"):
        generate_query(path, fmt="unknown")


# ------------------------------------------------------------------
# Legacy type field
# ------------------------------------------------------------------


def test_legacy_type_field(tmp_path):
    rec = {
        "timestamp": "2026-03-01T00:00:00Z",
        "type": "outlook",
        "target_user": "bob@contoso.com",
    }
    path = _write_record(tmp_path, rec)

    query = generate_query(path, fmt="kql")

    assert "MailItemsAccessed" in query
