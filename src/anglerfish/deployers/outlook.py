"""Outlook canary deployment implementation."""

from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone
import secrets
from typing import Any, TYPE_CHECKING

from .._io import parse_utc_datetime
from ..exceptions import DeploymentError, GraphApiError
from ..inventory import DeploymentRecord, coerce_record
from ..models import OutlookTemplate
from .base import BaseDeployer
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
