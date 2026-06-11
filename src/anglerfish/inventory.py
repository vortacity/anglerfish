"""Deployment record persistence and the canonical record schema."""

from __future__ import annotations

import datetime
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping

from ._io import write_json_atomic
from .exceptions import DeploymentError

#: Current on-disk record schema. Version 2 canonicalizes the ``canary_type``
#: key (v1 records may carry the legacy ``type`` alias) and stores ``verified``
#: as a JSON boolean (v1 stored the strings "true"/"false").
SCHEMA_VERSION = 2

# Keys consumed by DeploymentRecord.from_dict; anything else is preserved
# verbatim in ``extra`` so rewriting a record never destroys data.
_KNOWN_KEYS = frozenset(
    {
        "schema_version",
        "canary_type",
        "type",
        "timestamp",
        "status",
        "status_updated_at",
        "template_name",
        "target_user",
        "delivery_mode",
        "folder_id",
        "folder_name",
        "message_id",
        "internet_message_id",
        "inbox_message_id",
        "subject",
        "canary_id",
        "auth_mode",
        "verified",
        "verify_note",
    }
)


@dataclass
class DeploymentRecord:
    """Typed view of a deployment record.

    ``from_dict`` is the single place where legacy shapes are normalized:
    the ``type``/``canary_type`` key aliasing (``canary_type`` wins when both
    are present), string booleans for ``verified``, and JSON nulls. Consumers
    must not reach back into raw dicts.
    """

    canary_type: str
    timestamp: str = ""
    status: str = "active"
    status_updated_at: str = ""
    template_name: str = ""
    target_user: str = ""
    delivery_mode: str = "draft"
    folder_id: str = ""
    folder_name: str = ""
    message_id: str = ""
    internet_message_id: str = ""
    inbox_message_id: str = ""
    subject: str = ""
    canary_id: str = ""
    auth_mode: str = ""
    verified: bool = True
    verify_note: str = ""
    schema_version: int = SCHEMA_VERSION
    #: Unrecognized keys, preserved round-trip.
    extra: dict[str, Any] = field(default_factory=dict)
    #: Runtime-only: when the monitor should stop matching this record
    #: (set for recently cleaned-up records). Never serialized.
    monitor_expires_at: datetime.datetime | None = None

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> DeploymentRecord:
        def _text(key: str, default: str = "") -> str:
            value = raw.get(key)
            return default if value is None else str(value)

        canary_type = (_text("canary_type") or _text("type")).strip().lower()
        delivery_mode = _text("delivery_mode").strip().lower() or "draft"
        status = _text("status").strip() or "active"

        verified_raw = raw.get("verified", True)
        if isinstance(verified_raw, str):
            verified = verified_raw.strip().lower() != "false"
        else:
            verified = bool(verified_raw) if verified_raw is not None else True

        try:
            schema_version = int(raw.get("schema_version") or 1)
        except (TypeError, ValueError):
            schema_version = 1

        return cls(
            canary_type=canary_type,
            timestamp=_text("timestamp"),
            status=status,
            status_updated_at=_text("status_updated_at"),
            template_name=_text("template_name"),
            target_user=_text("target_user").strip(),
            delivery_mode=delivery_mode,
            folder_id=_text("folder_id").strip(),
            folder_name=_text("folder_name"),
            message_id=_text("message_id").strip(),
            internet_message_id=_text("internet_message_id").strip(),
            inbox_message_id=_text("inbox_message_id").strip(),
            subject=_text("subject"),
            canary_id=_text("canary_id"),
            auth_mode=_text("auth_mode"),
            verified=verified,
            verify_note=_text("verify_note"),
            schema_version=schema_version,
            extra={key: value for key, value in raw.items() if key not in _KNOWN_KEYS},
        )

    def to_dict(self) -> dict[str, Any]:
        """Serialize with canonical keys only, at the current schema version."""
        payload: dict[str, Any] = {
            "schema_version": SCHEMA_VERSION,
            "canary_type": self.canary_type,
            "timestamp": self.timestamp,
            "status": self.status,
            "delivery_mode": self.delivery_mode,
            "verified": self.verified,
        }
        for key in (
            "status_updated_at",
            "template_name",
            "target_user",
            "folder_id",
            "folder_name",
            "message_id",
            "internet_message_id",
            "inbox_message_id",
            "subject",
            "canary_id",
            "auth_mode",
            "verify_note",
        ):
            value = getattr(self, key)
            if value:
                payload[key] = value
        payload.update(self.extra)
        return payload


def coerce_record(record: Mapping[str, Any] | DeploymentRecord) -> DeploymentRecord:
    """Accept either a DeploymentRecord or a raw mapping at public boundaries."""
    if isinstance(record, DeploymentRecord):
        return record
    return DeploymentRecord.from_dict(record)


def read_deployment_record(path: str | Path) -> DeploymentRecord:
    """Load a deployment record. Raises DeploymentError on failure."""
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
    return DeploymentRecord.from_dict(data)


def write_deployment_record(path: str | Path, record: Mapping[str, Any] | DeploymentRecord) -> None:
    """Write a deployment record as canonical schema-v2 JSON.

    A UTC timestamp is added when the record does not carry one. Parent
    directories are created automatically if they do not exist.
    """
    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    if not isinstance(record, DeploymentRecord):
        record = DeploymentRecord.from_dict(record)
    if not record.timestamp:
        record.timestamp = datetime.datetime.now(datetime.timezone.utc).isoformat()
    write_json_atomic(output_path, record.to_dict(), error_cls=DeploymentError, label="deployment record")


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
    previous_status = record.status
    record.status = status
    if previous_status != status or not record.status_updated_at:
        record.status_updated_at = (updated_at or datetime.datetime.now(datetime.timezone.utc)).isoformat()
    write_json_atomic(Path(path), record.to_dict(), error_cls=DeploymentError, label="deployment record")
