"""Teams canary deployment implementation."""

from __future__ import annotations

import time
from urllib.parse import quote

from ..exceptions import DeploymentError, GraphApiError
from ..models import TeamsTemplate
from .base import BaseDeployer

_VERIFY_ATTEMPTS = 3


class TeamsDeployer(BaseDeployer):
    def __init__(self, graph, template: TeamsTemplate):
        super().__init__(graph, template)

    def deploy(self, target_user: str, **kwargs) -> dict[str, str]:
        delivery_mode = str(kwargs.get("delivery_mode", "channel")).strip().lower()
        if delivery_mode not in {"channel", "chat"}:
            raise DeploymentError("Invalid delivery mode. Supported values are 'channel' and 'chat'.")

        if delivery_mode == "channel":
            team_id = str(kwargs.get("team_id", "")).strip()
            channel_id = str(kwargs.get("channel_id", "")).strip()
            if not team_id:
                raise DeploymentError("team_id is required for channel delivery mode.")
            if not channel_id:
                raise DeploymentError("channel_id is required for channel delivery mode.")
            return self._deploy_channel(team_id, channel_id)

        if not target_user or "@" not in target_user:
            raise DeploymentError("Target user must be a valid email address for chat delivery mode.")
        actor_user_id = str(kwargs.get("actor_user_id", "")).strip()
        return self._deploy_chat(target_user, actor_user_id=actor_user_id)

    def _deploy_channel(self, team_id: str, channel_id: str) -> dict[str, str]:
        encoded_team_id = quote(team_id, safe="")
        encoded_channel_id = quote(channel_id, safe="")
        try:
            message = self.graph.post(
                f"/teams/{encoded_team_id}/channels/{encoded_channel_id}/messages",
                json={
                    "subject": self.template.subject,
                    "body": {
                        "contentType": "html",
                        "content": self.template.body_html,
                    },
                },
            )
            message_id = str(message.get("id", ""))
            if not message_id:
                raise DeploymentError("Graph response missing message id.")

            self._verify_message(
                f"/teams/{encoded_team_id}/channels/{encoded_channel_id}/messages",
                message_id,
                context="channel message",
            )

            return {
                "type": "teams",
                "delivery_mode": "channel",
                "team_id": team_id,
                "channel_id": channel_id,
                "message_id": message_id,
                "subject": self.template.subject,
                "verified": "true",
            }
        except GraphApiError as exc:
            raise DeploymentError(f"Teams deployment failed: {exc}") from exc

    def _deploy_chat(self, target_user: str, *, actor_user_id: str = "") -> dict[str, str]:
        actor_binding = "https://graph.microsoft.com/v1.0/users('me')"
        if actor_user_id:
            actor_binding = f"https://graph.microsoft.com/v1.0/users('{quote(actor_user_id, safe='')}')"
        try:
            chat = self.graph.post(
                "/chats",
                json={
                    "chatType": "oneOnOne",
                    "members": [
                        {
                            "@odata.type": "#microsoft.graph.aadUserConversationMember",
                            "roles": ["owner"],
                            "user@odata.bind": actor_binding,
                        },
                        {
                            "@odata.type": "#microsoft.graph.aadUserConversationMember",
                            "roles": ["owner"],
                            "user@odata.bind": f"https://graph.microsoft.com/v1.0/users('{quote(target_user, safe='')}')",
                        },
                    ],
                },
            )
            chat_id = str(chat.get("id", ""))
            if not chat_id:
                raise DeploymentError("Graph response missing chat id.")

            encoded_chat_id = quote(chat_id, safe="")
            message = self.graph.post(
                f"/chats/{encoded_chat_id}/messages",
                json={
                    "subject": self.template.subject,
                    "body": {
                        "contentType": "html",
                        "content": self.template.body_html,
                    },
                },
            )
            message_id = str(message.get("id", ""))
            if not message_id:
                raise DeploymentError("Graph response missing message id.")

            self._verify_message(
                f"/chats/{encoded_chat_id}/messages",
                message_id,
                context="chat message",
            )

            return {
                "type": "teams",
                "delivery_mode": "chat",
                "chat_id": chat_id,
                "message_id": message_id,
                "target_user": target_user,
                "actor_user_id": actor_user_id,
                "subject": self.template.subject,
                "verified": "true",
            }
        except GraphApiError as exc:
            raise DeploymentError(f"Teams deployment failed: {exc}") from exc

    def _verify_message(self, path: str, message_id: str, *, context: str) -> None:
        """GET the message at `path` and confirm its id matches, with retries on 404."""
        encoded_message_id = quote(message_id, safe="")
        full_path = f"{path}/{encoded_message_id}"
        for attempt in range(_VERIFY_ATTEMPTS):
            try:
                result = self.graph.get(full_path, params={"$select": "id"})
            except GraphApiError as exc:
                if exc.status_code == 404 and attempt < _VERIFY_ATTEMPTS - 1:
                    time.sleep(attempt + 1)
                    continue
                raise DeploymentError(f"Teams verification failed: {exc}") from exc
            if str(result.get("id", "")) == message_id:
                return
            if attempt < _VERIFY_ATTEMPTS - 1:
                time.sleep(attempt + 1)
        raise DeploymentError(f"Teams verification failed: {context} was not readable after retries.")


def remove_canary(graph, record: dict[str, str]) -> dict[str, str]:
    """Soft-delete a deployed Teams canary message."""
    delivery_mode = record.get("delivery_mode", "channel").strip().lower()
    message_id = record.get("message_id", "").strip()
    if not message_id:
        raise DeploymentError("Deployment record missing 'message_id'.")

    encoded_message_id = quote(message_id, safe="")

    if delivery_mode == "channel":
        team_id = record.get("team_id", "").strip()
        channel_id = record.get("channel_id", "").strip()
        if not team_id or not channel_id:
            raise DeploymentError("Deployment record missing 'team_id' or 'channel_id'.")
        encoded_team_id = quote(team_id, safe="")
        encoded_channel_id = quote(channel_id, safe="")
        try:
            graph.delete(f"/teams/{encoded_team_id}/channels/{encoded_channel_id}/messages/{encoded_message_id}")
        except GraphApiError as exc:
            raise DeploymentError(f"Teams cleanup failed: {exc}") from exc
        return {
            "type": "teams",
            "delivery_mode": "channel",
            "message_id": message_id,
            "removed": "true",
            "note": "Teams messages are soft-deleted (marked as deleted, retained for compliance audit).",
        }

    # chat mode
    chat_id = record.get("chat_id", "").strip()
    if not chat_id:
        raise DeploymentError("Deployment record missing 'chat_id'.")
    encoded_chat_id = quote(chat_id, safe="")
    try:
        graph.delete(f"/chats/{encoded_chat_id}/messages/{encoded_message_id}")
    except GraphApiError as exc:
        raise DeploymentError(f"Teams cleanup failed: {exc}") from exc
    return {
        "type": "teams",
        "delivery_mode": "chat",
        "message_id": message_id,
        "removed": "true",
        "note": "Teams messages are soft-deleted (marked as deleted, retained for compliance audit).",
    }
