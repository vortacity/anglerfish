from urllib.parse import quote

import pytest

from anglerfish.deployers.teams import TeamsDeployer, remove_canary
from anglerfish.exceptions import DeploymentError, GraphApiError
from anglerfish.models import TeamsTemplate


def _template() -> TeamsTemplate:
    return TeamsTemplate(
        name="Test",
        description="Test template",
        subject="Alert Subject",
        body_html="<p>Hello</p>",
        variables=[],
    )


class StubGraph:
    def __init__(self):
        self.post_calls = []
        self.get_calls = []
        self.channel_message_id = "msg-channel-123"
        self.chat_id = "chat-abc-456"
        self.chat_message_id = "msg-chat-789"

    def post(self, path, json=None):
        self.post_calls.append((path, json))
        if "/channels/" in path and "/messages" in path:
            return {"id": self.channel_message_id}
        if path == "/chats":
            return {"id": self.chat_id}
        if "/chats/" in path and "/messages" in path:
            return {"id": self.chat_message_id}
        return {}

    def get(self, path, params=None):
        self.get_calls.append((path, params))
        encoded_channel_msg = quote(self.channel_message_id, safe="")
        encoded_chat_msg = quote(self.chat_message_id, safe="")
        if encoded_channel_msg in path:
            return {"id": self.channel_message_id}
        if encoded_chat_msg in path:
            return {"id": self.chat_message_id}
        raise AssertionError(f"Unexpected GET path: {path}")


def test_teams_deployer_channel_happy_path():
    graph = StubGraph()
    deployer = TeamsDeployer(graph, _template())

    result = deployer.deploy("", delivery_mode="channel", team_id="team-1", channel_id="chan-1")

    assert result["type"] == "teams"
    assert result["delivery_mode"] == "channel"
    assert result["team_id"] == "team-1"
    assert result["channel_id"] == "chan-1"
    assert result["message_id"] == graph.channel_message_id
    assert result["verified"] == "true"
    encoded_team = quote("team-1", safe="")
    encoded_channel = quote("chan-1", safe="")
    assert graph.post_calls[0][0] == f"/teams/{encoded_team}/channels/{encoded_channel}/messages"


def test_teams_deployer_chat_happy_path():
    graph = StubGraph()
    deployer = TeamsDeployer(graph, _template())

    result = deployer.deploy("user@contoso.com", delivery_mode="chat")

    assert result["type"] == "teams"
    assert result["delivery_mode"] == "chat"
    assert result["chat_id"] == graph.chat_id
    assert result["message_id"] == graph.chat_message_id
    assert result["target_user"] == "user@contoso.com"
    assert result["verified"] == "true"
    assert graph.post_calls[0][0] == "/chats"
    encoded_chat = quote(graph.chat_id, safe="")
    assert graph.post_calls[1][0] == f"/chats/{encoded_chat}/messages"


def test_teams_deployer_wraps_graph_errors_channel():
    class ErrorGraph:
        def post(self, path, json=None):
            raise GraphApiError("Denied", status_code=403)

    deployer = TeamsDeployer(ErrorGraph(), _template())

    with pytest.raises(DeploymentError, match="Teams deployment failed"):
        deployer.deploy("", delivery_mode="channel", team_id="t", channel_id="c")


def test_teams_deployer_wraps_graph_errors_chat():
    class ErrorGraph:
        def post(self, path, json=None):
            raise GraphApiError("Denied", status_code=403)

    deployer = TeamsDeployer(ErrorGraph(), _template())

    with pytest.raises(DeploymentError, match="Teams deployment failed"):
        deployer.deploy("user@contoso.com", delivery_mode="chat")


def test_teams_deployer_rejects_invalid_delivery_mode():
    deployer = TeamsDeployer(StubGraph(), _template())

    with pytest.raises(DeploymentError, match="Invalid delivery mode"):
        deployer.deploy("user@contoso.com", delivery_mode="invalid")


def test_teams_deployer_channel_requires_team_id():
    deployer = TeamsDeployer(StubGraph(), _template())

    with pytest.raises(DeploymentError, match="team_id is required"):
        deployer.deploy("", delivery_mode="channel", channel_id="c")


def test_teams_deployer_channel_requires_channel_id():
    deployer = TeamsDeployer(StubGraph(), _template())

    with pytest.raises(DeploymentError, match="channel_id is required"):
        deployer.deploy("", delivery_mode="channel", team_id="t")


def test_teams_deployer_chat_rejects_invalid_email():
    deployer = TeamsDeployer(StubGraph(), _template())

    with pytest.raises(DeploymentError, match="valid email address"):
        deployer.deploy("not-an-email", delivery_mode="chat")


def test_teams_deployer_channel_verification_failure(monkeypatch: pytest.MonkeyPatch):
    class VerifyFailGraph:
        def post(self, path, json=None):
            return {"id": "msg-123"}

        def get(self, path, params=None):
            return {"id": "wrong-id"}

    monkeypatch.setattr("anglerfish.deployers.teams.time.sleep", lambda *_: None)

    deployer = TeamsDeployer(VerifyFailGraph(), _template())

    with pytest.raises(DeploymentError, match="channel message was not readable"):
        deployer.deploy("", delivery_mode="channel", team_id="t", channel_id="c")


def test_teams_deployer_chat_verification_failure(monkeypatch: pytest.MonkeyPatch):
    class VerifyFailGraph:
        def __init__(self):
            self.post_count = 0

        def post(self, path, json=None):
            self.post_count += 1
            if self.post_count == 1:
                return {"id": "chat-1"}
            return {"id": "msg-123"}

        def get(self, path, params=None):
            return {"id": "wrong-id"}

    monkeypatch.setattr("anglerfish.deployers.teams.time.sleep", lambda *_: None)

    deployer = TeamsDeployer(VerifyFailGraph(), _template())

    with pytest.raises(DeploymentError, match="chat message was not readable"):
        deployer.deploy("user@contoso.com", delivery_mode="chat")


def test_teams_deployer_channel_verification_retries_on_404_then_succeeds(
    monkeypatch: pytest.MonkeyPatch,
):
    message_id = "msg-retry-123"

    class RetryGraph:
        def __init__(self):
            self.get_count = 0

        def post(self, path, json=None):
            return {"id": message_id}

        def get(self, path, params=None):
            self.get_count += 1
            if self.get_count == 1:
                raise GraphApiError("Not Found", status_code=404)
            return {"id": message_id}

    sleep_calls = []
    monkeypatch.setattr("anglerfish.deployers.teams.time.sleep", lambda s: sleep_calls.append(s))

    graph = RetryGraph()
    deployer = TeamsDeployer(graph, _template())
    result = deployer.deploy("", delivery_mode="channel", team_id="team-1", channel_id="chan-1")

    assert result["verified"] == "true"
    assert len(sleep_calls) == 1


def test_teams_deployer_chat_post_uses_correct_actor_binding():
    graph = StubGraph()
    deployer = TeamsDeployer(graph, _template())

    deployer.deploy("user@contoso.com", delivery_mode="chat")

    body = graph.post_calls[0][1]
    members = body["members"]
    assert len(members) == 2
    actor = members[0]
    assert actor["@odata.type"] == "#microsoft.graph.aadUserConversationMember"
    assert actor["roles"] == ["owner"]
    assert "users('me')" in actor["user@odata.bind"]
    target = members[1]
    assert target["@odata.type"] == "#microsoft.graph.aadUserConversationMember"
    assert target["roles"] == ["owner"]
    assert quote("user@contoso.com", safe="") in target["user@odata.bind"]


def test_teams_deployer_verification_non_404_error_raises_immediately(
    monkeypatch: pytest.MonkeyPatch,
):
    class ForbiddenGraph:
        def __init__(self):
            self.post_count = 0

        def post(self, path, json=None):
            self.post_count += 1
            if self.post_count == 1:
                return {"id": "chat-1"}
            return {"id": "msg-123"}

        def get(self, path, params=None):
            raise GraphApiError("Forbidden", status_code=403)

    monkeypatch.setattr(
        "anglerfish.deployers.teams.time.sleep",
        lambda s: (_ for _ in ()).throw(AssertionError("sleep should not be called")),
    )

    deployer = TeamsDeployer(ForbiddenGraph(), _template())

    with pytest.raises(DeploymentError, match="Teams verification failed"):
        deployer.deploy("user@contoso.com", delivery_mode="chat")


# ---------------------------------------------------------------------------
# remove_canary() tests
# ---------------------------------------------------------------------------


class _DelGraph:
    def __init__(self):
        self.delete_calls: list[str] = []

    def delete(self, path: str) -> None:
        self.delete_calls.append(path)


def test_teams_remove_canary_channel_mode_soft_deletes_message():
    graph = _DelGraph()
    record = {
        "delivery_mode": "channel",
        "team_id": "team-1",
        "channel_id": "chan-1",
        "message_id": "msg-123",
    }
    result = remove_canary(graph, record)

    assert result["removed"] == "true"
    assert result["delivery_mode"] == "channel"
    assert result["message_id"] == "msg-123"
    assert "note" in result
    encoded_team = quote("team-1", safe="")
    encoded_channel = quote("chan-1", safe="")
    encoded_msg = quote("msg-123", safe="")
    assert graph.delete_calls == [f"/teams/{encoded_team}/channels/{encoded_channel}/messages/{encoded_msg}"]


def test_teams_remove_canary_chat_mode_soft_deletes_message():
    graph = _DelGraph()
    record = {
        "delivery_mode": "chat",
        "chat_id": "chat-abc",
        "message_id": "msg-456",
    }
    result = remove_canary(graph, record)

    assert result["removed"] == "true"
    assert result["delivery_mode"] == "chat"
    assert result["message_id"] == "msg-456"
    assert "note" in result
    encoded_chat = quote("chat-abc", safe="")
    encoded_msg = quote("msg-456", safe="")
    assert graph.delete_calls == [f"/chats/{encoded_chat}/messages/{encoded_msg}"]


def test_teams_remove_canary_raises_when_message_id_missing():
    with pytest.raises(DeploymentError, match="missing 'message_id'"):
        remove_canary(_DelGraph(), {"delivery_mode": "channel", "team_id": "t1", "channel_id": "c1"})


def test_teams_remove_canary_channel_raises_when_team_or_channel_id_missing():
    with pytest.raises(DeploymentError, match="missing 'team_id' or 'channel_id'"):
        remove_canary(_DelGraph(), {"delivery_mode": "channel", "message_id": "m1"})


def test_teams_remove_canary_chat_raises_when_chat_id_missing():
    with pytest.raises(DeploymentError, match="missing 'chat_id'"):
        remove_canary(_DelGraph(), {"delivery_mode": "chat", "message_id": "m1"})


def test_teams_remove_canary_channel_wraps_graph_error():
    class ErrorGraph:
        def delete(self, path: str) -> None:
            raise GraphApiError("Denied", status_code=403)

    with pytest.raises(DeploymentError, match="Teams cleanup failed"):
        remove_canary(
            ErrorGraph(),
            {"delivery_mode": "channel", "team_id": "t1", "channel_id": "c1", "message_id": "m1"},
        )


def test_teams_remove_canary_chat_wraps_graph_error():
    class ErrorGraph:
        def delete(self, path: str) -> None:
            raise GraphApiError("Denied", status_code=403)

    with pytest.raises(DeploymentError, match="Teams cleanup failed"):
        remove_canary(
            ErrorGraph(),
            {"delivery_mode": "chat", "chat_id": "chat-1", "message_id": "m1"},
        )


def test_teams_remove_canary_defaults_to_channel_when_delivery_mode_absent():
    graph = _DelGraph()
    record = {"team_id": "t1", "channel_id": "c1", "message_id": "m1"}
    result = remove_canary(graph, record)
    assert result["delivery_mode"] == "channel"
    assert result["removed"] == "true"
