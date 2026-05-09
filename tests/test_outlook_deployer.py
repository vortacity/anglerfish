from datetime import datetime, timezone
from urllib.parse import quote

import pytest

from urllib.parse import quote as _quote

from anglerfish.deployers.outlook import OutlookDeployer, _parse_graph_datetime, remove_canary, trigger_canary_access
from anglerfish.exceptions import DeploymentError, GraphApiError
from anglerfish.models import OutlookTemplate


class StubGraph:
    def __init__(self):
        self.post_calls = []
        self.get_calls = []
        self.folder_id = "folder/123=="
        self.message_id = "message/456?abc"
        self.internet_message_id = "<stub-imid@contoso.com>"

    def post(self, path, json=None):
        self.post_calls.append((path, json))
        if len(self.post_calls) == 1:
            return {"id": self.folder_id}
        return {"id": self.message_id, "internetMessageId": self.internet_message_id}

    def get(self, path, params=None):
        self.get_calls.append((path, params))
        encoded_folder_id = quote(self.folder_id, safe="")
        encoded_message_id = quote(self.message_id, safe="")
        if path.endswith(f"/mailFolders/{encoded_folder_id}"):
            return {"id": self.folder_id, "isHidden": True}
        if path.endswith(f"/messages/{encoded_message_id}"):
            return {"id": self.message_id}
        raise AssertionError(f"Unexpected GET path: {path}")


def _template() -> OutlookTemplate:
    return OutlookTemplate(
        name="Test",
        description="Test template",
        folder_name="IT Notifications",
        subject="Subject",
        body_html="<p>Hello</p>",
        sender_name="IT",
        sender_email="it@contoso.com",
        variables=[],
    )


def test_outlook_deployer_happy_path():
    graph = StubGraph()
    deployer = OutlookDeployer(graph, _template())

    result = deployer.deploy("user@contoso.com")

    encoded_user = quote("user@contoso.com", safe="")
    encoded_folder_id = quote(graph.folder_id, safe="")
    assert result["folder_id"] == graph.folder_id
    assert result["message_id"] == graph.message_id
    assert result["internet_message_id"] == graph.internet_message_id
    assert result["delivery_mode"] == "draft"
    assert result["verified"] == "true"
    assert graph.post_calls[0][0] == f"/users/{encoded_user}/mailFolders"
    assert graph.post_calls[1][0] == f"/users/{encoded_user}/mailFolders/{encoded_folder_id}/messages"
    assert graph.get_calls[0][0] == f"/users/{encoded_user}/mailFolders/{encoded_folder_id}"


def test_outlook_deployer_draft_adds_unique_canary_id_to_folder(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr("anglerfish.deployers.outlook._new_canary_id", lambda: "af-test-001")
    graph = StubGraph()
    deployer = OutlookDeployer(graph, _template())

    result = deployer.deploy("user@contoso.com")

    assert result["canary_id"] == "af-test-001"
    assert result["folder_name"] == "IT Notifications - af-test-001"
    assert graph.post_calls[0][1]["displayName"] == "IT Notifications - af-test-001"


def test_outlook_deployer_draft_uses_verified_internet_message_id_when_create_response_omits_it(
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setattr("anglerfish.deployers.outlook._new_canary_id", lambda: "af-test-002")

    class VerifyInternetMessageGraph(StubGraph):
        def post(self, path, json=None):
            self.post_calls.append((path, json))
            if len(self.post_calls) == 1:
                return {"id": self.folder_id}
            return {"id": self.message_id}

        def get(self, path, params=None):
            result = super().get(path, params)
            if path.endswith(f"/messages/{quote(self.message_id, safe='')}"):
                return {**result, "internetMessageId": self.internet_message_id}
            return result

    graph = VerifyInternetMessageGraph()
    deployer = OutlookDeployer(graph, _template())

    result = deployer.deploy("user@contoso.com")

    assert result["internet_message_id"] == graph.internet_message_id


def test_outlook_deployer_draft_requires_internet_message_id():
    class MissingInternetMessageGraph(StubGraph):
        def post(self, path, json=None):
            self.post_calls.append((path, json))
            if len(self.post_calls) == 1:
                return {"id": self.folder_id}
            return {"id": self.message_id}

    deployer = OutlookDeployer(MissingInternetMessageGraph(), _template())

    with pytest.raises(DeploymentError, match="internetMessageId"):
        deployer.deploy("user@contoso.com")


def test_outlook_deployer_wraps_graph_errors():
    class ErrorGraph:
        def post(self, path, json=None):
            raise GraphApiError("Denied", status_code=403)

    deployer = OutlookDeployer(ErrorGraph(), _template())

    with pytest.raises(DeploymentError, match="Outlook deployment failed"):
        deployer.deploy("user@contoso.com")


def test_outlook_deployer_raises_when_verification_fails():
    class VerifyFailureGraph(StubGraph):
        def get(self, path, params=None):
            if "/mailFolders/" in path and "/messages/" not in path:
                return {"id": self.folder_id, "isHidden": False}
            return {"id": self.message_id}

    deployer = OutlookDeployer(VerifyFailureGraph(), _template())

    with pytest.raises(DeploymentError, match="created folder is not hidden"):
        deployer.deploy("user@contoso.com")


def test_outlook_deployer_send_mode_happy_path():
    class SendGraph:
        def __init__(self):
            self.post_calls = []
            self.get_calls = []

        def post(self, path, json=None):
            self.post_calls.append((path, json))
            return {}

        def get(self, path, params=None):
            self.get_calls.append((path, params))
            if path.endswith("/mailFolders/inbox/messages"):
                timestamp = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
                return {
                    "value": [
                        {
                            "id": "inbox-message-123",
                            "subject": "Subject",
                            "internetMessageId": "<abc@contoso.com>",
                            "receivedDateTime": timestamp,
                        }
                    ]
                }
            raise AssertionError(f"Unexpected GET path: {path}")

    graph = SendGraph()
    deployer = OutlookDeployer(graph, _template())

    result = deployer.deploy("user@contoso.com", delivery_mode="send")

    encoded_user = quote("user@contoso.com", safe="")
    assert graph.post_calls[0][0] == f"/users/{encoded_user}/sendMail"
    send_payload = graph.post_calls[0][1]
    assert send_payload["message"]["toRecipients"][0]["emailAddress"]["address"] == "user@contoso.com"
    assert result["delivery_mode"] == "send"
    assert result["inbox_message_id"] == "inbox-message-123"
    assert result["internet_message_id"] == "<abc@contoso.com>"
    assert result["verified"] == "true"


def test_outlook_deployer_send_mode_raises_when_message_not_found(monkeypatch: pytest.MonkeyPatch):
    class SendGraph:
        def post(self, path, json=None):
            return {}

        def get(self, path, params=None):
            return {"value": []}

    monkeypatch.setattr("anglerfish.deployers.outlook.time.sleep", lambda *_: None)

    deployer = OutlookDeployer(SendGraph(), _template())

    with pytest.raises(DeploymentError, match="sent message was not found"):
        deployer.deploy("user@contoso.com", delivery_mode="send")


def test_outlook_deployer_rejects_invalid_delivery_mode():
    deployer = OutlookDeployer(StubGraph(), _template())

    with pytest.raises(DeploymentError, match="Invalid delivery mode"):
        deployer.deploy("user@contoso.com", delivery_mode="invalid")


# --- New outlook coverage tests ---


def test_outlook_deployer_rejects_invalid_email():
    deployer = OutlookDeployer(StubGraph(), _template())

    with pytest.raises(DeploymentError, match="valid mailbox UPN"):
        deployer.deploy("not-an-email")


def test_outlook_deployer_raises_when_folder_id_missing():
    class NoFolderIdGraph:
        def post(self, path, json=None):
            return {}

    deployer = OutlookDeployer(NoFolderIdGraph(), _template())

    with pytest.raises(DeploymentError, match="missing folder id"):
        deployer.deploy("user@contoso.com")


def test_outlook_deployer_raises_when_message_id_missing():
    class NoMessageIdGraph:
        def __init__(self):
            self.call_count = 0

        def post(self, path, json=None):
            self.call_count += 1
            if self.call_count == 1:
                return {"id": "folder-1"}
            return {}

    deployer = OutlookDeployer(NoMessageIdGraph(), _template())

    with pytest.raises(DeploymentError, match="missing message id"):
        deployer.deploy("user@contoso.com")


def test_outlook_deployer_send_mode_wraps_graph_errors():
    class ErrorGraph:
        def post(self, path, json=None):
            raise GraphApiError("Denied", status_code=403)

    deployer = OutlookDeployer(ErrorGraph(), _template())

    with pytest.raises(DeploymentError, match="Outlook deployment failed"):
        deployer.deploy("user@contoso.com", delivery_mode="send")


def test_outlook_deployer_verify_retries_on_404_then_succeeds(monkeypatch: pytest.MonkeyPatch):
    graph = StubGraph()
    get_count = {"n": 0}
    original_get = graph.get

    def get_with_first_404(path, params=None):
        get_count["n"] += 1
        if get_count["n"] == 1:
            raise GraphApiError("Not Found", status_code=404)
        return original_get(path, params)

    graph.get = get_with_first_404
    monkeypatch.setattr("anglerfish.deployers.outlook.time.sleep", lambda *_: None)

    deployer = OutlookDeployer(graph, _template())
    result = deployer.deploy("user@contoso.com")

    assert result["verified"] == "true"


def test_outlook_deployer_raises_when_folder_id_mismatches(monkeypatch: pytest.MonkeyPatch):
    class WrongFolderIdGraph(StubGraph):
        def get(self, path, params=None):
            encoded_folder_id = quote(self.folder_id, safe="")
            if path.endswith(f"/mailFolders/{encoded_folder_id}"):
                return {"id": "wrong-id", "isHidden": True}
            return super().get(path, params)

    monkeypatch.setattr("anglerfish.deployers.outlook.time.sleep", lambda *_: None)
    deployer = OutlookDeployer(WrongFolderIdGraph(), _template())

    with pytest.raises(DeploymentError, match="created folder could not be confirmed"):
        deployer.deploy("user@contoso.com")


def test_outlook_deployer_raises_when_message_id_mismatches(monkeypatch: pytest.MonkeyPatch):
    class WrongMessageIdGraph(StubGraph):
        def get(self, path, params=None):
            encoded_folder_id = quote(self.folder_id, safe="")
            if path.endswith(f"/mailFolders/{encoded_folder_id}"):
                return {"id": self.folder_id, "isHidden": True}
            return {"id": "wrong-message-id"}

    monkeypatch.setattr("anglerfish.deployers.outlook.time.sleep", lambda *_: None)
    deployer = OutlookDeployer(WrongMessageIdGraph(), _template())

    with pytest.raises(DeploymentError, match="created message could not be confirmed"):
        deployer.deploy("user@contoso.com")


def test_outlook_deployer_raises_when_verify_exhausted(monkeypatch: pytest.MonkeyPatch):
    class Always404Graph(StubGraph):
        def get(self, path, params=None):
            raise GraphApiError("Not Found", status_code=404)

    monkeypatch.setattr("anglerfish.deployers.outlook.time.sleep", lambda *_: None)
    deployer = OutlookDeployer(Always404Graph(), _template())

    with pytest.raises(DeploymentError, match="Outlook verification failed"):
        deployer.deploy("user@contoso.com")


def test_outlook_deployer_send_verify_retries_on_404(monkeypatch: pytest.MonkeyPatch):
    call_count = {"n": 0}

    class RetryAfter404Graph:
        def post(self, path, json=None):
            return {}

        def get(self, path, params=None):
            call_count["n"] += 1
            if call_count["n"] == 1:
                raise GraphApiError("Not Found", status_code=404)
            timestamp = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
            return {
                "value": [
                    {"id": "msg-1", "subject": "Subject", "internetMessageId": "<x@y>", "receivedDateTime": timestamp}
                ]
            }

    monkeypatch.setattr("anglerfish.deployers.outlook.time.sleep", lambda *_: None)
    deployer = OutlookDeployer(RetryAfter404Graph(), _template())
    result = deployer.deploy("user@contoso.com", delivery_mode="send")

    assert result["inbox_message_id"] == "msg-1"


def test_outlook_deployer_send_verify_skips_non_dict_messages(monkeypatch: pytest.MonkeyPatch):
    call_count = {"n": 0}

    class NonDictMessageGraph:
        def post(self, path, json=None):
            return {}

        def get(self, path, params=None):
            call_count["n"] += 1
            if call_count["n"] <= 4:
                return {"value": ["not-a-dict", 42, None]}
            timestamp = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
            return {
                "value": [
                    {"id": "msg-ok", "subject": "Subject", "internetMessageId": "<ok@x>", "receivedDateTime": timestamp}
                ]
            }

    monkeypatch.setattr("anglerfish.deployers.outlook.time.sleep", lambda *_: None)
    deployer = OutlookDeployer(NonDictMessageGraph(), _template())
    result = deployer.deploy("user@contoso.com", delivery_mode="send")

    assert result["inbox_message_id"] == "msg-ok"


def test_outlook_deployer_send_verify_skips_wrong_subject(monkeypatch: pytest.MonkeyPatch):
    call_count = {"n": 0}

    class WrongSubjectGraph:
        def post(self, path, json=None):
            return {}

        def get(self, path, params=None):
            call_count["n"] += 1
            if call_count["n"] <= 4:
                timestamp = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
                return {"value": [{"id": "msg-bad", "subject": "Different Subject", "receivedDateTime": timestamp}]}
            timestamp = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
            return {
                "value": [
                    {"id": "msg-ok", "subject": "Subject", "internetMessageId": "<ok@x>", "receivedDateTime": timestamp}
                ]
            }

    monkeypatch.setattr("anglerfish.deployers.outlook.time.sleep", lambda *_: None)
    deployer = OutlookDeployer(WrongSubjectGraph(), _template())
    result = deployer.deploy("user@contoso.com", delivery_mode="send")

    assert result["inbox_message_id"] == "msg-ok"


def test_outlook_deployer_send_requires_internet_message_id(monkeypatch: pytest.MonkeyPatch):
    class MissingInternetMessageGraph:
        def post(self, path, json=None):
            return {}

        def get(self, path, params=None):
            timestamp = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
            return {"value": [{"id": "msg-no-imid", "subject": "Subject", "receivedDateTime": timestamp}]}

    monkeypatch.setattr("anglerfish.deployers.outlook.time.sleep", lambda *_: None)
    deployer = OutlookDeployer(MissingInternetMessageGraph(), _template())

    with pytest.raises(DeploymentError, match="internetMessageId"):
        deployer.deploy("user@contoso.com", delivery_mode="send")


def test_parse_graph_datetime_empty_string_returns_none():
    assert _parse_graph_datetime("") is None
    assert _parse_graph_datetime("   ") is None


def test_parse_graph_datetime_invalid_string_returns_none():
    assert _parse_graph_datetime("not-a-date") is None


def test_parse_graph_datetime_z_suffix_handled():
    result = _parse_graph_datetime("2026-02-19T12:00:00Z")
    assert result is not None
    assert result.tzinfo is not None


def test_parse_graph_datetime_no_timezone_gets_utc():
    result = _parse_graph_datetime("2026-02-19T12:00:00")
    assert result is not None
    assert result.tzinfo is not None


# ---------------------------------------------------------------------------
# remove_canary() tests
# ---------------------------------------------------------------------------


class _DelGraph:
    def __init__(self):
        self.delete_calls: list[str] = []

    def delete(self, path: str) -> None:
        self.delete_calls.append(path)


def test_outlook_remove_canary_draft_mode_deletes_folder():
    graph = _DelGraph()
    record = {
        "delivery_mode": "draft",
        "target_user": "user@contoso.com",
        "folder_id": "folder/123==",
    }
    result = remove_canary(graph, record)

    assert result["removed"] == "true"
    assert result["delivery_mode"] == "draft"
    assert result["folder_id"] == "folder/123=="
    encoded_user = _quote("user@contoso.com", safe="")
    encoded_folder = _quote("folder/123==", safe="")
    assert graph.delete_calls == [f"/users/{encoded_user}/mailFolders/{encoded_folder}"]


def test_outlook_remove_canary_send_mode_deletes_inbox_message():
    graph = _DelGraph()
    record = {
        "delivery_mode": "send",
        "target_user": "user@contoso.com",
        "inbox_message_id": "msg/456?abc",
    }
    result = remove_canary(graph, record)

    assert result["removed"] == "true"
    assert result["delivery_mode"] == "send"
    assert result["inbox_message_id"] == "msg/456?abc"
    assert "note" in result
    encoded_user = _quote("user@contoso.com", safe="")
    encoded_msg = _quote("msg/456?abc", safe="")
    assert graph.delete_calls == [f"/users/{encoded_user}/mailFolders/inbox/messages/{encoded_msg}"]


def test_outlook_remove_canary_raises_when_target_user_missing():
    with pytest.raises(DeploymentError, match="missing 'target_user'"):
        remove_canary(_DelGraph(), {"delivery_mode": "draft", "folder_id": "f1"})


def test_outlook_remove_canary_raises_when_folder_id_missing():
    with pytest.raises(DeploymentError, match="missing 'folder_id'"):
        remove_canary(_DelGraph(), {"delivery_mode": "draft", "target_user": "u@c.com"})


def test_outlook_remove_canary_raises_when_inbox_message_id_missing():
    with pytest.raises(DeploymentError, match="missing 'inbox_message_id'"):
        remove_canary(_DelGraph(), {"delivery_mode": "send", "target_user": "u@c.com"})


def test_outlook_remove_canary_draft_wraps_graph_error():
    class ErrorGraph:
        def delete(self, path: str) -> None:
            raise GraphApiError("Denied", status_code=403)

    with pytest.raises(DeploymentError, match="Outlook cleanup failed"):
        remove_canary(
            ErrorGraph(),
            {"delivery_mode": "draft", "target_user": "u@c.com", "folder_id": "f1"},
        )


def test_outlook_remove_canary_send_wraps_graph_error():
    class ErrorGraph:
        def delete(self, path: str) -> None:
            raise GraphApiError("Not Found", status_code=404)

    with pytest.raises(DeploymentError, match="Outlook cleanup failed"):
        remove_canary(
            ErrorGraph(),
            {"delivery_mode": "send", "target_user": "u@c.com", "inbox_message_id": "m1"},
        )


def test_outlook_remove_canary_defaults_to_draft_when_delivery_mode_absent():
    graph = _DelGraph()
    record = {
        "target_user": "user@contoso.com",
        "folder_id": "f-abc",
    }
    result = remove_canary(graph, record)
    assert result["delivery_mode"] == "draft"
    assert result["removed"] == "true"


class _GetGraph:
    def __init__(self):
        self.get_calls: list[tuple[str, dict | None]] = []

    def get(self, path: str, params=None):
        self.get_calls.append((path, params))
        return {
            "id": "msg/456?abc",
            "subject": "Subject",
            "internetMessageId": "<canary-msg@contoso.com>",
        }


def test_trigger_canary_access_reads_draft_message():
    graph = _GetGraph()
    record = {
        "canary_type": "outlook",
        "delivery_mode": "draft",
        "target_user": "user@contoso.com",
        "folder_id": "folder/123==",
        "message_id": "msg/456?abc",
    }

    result = trigger_canary_access(graph, record)

    encoded_user = _quote("user@contoso.com", safe="")
    encoded_folder = _quote("folder/123==", safe="")
    encoded_message = _quote("msg/456?abc", safe="")
    assert graph.get_calls == [
        (
            f"/users/{encoded_user}/mailFolders/{encoded_folder}/messages/{encoded_message}",
            {"$select": "id,subject,internetMessageId,receivedDateTime"},
        )
    ]
    assert result["triggered"] == "true"
    assert result["delivery_mode"] == "draft"
    assert result["internet_message_id"] == "<canary-msg@contoso.com>"


def test_trigger_canary_access_reads_send_message_from_inbox():
    graph = _GetGraph()
    record = {
        "canary_type": "outlook",
        "delivery_mode": "send",
        "target_user": "user@contoso.com",
        "inbox_message_id": "msg/456?abc",
    }

    result = trigger_canary_access(graph, record)

    encoded_user = _quote("user@contoso.com", safe="")
    encoded_message = _quote("msg/456?abc", safe="")
    assert graph.get_calls[0][0] == f"/users/{encoded_user}/mailFolders/inbox/messages/{encoded_message}"
    assert result["triggered"] == "true"
    assert result["delivery_mode"] == "send"


def test_trigger_canary_access_rejects_missing_draft_fields():
    with pytest.raises(DeploymentError, match="message_id"):
        trigger_canary_access(
            _GetGraph(),
            {"canary_type": "outlook", "delivery_mode": "draft", "target_user": "u@c.com", "folder_id": "f1"},
        )
