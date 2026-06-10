"""Canary health-check: verify deployed artifacts still exist via Graph API."""

from __future__ import annotations

import enum
import logging
from dataclasses import dataclass

from .deployers._paths import path_segment
from .exceptions import GraphApiError
from .graph import GraphClient
from .inventory import DeploymentRecord, coerce_record

logger = logging.getLogger(__name__)


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


def verify_record(graph: GraphClient, record: DeploymentRecord | dict) -> VerifyResult:
    """Check whether a deployed canary artifact still exists.

    Makes a single GET call to Graph API. Returns a VerifyResult with
    status OK (200), GONE (404), or ERROR (other failures).
    """
    record = coerce_record(record)
    canary_type = record.canary_type
    template_name = record.template_name

    try:
        if canary_type == "outlook":
            return _verify_outlook(graph, record, template_name)
        else:
            return VerifyResult(
                canary_type=canary_type,
                template_name=template_name,
                target="",
                status=VerifyStatus.ERROR,
                detail=f"Unsupported canary type: {canary_type}",
            )
    except GraphApiError as exc:
        if exc.status_code == 404:
            return VerifyResult(
                canary_type=canary_type,
                template_name=template_name,
                target=_get_target(record, canary_type),
                status=VerifyStatus.GONE,
                detail=str(exc),
            )
        return VerifyResult(
            canary_type=canary_type,
            template_name=template_name,
            target=_get_target(record, canary_type),
            status=VerifyStatus.ERROR,
            detail=f"Graph API error (HTTP {exc.status_code}): {exc}",
        )


def _verify_outlook(graph: GraphClient, record: DeploymentRecord, template_name: str) -> VerifyResult:
    target_user = record.target_user
    if record.delivery_mode == "send":
        return VerifyResult(
            canary_type="outlook",
            template_name=template_name,
            target=target_user,
            status=VerifyStatus.ERROR,
            detail="Verify only supports draft-mode outlook records",
        )

    folder_id = record.folder_id
    if not target_user or not folder_id:
        return VerifyResult(
            canary_type="outlook",
            template_name=template_name,
            target=target_user,
            status=VerifyStatus.ERROR,
            detail="Record missing target_user or folder_id",
        )
    graph.get(f"/users/{path_segment(target_user)}/mailFolders/{path_segment(folder_id)}")
    # Also confirm the canary message itself: a surviving folder with a
    # deleted message is a dead canary (the internetMessageId match — the
    # primary detection path — no longer fires). Older records may lack
    # message_id; for those the folder check is the best available signal.
    message_id = record.message_id
    if message_id:
        graph.get(
            f"/users/{path_segment(target_user)}/mailFolders/{path_segment(folder_id)}"
            f"/messages/{path_segment(message_id)}"
        )
    return VerifyResult(
        canary_type="outlook",
        template_name=template_name,
        target=target_user,
        status=VerifyStatus.OK,
    )


def run_verify(
    records: list[tuple[str, DeploymentRecord | dict]],
    graph: GraphClient,
) -> list[VerifyResult]:
    """Check all deployment records and return results."""
    results: list[VerifyResult] = []
    for _path, record in records:
        result = verify_record(graph, record)
        results.append(result)
    return results


def _get_target(record: DeploymentRecord, canary_type: str) -> str:
    if canary_type == "outlook":
        return record.target_user
    return ""
