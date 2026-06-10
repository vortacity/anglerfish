"""Canary health-check: verify deployed artifacts still exist via Graph API."""

from __future__ import annotations

import logging

from .deployers.registry import find_canary_type
from .exceptions import GraphApiError
from .graph import GraphClient
from .inventory import DeploymentRecord, coerce_record
from .models import VerifyResult, VerifyStatus

__all__ = ["VerifyResult", "VerifyStatus", "run_verify", "verify_record"]

logger = logging.getLogger(__name__)


def verify_record(graph: GraphClient, record: DeploymentRecord | dict) -> VerifyResult:
    """Check whether a deployed canary artifact still exists.

    Dispatches to the record's registered canary type. Returns a VerifyResult
    with status OK (200), GONE (404), or ERROR (other failures).
    """
    record = coerce_record(record)
    canary_type = find_canary_type(record.canary_type)
    if canary_type is None:
        return VerifyResult(
            canary_type=record.canary_type,
            template_name=record.template_name,
            target="",
            status=VerifyStatus.ERROR,
            detail=f"Unsupported canary type: {record.canary_type}",
        )

    try:
        return canary_type.verify(graph, record)
    except GraphApiError as exc:
        if exc.status_code == 404:
            return VerifyResult(
                canary_type=record.canary_type,
                template_name=record.template_name,
                target=record.target_user,
                status=VerifyStatus.GONE,
                detail=str(exc),
            )
        return VerifyResult(
            canary_type=record.canary_type,
            template_name=record.template_name,
            target=record.target_user,
            status=VerifyStatus.ERROR,
            detail=f"Graph API error (HTTP {exc.status_code}): {exc}",
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
