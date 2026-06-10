"""Deployment record persistence."""

from __future__ import annotations

import datetime
import json
from pathlib import Path

from ._io import write_json_atomic
from .exceptions import DeploymentError


def read_deployment_record(path: str | Path) -> dict:
    """Load and return a deployment record JSON. Raises DeploymentError on failure."""
    record_path = Path(path)
    if not record_path.is_file():
        raise DeploymentError(f"Deployment record not found: {path}")
    try:
        with record_path.open("r", encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, json.JSONDecodeError) as exc:
        raise DeploymentError(f"Failed to read deployment record '{path}': {exc}") from exc
    if not isinstance(data, dict):
        raise DeploymentError(f"Deployment record '{path}' is not a valid JSON object.")
    if "timestamp" not in data:
        raise DeploymentError(f"Deployment record '{path}' is missing required field 'timestamp'.")
    if "canary_type" not in data and "type" not in data:
        raise DeploymentError(f"Deployment record '{path}' is missing required field 'canary_type' or 'type'.")
    return data


def write_deployment_record(path: str | Path, record: dict) -> None:
    """Write deployment metadata to a JSON file.

    The record is written with a UTC timestamp prepended. Parent directories are
    created automatically if they do not exist.
    """
    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    record_with_meta = {
        "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        **record,
    }
    write_json_atomic(output_path, record_with_meta, error_cls=DeploymentError, label="deployment record")


def update_deployment_status(
    path: str | Path,
    status: str,
    *,
    updated_at: datetime.datetime | None = None,
) -> None:
    """Update the 'status' field of an existing deployment record in place.

    Reads the file, overwrites the 'status' key, and re-serialises. All other
    fields (including the original timestamp) are preserved.
    """
    record = read_deployment_record(path)
    previous_status = record.get("status")
    record["status"] = status
    if previous_status != status or not record.get("status_updated_at"):
        record["status_updated_at"] = (updated_at or datetime.datetime.now(datetime.timezone.utc)).isoformat()
    output_path = Path(path)
    write_json_atomic(output_path, record, error_cls=DeploymentError, label="deployment record")
