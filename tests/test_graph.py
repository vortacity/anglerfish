from __future__ import annotations

from typing import Any
from unittest.mock import Mock

import pytest
import requests

from anglerfish.exceptions import GraphApiError
from anglerfish.graph import GraphClient


class FakeResponse:
    def __init__(
        self,
        *,
        status_code: int,
        payload: Any | None = None,
        text: str = "",
        headers: dict[str, str] | None = None,
    ):
        self.status_code = status_code
        self._payload = payload
        self.text = text
        self.headers = headers or {}

    @property
    def ok(self) -> bool:
        return 200 <= self.status_code < 300

    @property
    def content(self) -> bytes:
        if self._payload is None:
            return b""
        return b"{}"

    def json(self) -> Any:
        if self._payload is None:
            raise ValueError("No JSON")
        return self._payload


def test_graph_get_success_returns_json_dict():
    session = requests.Session()
    session.request = Mock(return_value=FakeResponse(status_code=200, payload={"id": "123"}))

    client = GraphClient("token", session=session)
    result = client.get("/me")

    assert result["id"] == "123"


def test_graph_client_retries_on_429(monkeypatch: pytest.MonkeyPatch):
    responses = [
        FakeResponse(
            status_code=429,
            payload={"error": {"code": "TooManyRequests", "message": "slow down"}},
            headers={"Retry-After": "1"},
        ),
        FakeResponse(status_code=200, payload={"ok": True}),
    ]

    session = requests.Session()

    def fake_request(*args, **kwargs):
        return responses.pop(0)

    session.request = Mock(side_effect=fake_request)
    sleep_calls: list[int] = []
    monkeypatch.setattr("anglerfish.graph.time.sleep", lambda value: sleep_calls.append(value))

    client = GraphClient("token", session=session)
    result = client.get("/me")

    assert result == {"ok": True}
    assert sleep_calls == [1]


def test_graph_client_raises_on_error_response():
    session = requests.Session()
    session.request = Mock(
        return_value=FakeResponse(
            status_code=403,
            payload={"error": {"code": "ErrorAccessDenied", "message": "Denied"}},
        )
    )

    client = GraphClient("token", session=session)

    with pytest.raises(GraphApiError, match="ErrorAccessDenied"):
        client.get("/me")


def test_graph_client_captures_request_context_on_error_response():
    session = requests.Session()
    session.request = Mock(
        return_value=FakeResponse(
            status_code=403,
            payload={
                "error": {
                    "code": "Forbidden",
                    "message": "InsufficientPrivileges",
                    "innerError": {
                        "request-id": "inner-req-id",
                        "client-request-id": "inner-client-id",
                    },
                }
            },
            headers={"request-id": "header-req-id"},
        )
    )

    client = GraphClient("token", session=session)

    with pytest.raises(GraphApiError) as exc_info:
        client.post("/users/abc/mailFolders/def/messages", json={"body": {"content": "test"}})

    exc = exc_info.value
    assert exc.status_code == 403
    assert exc.method == "POST"
    assert exc.path == "/users/abc/mailFolders/def/messages"
    assert exc.request_id == "header-req-id"
    assert exc.client_request_id == "inner-client-id"


def test_graph_client_retries_on_5xx(monkeypatch: pytest.MonkeyPatch):
    responses = [
        FakeResponse(status_code=503, payload={"error": {"code": "ServiceUnavailable", "message": "try later"}}),
        FakeResponse(status_code=200, payload={"ok": True}),
    ]
    session = requests.Session()
    session.request = Mock(side_effect=lambda *args, **kwargs: responses.pop(0))
    sleep_calls: list[int] = []
    monkeypatch.setattr("anglerfish.graph.time.sleep", lambda value: sleep_calls.append(value))

    client = GraphClient("token", session=session)
    result = client.get("/me")

    assert result == {"ok": True}
    assert sleep_calls == [1]


def test_graph_client_post_does_not_retry_on_5xx(monkeypatch: pytest.MonkeyPatch):
    responses = [
        FakeResponse(status_code=503, payload={"error": {"code": "ServiceUnavailable", "message": "try later"}}),
        FakeResponse(status_code=200, payload={"ok": True}),
    ]
    session = requests.Session()
    session.request = Mock(side_effect=lambda *args, **kwargs: responses.pop(0))
    monkeypatch.setattr("anglerfish.graph.time.sleep", lambda *_: None)

    client = GraphClient("token", session=session, retries=3)

    with pytest.raises(GraphApiError, match="ServiceUnavailable"):
        client.post("/me/sendMail", json={"message": {}})

    assert session.request.call_count == 1


def test_graph_client_post_retry_safe_retries_on_5xx(monkeypatch: pytest.MonkeyPatch):
    responses = [
        FakeResponse(status_code=503, payload={"error": {"code": "ServiceUnavailable", "message": "try later"}}),
        FakeResponse(status_code=200, payload={"ok": True}),
    ]
    session = requests.Session()
    session.request = Mock(side_effect=lambda *args, **kwargs: responses.pop(0))
    sleep_calls: list[int] = []
    monkeypatch.setattr("anglerfish.graph.time.sleep", lambda value: sleep_calls.append(value))

    client = GraphClient("token", session=session, retries=3)
    result = client.post("/me/sendMail", json={"message": {}}, retry_safe=True)

    assert result == {"ok": True}
    assert session.request.call_count == 2
    assert sleep_calls == [1]


def test_graph_client_post_does_not_retry_on_429(monkeypatch: pytest.MonkeyPatch):
    responses = [
        FakeResponse(
            status_code=429,
            payload={"error": {"code": "TooManyRequests", "message": "slow down"}},
            headers={"Retry-After": "1"},
        ),
        FakeResponse(status_code=200, payload={"ok": True}),
    ]
    session = requests.Session()
    session.request = Mock(side_effect=lambda *args, **kwargs: responses.pop(0))
    monkeypatch.setattr("anglerfish.graph.time.sleep", lambda *_: None)

    client = GraphClient("token", session=session, retries=3)

    with pytest.raises(GraphApiError, match="TooManyRequests"):
        client.post("/me/sendMail", json={"message": {}})

    assert session.request.call_count == 1


def test_graph_client_retries_on_request_exception(monkeypatch: pytest.MonkeyPatch):
    session = requests.Session()
    session.request = Mock(
        side_effect=[
            requests.exceptions.Timeout("timed out"),
            FakeResponse(status_code=200, payload={"ok": True}),
        ]
    )
    sleep_calls: list[int] = []
    monkeypatch.setattr("anglerfish.graph.time.sleep", lambda value: sleep_calls.append(value))

    client = GraphClient("token", session=session)
    result = client.get("/me")

    assert result == {"ok": True}
    assert sleep_calls == [1]


def test_graph_client_put_does_not_retry_on_request_exception(monkeypatch: pytest.MonkeyPatch):
    session = requests.Session()
    session.request = Mock(
        side_effect=[
            requests.exceptions.Timeout("timed out"),
            FakeResponse(status_code=200, payload={"ok": True}),
        ]
    )
    monkeypatch.setattr("anglerfish.graph.time.sleep", lambda *_: None)

    client = GraphClient("token", session=session, retries=3)

    with pytest.raises(GraphApiError, match="Network error while calling Graph API"):
        client.put("/sites/abc/drive/root:/file.txt:/content", data=b"content")

    assert session.request.call_count == 1


def test_graph_client_raises_graph_api_error_on_request_exception(monkeypatch: pytest.MonkeyPatch):
    session = requests.Session()
    session.request = Mock(side_effect=requests.exceptions.ConnectionError("no route"))
    monkeypatch.setattr("anglerfish.graph.time.sleep", lambda *_: None)

    client = GraphClient("token", session=session, retries=2)

    with pytest.raises(GraphApiError, match="Network error while calling Graph API"):
        client.get("/me")


def test_graph_client_delete_retries_on_5xx(monkeypatch: pytest.MonkeyPatch):
    responses = [
        FakeResponse(status_code=503, payload={"error": {"code": "ServiceUnavailable", "message": "try later"}}),
        FakeResponse(status_code=204, payload=None),
    ]
    session = requests.Session()
    session.request = Mock(side_effect=lambda *args, **kwargs: responses.pop(0))
    sleep_calls: list[int] = []
    monkeypatch.setattr("anglerfish.graph.time.sleep", lambda value: sleep_calls.append(value))

    client = GraphClient("token", session=session, retries=3)
    client.delete("/sites/site-id/drive/items/item-id")

    assert session.request.call_count == 2
    assert sleep_calls == [1]


# --- New graph coverage tests ---


def test_graph_client_put_calls_request_with_data():
    session = requests.Session()
    session.request = Mock(return_value=FakeResponse(status_code=200, payload={"id": "item-1"}))

    client = GraphClient("token", session=session)
    result = client.put("/sites/abc/drive/root:/file.txt:/content", data=b"content", content_type="text/plain")

    assert result["id"] == "item-1"
    call_kwargs = session.request.call_args
    assert call_kwargs[1].get("headers", {}).get("Content-Type") == "text/plain"
    assert call_kwargs[1].get("data") == b"content"


def test_graph_client_raises_after_all_429_retries_exhausted(monkeypatch: pytest.MonkeyPatch):
    session = requests.Session()
    session.request = Mock(
        return_value=FakeResponse(
            status_code=429,
            payload={"error": {"code": "TooManyRequests", "message": "slow down"}},
            headers={"Retry-After": "1"},
        )
    )
    monkeypatch.setattr("anglerfish.graph.time.sleep", lambda *_: None)

    client = GraphClient("token", session=session, retries=2)

    with pytest.raises(GraphApiError):
        client.get("/me")


def test_graph_client_response_204_returns_empty_dict():
    session = requests.Session()
    response = FakeResponse(status_code=204, payload=None)
    session.request = Mock(return_value=response)

    client = GraphClient("token", session=session)
    result = client.post("/some/path", json={})

    assert result == {}


def test_graph_client_non_json_success_returns_empty_dict():
    class NonJsonResponse(FakeResponse):
        @property
        def content(self) -> bytes:
            return b"plain text"

        def json(self):
            raise ValueError("not JSON")

    session = requests.Session()
    session.request = Mock(return_value=NonJsonResponse(status_code=200, payload=None, text="plain text"))

    client = GraphClient("token", session=session)
    result = client.get("/me")

    assert result == {}


def test_graph_client_list_json_response_wrapped_in_value():
    class ListResponse(FakeResponse):
        @property
        def content(self) -> bytes:
            return b"[1,2,3]"

        def json(self):
            return [1, 2, 3]

    session = requests.Session()
    session.request = Mock(return_value=ListResponse(status_code=200, payload=None))

    client = GraphClient("token", session=session)
    result = client.get("/me")

    assert result == {"value": [1, 2, 3]}


def test_graph_client_non_json_error_body_uses_text():
    class TextErrorResponse(FakeResponse):
        def json(self):
            raise ValueError("not JSON")

    session = requests.Session()
    session.request = Mock(return_value=TextErrorResponse(status_code=500, payload=None, text="Internal Server Error"))
    client = GraphClient("token", session=session, retries=1)

    with pytest.raises(GraphApiError) as exc_info:
        client.get("/me")

    assert "Internal Server Error" in str(exc_info.value)


def test_graph_client_non_dict_error_payload_uses_text():
    class ListPayloadResponse(FakeResponse):
        @property
        def content(self) -> bytes:
            return b'["not","a","dict"]'

        @property
        def ok(self) -> bool:
            return False

        def json(self):
            return ["not", "a", "dict"]

    session = requests.Session()
    session.request = Mock(return_value=ListPayloadResponse(status_code=400, payload=None, text='["not","a","dict"]'))

    client = GraphClient("token", session=session, retries=1)

    with pytest.raises(GraphApiError):
        client.get("/me")


def test_parse_retry_after_returns_1_for_none():
    from anglerfish.graph import _parse_retry_after

    assert _parse_retry_after(None) == 1


def test_parse_retry_after_parses_integer_string():
    from anglerfish.graph import _parse_retry_after

    assert _parse_retry_after("5") == 5


def test_parse_retry_after_parses_http_date():
    from anglerfish.graph import _parse_retry_after
    from datetime import datetime, timedelta, timezone

    future = datetime.now(timezone.utc) + timedelta(seconds=10)
    http_date = future.strftime("%a, %d %b %Y %H:%M:%S GMT")
    result = _parse_retry_after(http_date)
    assert result >= 1


def test_parse_retry_after_returns_1_for_invalid_string():
    from anglerfish.graph import _parse_retry_after

    assert _parse_retry_after("not-a-number-or-date") == 1
