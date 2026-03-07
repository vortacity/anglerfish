from __future__ import annotations

from urllib.parse import quote, unquote

import pytest

from anglerfish.deployers.onedrive import OneDriveDeployer, remove_canary
from anglerfish.exceptions import DeploymentError, GraphApiError
from anglerfish.models import OneDriveTemplate


def _template() -> OneDriveTemplate:
    return OneDriveTemplate(
        name="OneDrive Test",
        description="Test template",
        folder_path="IT/Backups",
        filenames=["vpn_config.txt"],
        content_text="Canary file: ${filename}",
        variables=[],
    )


class StubGraph:
    def __init__(self):
        self.get_calls = []
        self.put_calls = []
        self.upn = "j.smith@contoso.com"
        self.encoded_upn = quote(self.upn, safe="")
        self.items_by_id: dict[str, dict[str, str]] = {}

    def get(self, path, params=None):
        self.get_calls.append((path, params))
        if path.startswith(f"/users/{self.encoded_upn}/drive/items/"):
            item_id = unquote(path.rsplit("/", maxsplit=1)[-1])
            return self.items_by_id[item_id]
        raise AssertionError(f"Unexpected GET path: {path}")

    def put(self, path, data=None, content_type=None):
        self.put_calls.append((path, data, content_type))
        if not path.startswith(f"/users/{self.encoded_upn}/drive/root:/"):
            raise AssertionError(f"Unexpected PUT path: {path}")

        raw_drive_path = path.split("/drive/root:/", maxsplit=1)[1].rsplit(":/content", maxsplit=1)[0]
        filename = unquote(raw_drive_path.rsplit("/", maxsplit=1)[-1])
        item_id = f"item-{len(self.put_calls)}"
        self.items_by_id[item_id] = {
            "id": item_id,
            "name": filename,
            "webUrl": f"https://contoso-my.sharepoint.com/personal/item/{item_id}",
        }
        return {"id": item_id}


def test_onedrive_deployer_happy_path_uploads_and_verifies_files():
    graph = StubGraph()
    deployer = OneDriveDeployer(graph, _template())

    result = deployer.deploy("j.smith@contoso.com")

    assert result["type"] == "onedrive"
    assert result["target_user"] == "j.smith@contoso.com"
    assert result["uploaded_count"] == "1"
    assert "vpn_config.txt" in result["uploaded_files"]
    assert result["verified"] == "true"
    assert len(graph.put_calls) == 1
    assert graph.put_calls[0][0] == f"/users/{graph.encoded_upn}/drive/root:/IT/Backups/vpn_config.txt:/content"
    assert graph.put_calls[0][2] == "text/plain; charset=utf-8"
    assert b"Canary file: vpn_config.txt" == graph.put_calls[0][1]


def test_onedrive_deployer_folder_path_no_library_prefix_stripping():
    """OneDrive does not strip 'Shared Documents/' prefix — unlike SharePoint."""
    graph = StubGraph()
    deployer = OneDriveDeployer(graph, _template())

    deployer.deploy("j.smith@contoso.com", folder_path="Shared Documents/Backups")

    # "Shared Documents" should NOT be stripped for OneDrive.
    assert "Shared%20Documents/Backups/vpn_config.txt" in graph.put_calls[0][0]


def test_onedrive_deployer_wraps_graph_errors():
    class ErrorGraph:
        def get(self, path, params=None):
            raise GraphApiError("Denied", status_code=403)

        def put(self, path, data=None, content_type=None):
            raise GraphApiError("Denied", status_code=403)

    deployer = OneDriveDeployer(ErrorGraph(), _template())

    with pytest.raises(DeploymentError, match="OneDrive deployment failed"):
        deployer.deploy("j.smith@contoso.com")


def test_onedrive_deployer_rejects_invalid_target_missing_at():
    deployer = OneDriveDeployer(StubGraph(), _template())

    with pytest.raises(DeploymentError, match="UPN or email"):
        deployer.deploy("not-an-email")


def test_onedrive_deployer_rejects_empty_target():
    deployer = OneDriveDeployer(StubGraph(), _template())

    with pytest.raises(DeploymentError, match="UPN or email"):
        deployer.deploy("")


def test_onedrive_deployer_rejects_invalid_filenames():
    deployer = OneDriveDeployer(StubGraph(), _template())

    with pytest.raises(DeploymentError, match="must not contain path separators"):
        deployer.deploy("j.smith@contoso.com", filenames=["bad/path.txt"])


def test_onedrive_deployer_rejects_multiple_filenames():
    deployer = OneDriveDeployer(StubGraph(), _template())

    with pytest.raises(DeploymentError, match="supports exactly one filename"):
        deployer.deploy("j.smith@contoso.com", filenames=["file1.txt", "file2.txt"])


def test_onedrive_deployer_raises_when_put_response_missing_id():
    class NoItemIdGraph(StubGraph):
        def put(self, path, data=None, content_type=None):
            self.put_calls.append((path, data, content_type))
            return {}

    deployer = OneDriveDeployer(NoItemIdGraph(), _template())

    with pytest.raises(DeploymentError, match="missing file id"):
        deployer.deploy("j.smith@contoso.com")


def test_onedrive_deployer_raises_when_rendered_content_empty():
    template = OneDriveTemplate(
        name="Test",
        description="Test",
        folder_path="IT/Backups",
        filenames=["file.txt"],
        content_text="   ",
        variables=[],
    )
    deployer = OneDriveDeployer(StubGraph(), template)

    with pytest.raises(DeploymentError, match="file content is empty"):
        deployer.deploy("j.smith@contoso.com")


def test_onedrive_deployer_verify_retries_on_404_then_succeeds(monkeypatch: pytest.MonkeyPatch):
    graph = StubGraph()
    get_count = {"n": 0}
    original_get = graph.get

    def get_with_404(path, params=None):
        if "/drive/items/" in path:
            get_count["n"] += 1
            if get_count["n"] == 1:
                raise GraphApiError("Not Found", status_code=404)
        return original_get(path, params)

    graph.get = get_with_404
    monkeypatch.setattr("anglerfish.deployers.onedrive.time.sleep", lambda *_: None)

    deployer = OneDriveDeployer(graph, _template())
    result = deployer.deploy("j.smith@contoso.com")

    assert result["verified"] == "true"


def test_onedrive_deployer_raises_when_item_id_mismatch():
    class WrongIdGraph(StubGraph):
        def get(self, path, params=None):
            if "/drive/items/" in path:
                return {"id": "wrong-id", "name": "vpn_config.txt"}
            return super().get(path, params)

    deployer = OneDriveDeployer(WrongIdGraph(), _template())

    with pytest.raises(DeploymentError, match="id mismatch"):
        deployer.deploy("j.smith@contoso.com")


def test_onedrive_deployer_raises_when_item_name_mismatch():
    class WrongNameGraph(StubGraph):
        def get(self, path, params=None):
            if "/drive/items/" in path:
                raw_item_id = unquote(path.rsplit("/", 1)[-1])
                return {"id": raw_item_id, "name": "wrong_name.txt"}
            return super().get(path, params)

    deployer = OneDriveDeployer(WrongNameGraph(), _template())

    with pytest.raises(DeploymentError, match="name mismatch"):
        deployer.deploy("j.smith@contoso.com")


def test_onedrive_deployer_raises_when_filenames_not_a_list():
    deployer = OneDriveDeployer(StubGraph(), _template())

    with pytest.raises(DeploymentError, match="must be provided as a list"):
        deployer.deploy("j.smith@contoso.com", filenames="vpn_config.txt")


def test_onedrive_deployer_raises_when_filename_is_empty_string():
    deployer = OneDriveDeployer(StubGraph(), _template())

    with pytest.raises(DeploymentError, match="cannot be empty"):
        deployer.deploy("j.smith@contoso.com", filenames=[""])


def test_onedrive_deployer_raises_when_filenames_list_is_empty():
    deployer = OneDriveDeployer(StubGraph(), _template())

    with pytest.raises(DeploymentError, match="At least one"):
        deployer.deploy("j.smith@contoso.com", filenames=[])


def test_onedrive_deployer_docx_filename_triggers_docx_content_type():
    graph = StubGraph()
    template = OneDriveTemplate(
        name="Test",
        description="Test",
        folder_path="HR/Reviews",
        filenames=["Review_Notes.docx"],
        content_text="Performance review content",
        variables=[],
    )
    deployer = OneDriveDeployer(graph, template)

    deployer.deploy("j.smith@contoso.com")

    assert graph.put_calls[0][2] == "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


def test_onedrive_deployer_xlsx_filename_triggers_xlsx_content_type():
    graph = StubGraph()
    template = OneDriveTemplate(
        name="Test",
        description="Test",
        folder_path="Financial/Investments",
        filenames=["Portfolio.xlsx"],
        content_text="Header\nRow 1\nRow 2",
        variables=[],
    )
    deployer = OneDriveDeployer(graph, template)

    deployer.deploy("j.smith@contoso.com")

    assert graph.put_calls[0][2] == "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def test_onedrive_deployer_txt_filename_still_uses_text_plain():
    graph = StubGraph()
    deployer = OneDriveDeployer(graph, _template())

    deployer.deploy("j.smith@contoso.com")

    assert graph.put_calls[0][2] == "text/plain; charset=utf-8"


def test_onedrive_deployer_allows_empty_folder_path():
    """OneDrive allows empty folder_path (file in drive root)."""
    graph = StubGraph()
    deployer = OneDriveDeployer(graph, _template())

    result = deployer.deploy("j.smith@contoso.com", folder_path="")

    assert result["folder_path"] == ""
    # PUT path should just be the filename, no leading folder segments
    assert "/drive/root:/vpn_config.txt:/content" in graph.put_calls[0][0]


def test_onedrive_deployer_deploy_includes_item_id():
    graph = StubGraph()
    deployer = OneDriveDeployer(graph, _template())

    result = deployer.deploy("j.smith@contoso.com")

    assert "item_id" in result
    assert result["item_id"]  # non-empty


# ---------------------------------------------------------------------------
# Path traversal protection tests
# ---------------------------------------------------------------------------


class TestNormalizeFolderPathTraversalProtection:
    """_normalize_folder_path() must reject path traversal attempts."""

    def _call(self, path: str) -> str:
        from anglerfish.deployers.onedrive import _normalize_folder_path

        return _normalize_folder_path(path)

    def test_rejects_dotdot_segment(self):
        with pytest.raises(DeploymentError, match="path traversal"):
            self._call("../../../etc")

    def test_rejects_dotdot_segment_windows_style(self):
        with pytest.raises(DeploymentError, match="path traversal"):
            self._call("..\\..\\secret")

    def test_rejects_single_dot_segment(self):
        with pytest.raises(DeploymentError, match="path traversal"):
            self._call("HR/./Restricted")

    def test_rejects_percent_encoded_slash(self):
        with pytest.raises(DeploymentError, match="percent-encoded traversal"):
            self._call("normal%2f..%2fpath")

    def test_rejects_percent_encoded_backslash(self):
        with pytest.raises(DeploymentError, match="percent-encoded traversal"):
            self._call("Finance%5cConfidential")

    def test_rejects_percent_encoded_dot_dot(self):
        with pytest.raises(DeploymentError, match="percent-encoded traversal"):
            self._call("HR/%2e%2e/Restricted")

    def test_rejects_null_byte(self):
        with pytest.raises(DeploymentError, match="null bytes"):
            self._call("HR/\x00/Restricted")

    def test_rejects_percent_encoded_null_byte(self):
        with pytest.raises(DeploymentError, match="null bytes"):
            self._call("HR/%00/Restricted")

    def test_allows_normal_path(self):
        result = self._call("HR/Restricted")
        assert result == "HR/Restricted"

    def test_allows_path_with_dots_in_name(self):
        result = self._call("Finance/Q1.Reports")
        assert result == "Finance/Q1.Reports"

    def test_allows_empty_path(self):
        result = self._call("")
        assert result == ""

    def test_does_not_strip_shared_documents_prefix(self):
        """OneDrive does not strip library prefixes."""
        result = self._call("Shared Documents/HR/Restricted")
        assert result == "Shared Documents/HR/Restricted"


# ---------------------------------------------------------------------------
# remove_canary() tests
# ---------------------------------------------------------------------------


class _DelGraph:
    def __init__(self):
        self.delete_calls: list[str] = []

    def delete(self, path: str) -> None:
        self.delete_calls.append(path)


def test_onedrive_remove_canary_happy_path():
    graph = _DelGraph()
    record = {"target_user": "j.smith@contoso.com", "item_id": "item-1"}

    result = remove_canary(graph, record)

    assert result["removed"] == "true"
    assert result["target_user"] == "j.smith@contoso.com"
    assert result["item_id"] == "item-1"
    encoded_upn = quote("j.smith@contoso.com", safe="")
    encoded_item = quote("item-1", safe="")
    assert graph.delete_calls == [f"/users/{encoded_upn}/drive/items/{encoded_item}"]


def test_onedrive_remove_canary_raises_when_target_user_missing():
    with pytest.raises(DeploymentError, match="missing 'target_user'"):
        remove_canary(_DelGraph(), {"item_id": "item-1"})


def test_onedrive_remove_canary_raises_when_item_id_missing():
    with pytest.raises(DeploymentError, match="missing 'item_id'"):
        remove_canary(_DelGraph(), {"target_user": "j.smith@contoso.com"})


def test_onedrive_remove_canary_delete_wraps_graph_error():
    class ErrorGraph:
        def delete(self, path: str) -> None:
            raise GraphApiError("Denied", status_code=403)

    with pytest.raises(DeploymentError, match="OneDrive cleanup failed"):
        remove_canary(ErrorGraph(), {"target_user": "j.smith@contoso.com", "item_id": "i1"})
