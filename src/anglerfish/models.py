"""Shared data models: templates, alerts, and verification results."""

from __future__ import annotations

import enum
from dataclasses import dataclass, field


@dataclass(frozen=True)
class OutlookTemplate:
    name: str
    description: str
    folder_name: str
    subject: str
    body_html: str
    sender_name: str
    sender_email: str
    variables: list[dict[str, str]] = field(default_factory=list)


@dataclass(frozen=True)
class CanaryAlert:
    """A confirmed canary access or tamper event."""

    canary_type: str
    template_name: str
    artifact_label: str
    accessed_by: str
    source_ip: str
    timestamp: str
    operation: str
    client_info: str
    record_path: str
    #: "access" (canary was read) or "tamper" (canary was deleted, moved,
    #: or modified — anti-forensic cleanup is itself attacker behavior).
    category: str = "access"


class VerifyStatus(enum.Enum):
    OK = "OK"
    GONE = "GONE"
    ERROR = "ERROR"


@dataclass(frozen=True)
class VerifyResult:
    """Result of checking a single deployment record."""

    canary_type: str
    template_name: str
    target: str
    status: VerifyStatus
    detail: str = ""
