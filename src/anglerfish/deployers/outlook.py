"""Outlook canary deployment implementation."""

from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone
from urllib.parse import quote

from ..exceptions import DeploymentError, GraphApiError
from ..models import OutlookTemplate
from .base import BaseDeployer

_VERIFY_ATTEMPTS = 3
_SEND_VERIFY_ATTEMPTS = 5
_SEND_VERIFY_WINDOW = timedelta(minutes=2)


class OutlookDeployer(BaseDeployer):
    def __init__(self, graph, template: OutlookTemplate):
        super().__init__(graph, template)

    def deploy(self, target_user: str, **kwargs) -> dict[str, str]:
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
        try:
            folder = self.graph.post(
                f"/users/{encoded_user}/mailFolders",
                json={"displayName": self.template.folder_name, "isHidden": True},
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
            internet_message_id = str(message.get("internetMessageId", ""))

            self._verify_created_artifacts(
                encoded_user=encoded_user,
                encoded_folder_id=encoded_folder_id,
                folder_id=folder_id,
                message_id=message_id,
            )

            return {
                "delivery_mode": "draft",
                "folder_id": folder_id,
                "folder_name": self.template.folder_name,
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
            inbox_message = self._verify_sent_message(
                encoded_user=encoded_user,
                started_at=started_at,
            )
            return {
                "delivery_mode": "send",
                "subject": self.template.subject,
                "target_user": target_user,
                "inbox_message_id": str(inbox_message.get("id", "")),
                "internet_message_id": str(inbox_message.get("internetMessageId", "")),
                "verified": "true",
            }
        except GraphApiError as exc:
            raise DeploymentError(f"Outlook deployment failed: {exc}") from exc

    def _verify_created_artifacts(
        self,
        *,
        encoded_user: str,
        encoded_folder_id: str,
        folder_id: str,
        message_id: str,
    ) -> None:
        encoded_message_id = _path_segment(message_id)

        for attempt in range(_VERIFY_ATTEMPTS):
            try:
                folder = self.graph.get(
                    f"/users/{encoded_user}/mailFolders/{encoded_folder_id}",
                    params={"$select": "id,isHidden"},
                )
                message = self.graph.get(
                    f"/users/{encoded_user}/mailFolders/{encoded_folder_id}/messages/{encoded_message_id}",
                    params={"$select": "id"},
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
            return

        raise DeploymentError("Outlook verification failed: created artifacts were not readable after retries.")

    def _verify_sent_message(
        self,
        *,
        encoded_user: str,
        started_at: datetime,
    ) -> dict:
        for attempt in range(_SEND_VERIFY_ATTEMPTS):
            try:
                inbox = self.graph.get(
                    f"/users/{encoded_user}/mailFolders/inbox/messages",
                    params={
                        "$top": 25,
                        "$select": "id,subject,internetMessageId,receivedDateTime",
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
                    received = _parse_graph_datetime(str(message.get("receivedDateTime", "")))
                    if received and received >= started_at - _SEND_VERIFY_WINDOW:
                        if str(message.get("id", "")).strip():
                            return message

            if attempt < _SEND_VERIFY_ATTEMPTS - 1:
                time.sleep(attempt + 1)

        raise DeploymentError("Outlook verification failed: sent message was not found in the Inbox.")


def _path_segment(value: str) -> str:
    return quote(value, safe="")


def remove_canary(graph, record: dict[str, str]) -> dict[str, str]:
    """Remove a deployed Outlook canary artifact."""
    delivery_mode = record.get("delivery_mode", "draft").strip().lower()
    target_user = record.get("target_user", "").strip()
    if not target_user:
        raise DeploymentError("Deployment record missing 'target_user'.")

    encoded_user = _path_segment(target_user)

    if delivery_mode == "draft":
        folder_id = record.get("folder_id", "").strip()
        if not folder_id:
            raise DeploymentError("Deployment record missing 'folder_id'.")
        encoded_folder_id = _path_segment(folder_id)
        try:
            graph.delete(f"/users/{encoded_user}/mailFolders/{encoded_folder_id}")
        except GraphApiError as exc:
            raise DeploymentError(f"Outlook cleanup failed: {exc}") from exc
        return {"type": "outlook", "delivery_mode": "draft", "folder_id": folder_id, "removed": "true"}

    # send mode: delete inbox message (moves to Deleted Items)
    inbox_message_id = record.get("inbox_message_id", "").strip()
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


def _parse_graph_datetime(raw: str) -> datetime | None:
    value = raw.strip()
    if not value:
        return None
    if value.endswith("Z"):
        value = f"{value[:-1]}+00:00"
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)
