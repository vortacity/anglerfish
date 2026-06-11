"""Tests for --format json output on list and verify."""

from __future__ import annotations

import json

from anglerfish.cli import main
from anglerfish.inventory import write_deployment_record


def test_list_json_outputs_records(tmp_path, capsys):
    write_deployment_record(
        tmp_path / "rec1.json",
        {"canary_type": "outlook", "template_name": "Fake Password Reset", "target_user": "a@contoso.com"},
    )
    write_deployment_record(
        tmp_path / "rec2.json",
        {"canary_type": "sharepoint", "template_name": "Legacy"},  # filtered out, like the table
    )

    rc = main(["list", "--records-dir", str(tmp_path), "--format", "json"])
    out = capsys.readouterr().out

    assert rc == 0
    entries = json.loads(out)
    assert len(entries) == 1
    assert entries[0]["canary_type"] == "outlook"
    assert entries[0]["template_name"] == "Fake Password Reset"
    assert entries[0]["record_path"].endswith("rec1.json")
    assert entries[0]["schema_version"] == 2


def test_list_json_missing_dir_outputs_empty_array(tmp_path, capsys):
    rc = main(["list", "--records-dir", str(tmp_path / "missing"), "--format", "json"])
    out = capsys.readouterr().out

    assert rc == 0
    assert json.loads(out) == []


def test_list_json_empty_dir_outputs_empty_array(tmp_path, capsys):
    rc = main(["list", "--records-dir", str(tmp_path), "--format", "json"])
    assert rc == 0
    assert json.loads(capsys.readouterr().out) == []


def test_list_json_skips_malformed_records(tmp_path, capsys):
    (tmp_path / "broken.json").write_text("not json", encoding="utf-8")
    write_deployment_record(tmp_path / "good.json", {"canary_type": "outlook"})

    rc = main(["list", "--records-dir", str(tmp_path), "--format", "json"])

    assert rc == 0
    assert len(json.loads(capsys.readouterr().out)) == 1


def test_verify_demo_json_is_pure_json_on_stdout(capsys):
    rc = main(["verify", "--demo", "--format", "json"])
    out = capsys.readouterr().out

    # Demo data includes a GONE canary, so exit code is 1 — same as table mode.
    assert rc == 1
    results = json.loads(out)  # no banner, no table — stdout is just the array
    statuses = {r["status"] for r in results}
    assert statuses == {"OK", "GONE", "ERROR"}
    assert all(set(r) == {"canary_type", "template_name", "target", "status", "detail"} for r in results)


def test_verify_table_mode_unchanged(capsys):
    rc = main(["verify", "--demo"])
    out = capsys.readouterr().out
    assert rc == 1
    assert "Canary Verification" in out
