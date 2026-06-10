"""Outlook canary deployment implementation."""

from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import secrets
from typing import Any, Sequence, TYPE_CHECKING

from .._io import as_utc, parse_utc_datetime
from ..exceptions import DeploymentError, GraphApiError
from ..inventory import DeploymentRecord, coerce_record
from ..models import CanaryAlert, OutlookTemplate, VerifyResult, VerifyStatus
from .base import BaseDeployer, CanaryMatcher, CanaryType
from ._paths import path_segment as _path_segment

if TYPE_CHECKING:
    from ..graph import GraphClient

_VERIFY_ATTEMPTS = 3
_SEND_VERIFY_ATTEMPTS = 5
_SEND_VERIFY_WINDOW = timedelta(minutes=2)


class OutlookDeployer(BaseDeployer):
    def __init__(self, graph: GraphClient, template: OutlookTemplate) -> None:
        super().__init__(graph, template)

    def deploy(self, target_user: str, **kwargs: Any) -> dict[str, str]:
        if not target_user or "@" not in target_user:
            raise DeploymentError("Target user must be a valid mailbox UPN/email.")

        delivery_mode = str(kwargs.get("delivery_mode", "draft")).strip().lower()
        if delivery_mode not in {"draft", "send"}:
            raise DeploymentError("Invalid delivery mode. Supported values are 'draft' and 'send'.")

        if delivery_mode == "send":
            return self._deploy_send(target_user)
        return self._deploy_draft(target_user)

    def _deploy_draft(self, target_user: str) -> dict[str, str]:
        encoded_user = _path_segment(target_user)
        canary_id = _new_canary_id()
        folder_name = _deployment_folder_name(self.template.folder_name, canary_id)
        try:
            folder = self.graph.post(
                f"/users/{encoded_user}/mailFolders",
                json={"displayName": folder_name, "isHidden": True},
            )
            folder_id = str(folder.get("id", ""))
            if not folder_id:
                raise DeploymentError("Graph response missing folder id.")

            encoded_folder_id = _path_segment(folder_id)
            message = self.graph.post(
                f"/users/{encoded_user}/mailFolders/{encoded_folder_id}/messages",
                json={
                    "subject": self.template.subject,
                    "body": {
                        "contentType": "html",
                        "content": self.template.body_html,
                    },
                    "from": {
                        "emailAddress": {
                            "name": self.template.sender_name,
                            "address": self.template.sender_email,
                        }
                    },
                    "isRead": False,
                },
            )
            message_id = str(message.get("id", ""))
            if not message_id:
                raise DeploymentError("Graph response missing message id.")
            internet_message_id = str(message.get("internetMessageId", "")).strip()

            verified_message = self._verify_created_artifacts(
                encoded_user=encoded_user,
                encoded_folder_id=encoded_folder_id,
                folder_id=folder_id,
                message_id=message_id,
            )
            if not internet_message_id:
                internet_message_id = str(verified_message.get("internetMessageId", "")).strip()
            if not internet_message_id:
                raise DeploymentError("Outlook deployment failed: Graph response missing internetMessageId.")

            return {
                "delivery_mode": "draft",
                "canary_id": canary_id,
                "folder_id": folder_id,
                "folder_name": folder_name,
                "message_id": message_id,
                "internet_message_id": internet_message_id,
                "subject": self.template.subject,
                "target_user": target_user,
                "verified": "true",
            }
        except GraphApiError as exc:
            raise DeploymentError(f"Outlook deployment failed: {exc}") from exc

    def _deploy_send(self, target_user: str) -> dict[str, str]:
        encoded_user = _path_segment(target_user)
        started_at = datetime.now(timezone.utc)
        try:
            self.graph.post(
                f"/users/{encoded_user}/sendMail",
                json={
                    "message": {
                        "subject": self.template.subject,
                        "body": {
                            "contentType": "html",
                            "content": self.template.body_html,
                        },
                        "toRecipients": [
                            {
                                "emailAddress": {
                                    "address": target_user,
                                }
                            }
                        ],
                    },
                    "saveToSentItems": False,
                },
            )
            # From here on the mail is live in the target mailbox. Verification
            # problems must degrade to an unverified record, never to a raised
            # error: a raise would leave a deployed canary with no record at
            # all (untracked, unmonitorable, and impossible to clean up).
            inbox_message = self._verify_sent_message(
                target_user=target_user,
                encoded_user=encoded_user,
                started_at=started_at,
            )
            result = {
                "delivery_mode": "send",
                "subject": self.template.subject,
                "target_user": target_user,
                "inbox_message_id": "",
                "internet_message_id": "",
                "verified": "false",
            }
            if inbox_message is None:
                result["verify_note"] = (
                    "Mail was accepted by Graph sendMail but could not be confirmed in the "
                    "Inbox within the verification window."
                )
                return result

            result["inbox_message_id"] = str(inbox_message.get("id", ""))
            internet_message_id = str(inbox_message.get("internetMessageId", "")).strip()
            if not internet_message_id:
                result["verify_note"] = (
                    "Sent message was found but its internetMessageId could not be confirmed; "
                    "monitor correlation will rely on re-deployment or manual record repair."
                )
                return result

            result["internet_message_id"] = internet_message_id
            result["verified"] = "true"
            return result
        except GraphApiError as exc:
            raise DeploymentError(f"Outlook deployment failed: {exc}") from exc

    def _verify_created_artifacts(
        self,
        *,
        encoded_user: str,
        encoded_folder_id: str,
        folder_id: str,
        message_id: str,
    ) -> dict:
        encoded_message_id = _path_segment(message_id)

        for attempt in range(_VERIFY_ATTEMPTS):
            try:
                folder = self.graph.get(
                    f"/users/{encoded_user}/mailFolders/{encoded_folder_id}",
                    params={"$select": "id,isHidden"},
                )
                message = self.graph.get(
                    f"/users/{encoded_user}/mailFolders/{encoded_folder_id}/messages/{encoded_message_id}",
                    params={"$select": "id,internetMessageId"},
                )
            except GraphApiError as exc:
                if exc.status_code == 404 and attempt < _VERIFY_ATTEMPTS - 1:
                    time.sleep(attempt + 1)
                    continue
                raise DeploymentError(f"Outlook verification failed: {exc}") from exc

            if str(folder.get("id", "")) != folder_id:
                raise DeploymentError("Outlook verification failed: created folder could not be confirmed.")
            if folder.get("isHidden") is not True:
                raise DeploymentError("Outlook verification failed: created folder is not hidden.")
            if str(message.get("id", "")) != message_id:
                raise DeploymentError("Outlook verification failed: created message could not be confirmed.")
            return message

        raise DeploymentError("Outlook verification failed: created artifacts were not readable after retries.")

    def _verify_sent_message(
        self,
        *,
        target_user: str,
        encoded_user: str,
        started_at: datetime,
    ) -> dict | None:
        """Find the just-sent canary in the Inbox; ``None`` if not confirmable."""
        for attempt in range(_SEND_VERIFY_ATTEMPTS):
            try:
                inbox = self.graph.get(
                    f"/users/{encoded_user}/mailFolders/inbox/messages",
                    params={
                        "$top": 25,
                        "$select": "id,subject,internetMessageId,receivedDateTime,from",
                        "$orderby": "receivedDateTime desc",
                    },
                )
            except GraphApiError as exc:
                if exc.status_code == 404 and attempt < _SEND_VERIFY_ATTEMPTS - 1:
                    time.sleep(attempt + 1)
                    continue
                raise DeploymentError(f"Outlook verification failed: {exc}") from exc

            candidates = inbox.get("value", [])
            if isinstance(candidates, list):
                for message in candidates:
                    if not isinstance(message, dict):
                        continue
                    if str(message.get("subject", "")) != self.template.subject:
                        continue
                    # sendMail to self arrives from the mailbox owner. Reject a
                    # same-subject message from another sender, or cleanup would
                    # later delete someone else's mail.
                    if not _from_matches_target(message, target_user):
                        continue
                    received = parse_utc_datetime(message.get("receivedDateTime", ""))
                    if received and received >= started_at - _SEND_VERIFY_WINDOW:
                        if str(message.get("id", "")).strip():
                            return message

            if attempt < _SEND_VERIFY_ATTEMPTS - 1:
                time.sleep(attempt + 1)

        return None


def remove_canary(graph: GraphClient, record: DeploymentRecord | dict) -> dict[str, str]:
    """Remove a deployed Outlook canary artifact."""
    record = coerce_record(record)
    target_user = record.target_user
    if not target_user:
        raise DeploymentError("Deployment record missing 'target_user'.")

    encoded_user = _path_segment(target_user)

    if record.delivery_mode == "draft":
        folder_id = record.folder_id
        if not folder_id:
            raise DeploymentError("Deployment record missing 'folder_id'.")
        encoded_folder_id = _path_segment(folder_id)
        try:
            graph.delete(f"/users/{encoded_user}/mailFolders/{encoded_folder_id}")
        except GraphApiError as exc:
            raise DeploymentError(f"Outlook cleanup failed: {exc}") from exc
        return {"type": "outlook", "delivery_mode": "draft", "folder_id": folder_id, "removed": "true"}

    # send mode: delete inbox message (moves to Deleted Items)
    inbox_message_id = record.inbox_message_id
    if not inbox_message_id:
        raise DeploymentError("Deployment record missing 'inbox_message_id'.")
    encoded_message_id = _path_segment(inbox_message_id)
    try:
        graph.delete(f"/users/{encoded_user}/mailFolders/inbox/messages/{encoded_message_id}")
    except GraphApiError as exc:
        raise DeploymentError(f"Outlook cleanup failed: {exc}") from exc
    return {
        "type": "outlook",
        "delivery_mode": "send",
        "inbox_message_id": inbox_message_id,
        "removed": "true",
        "note": "Message moved to Deleted Items. Empty Deleted Items to permanently remove.",
    }


def trigger_canary_access(graph: GraphClient, record: DeploymentRecord | dict) -> dict[str, str]:
    """Read a deployed Outlook canary through Graph to generate authorized audit evidence."""
    record = coerce_record(record)
    if record.canary_type != "outlook":
        raise DeploymentError("Only outlook canaries are supported in this release.")

    target_user = record.target_user
    if not target_user:
        raise DeploymentError("Deployment record missing 'target_user'.")
    encoded_user = _path_segment(target_user)

    delivery_mode = record.delivery_mode
    try:
        if delivery_mode == "draft":
            folder_id = record.folder_id
            message_id = record.message_id
            if not folder_id:
                raise DeploymentError("Deployment record missing 'folder_id'.")
            if not message_id:
                raise DeploymentError("Deployment record missing 'message_id'.")
            message = graph.get(
                f"/users/{encoded_user}/mailFolders/{_path_segment(folder_id)}/messages/{_path_segment(message_id)}",
                params={"$select": "id,subject,internetMessageId,receivedDateTime"},
            )
        elif delivery_mode == "send":
            message_id = record.inbox_message_id
            if not message_id:
                raise DeploymentError("Deployment record missing 'inbox_message_id'.")
            message = graph.get(
                f"/users/{encoded_user}/mailFolders/inbox/messages/{_path_segment(message_id)}",
                params={"$select": "id,subject,internetMessageId,receivedDateTime"},
            )
        else:
            raise DeploymentError("Invalid delivery mode. Supported values are 'draft' and 'send'.")
    except GraphApiError as exc:
        raise DeploymentError(f"Outlook demo access trigger failed: {exc}") from exc

    return {
        "type": "outlook",
        "delivery_mode": delivery_mode,
        "target_user": target_user,
        "message_id": str(message.get("id") or record.message_id or record.inbox_message_id or ""),
        "internet_message_id": str(message.get("internetMessageId", "")),
        "subject": str(message.get("subject") or record.subject),
        "triggered": "true",
    }


def _new_canary_id() -> str:
    return f"af-{secrets.token_hex(4)}"


def _deployment_folder_name(base_name: str, canary_id: str) -> str:
    clean_base = str(base_name or "Anglerfish Canary").strip() or "Anglerfish Canary"
    return f"{clean_base} - {canary_id}"


def _from_matches_target(message: dict, target_user: str) -> bool:
    sender = message.get("from")
    if not isinstance(sender, dict):
        # Defensive: tolerate responses that omit the selected "from" field.
        return True
    address = str((sender.get("emailAddress") or {}).get("address") or "").strip()
    if not address:
        return True
    return address.casefold() == target_user.casefold()


# ------------------------------------------------------------------
# Audit-event matching
# ------------------------------------------------------------------


@dataclass
class _CanaryEntry:
    """Internal index entry for a single deployed Outlook canary."""

    canary_type: str
    template_name: str
    record_path: str
    internet_message_id: str = ""
    folder_name: str = ""
    folder_id: str = ""
    target_user: str = ""
    subject: str = ""
    canary_id: str = ""
    expires_at: datetime | None = None


def _build_entry(record_path: str, rec: DeploymentRecord) -> _CanaryEntry:
    return _CanaryEntry(
        canary_type=rec.canary_type or "unknown",
        template_name=rec.template_name,
        record_path=record_path,
        internet_message_id=rec.internet_message_id,
        folder_name=rec.folder_name,
        folder_id=rec.folder_id,
        target_user=rec.target_user,
        subject=rec.subject,
        canary_id=rec.canary_id,
        expires_at=rec.monitor_expires_at,
    )


def _build_alert(entry: _CanaryEntry, event: dict, *, artifact_label: str) -> CanaryAlert:
    return CanaryAlert(
        canary_type=entry.canary_type,
        template_name=entry.template_name or entry.subject or "(unnamed)",
        artifact_label=artifact_label,
        accessed_by=str(event.get("UserId") or event.get("UserKey") or "unknown"),
        source_ip=str(event.get("ClientIP") or event.get("ClientIPAddress") or "unknown"),
        timestamp=str(event.get("CreationTime") or event.get("Timestamp") or ""),
        operation=str(event.get("Operation") or ""),
        client_info=str(event.get("ClientInfoString") or event.get("ClientAppId") or ""),
        record_path=entry.record_path,
    )


def _entry_is_expired(entry: _CanaryEntry, now: datetime | None) -> bool:
    if entry.expires_at is None:
        return False
    current_time = as_utc(now or datetime.now(timezone.utc))
    return current_time > entry.expires_at


class OutlookMatcher(CanaryMatcher):
    """Match MailItemsAccessed audit events against deployed Outlook canaries."""

    def __init__(self, records: Sequence[tuple[str, DeploymentRecord]]):
        self._entries: list[_CanaryEntry] = []
        self._by_internet_message_id: dict[str, _CanaryEntry] = {}
        for path, rec in records:
            entry = _build_entry(path, rec)
            self._entries.append(entry)
            if entry.internet_message_id:
                self._by_internet_message_id[entry.internet_message_id] = entry

    @property
    def count(self) -> int:
        return len(self._entries)

    def match(self, event: dict, *, now: datetime | None = None) -> CanaryAlert | None:
        if str(event.get("Operation", "")) != "MailItemsAccessed":
            return None

        # Check MailAccessType — "Bind" events carry FolderItems.
        folders = event.get("Folders") or []
        for folder in folders:
            if not isinstance(folder, dict):
                continue
            folder_items = folder.get("FolderItems") or []
            for item in folder_items:
                if not isinstance(item, dict):
                    continue
                imid = str(item.get("InternetMessageId") or "").strip()
                if imid and imid in self._by_internet_message_id:
                    entry = self._by_internet_message_id[imid]
                    if _entry_is_expired(entry, now):
                        continue
                    return _build_alert(entry, event, artifact_label=f"internet_message_id: {imid}")

        # Secondary: match by folder name (Sync events lack FolderItems).
        for folder in folders:
            if not isinstance(folder, dict):
                continue
            event_folder_id = str(folder.get("Id") or "").strip()
            folder_path = str(folder.get("Path") or "")
            for entry in self._entries:
                if _entry_is_expired(entry, now):
                    continue
                if entry.folder_id and event_folder_id and entry.folder_id == event_folder_id:
                    return _build_alert(entry, event, artifact_label=f"folder_id: {entry.folder_id}")
                if entry.canary_id and entry.folder_name:
                    folder_path_lower = folder_path.casefold()
                    if (
                        entry.canary_id.casefold() in folder_path_lower
                        and entry.folder_name.casefold() in folder_path_lower
                    ):
                        return _build_alert(entry, event, artifact_label=f"folder: {entry.folder_name}")

        return None


# ------------------------------------------------------------------
# Health check
# ------------------------------------------------------------------


def verify_preflight(record: DeploymentRecord) -> VerifyResult | None:
    """Screen records that cannot be verified via Graph (no API call needed)."""
    if record.delivery_mode == "send":
        return VerifyResult(
            canary_type="outlook",
            template_name=record.template_name,
            target=record.target_user,
            status=VerifyStatus.ERROR,
            detail="Verify only supports draft-mode outlook records",
        )
    if not record.target_user or not record.folder_id:
        return VerifyResult(
            canary_type="outlook",
            template_name=record.template_name,
            target=record.target_user,
            status=VerifyStatus.ERROR,
            detail="Record missing target_user or folder_id",
        )
    return None


def verify_canary(graph: GraphClient, record: DeploymentRecord) -> VerifyResult:
    """Check whether a deployed Outlook canary still exists (draft mode only)."""
    preflight = verify_preflight(record)
    if preflight is not None:
        return preflight

    template_name = record.template_name
    target_user = record.target_user
    folder_id = record.folder_id
    graph.get(f"/users/{_path_segment(target_user)}/mailFolders/{_path_segment(folder_id)}")
    # Also confirm the canary message itself: a surviving folder with a
    # deleted message is a dead canary (the internetMessageId match — the
    # primary detection path — no longer fires). Older records may lack
    # message_id; for those the folder check is the best available signal.
    if record.message_id:
        graph.get(
            f"/users/{_path_segment(target_user)}/mailFolders/{_path_segment(folder_id)}"
            f"/messages/{_path_segment(record.message_id)}"
        )
    return VerifyResult(
        canary_type="outlook",
        template_name=template_name,
        target=target_user,
        status=VerifyStatus.OK,
    )


# ------------------------------------------------------------------
# Lifecycle plugin
# ------------------------------------------------------------------


class OutlookCanaryType(CanaryType):
    """Outlook draft/send canaries detected via Audit.Exchange."""

    name = "outlook"
    audit_content_types = ("Audit.Exchange",)

    def create_deployer(self, graph: GraphClient, template: Any) -> BaseDeployer:
        return OutlookDeployer(graph, template)

    def remove(self, graph: GraphClient, record: DeploymentRecord) -> dict[str, str]:
        return remove_canary(graph, record)

    def trigger_access(self, graph: GraphClient, record: DeploymentRecord) -> dict[str, str]:
        return trigger_canary_access(graph, record)

    def verify(self, graph: GraphClient, record: DeploymentRecord) -> VerifyResult:
        return verify_canary(graph, record)

    def preflight_verify(self, record: DeploymentRecord) -> VerifyResult | None:
        return verify_preflight(record)

    def build_matcher(self, records: Sequence[tuple[str, DeploymentRecord]]) -> CanaryMatcher:
        return OutlookMatcher(records)
