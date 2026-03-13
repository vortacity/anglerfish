from __future__ import annotations

from urllib.parse import quote, unquote

import pytest

from anglerfish.deployers.sharepoint import SharePointDeployer, remove_canary
from anglerfish.exceptions import DeploymentError, GraphApiError
from anglerfish.models import SharePointTemplate


def _template() -> SharePointTemplate:
    return SharePointTemplate(
        name="SharePoint Test",
        description="Test template",
        site_name="Finance",
        folder_path="Shared Documents/Canary",
        filenames=["bonus_plan.txt"],
        content_text="Canary file: ${filename}",
        variables=[],
    )


class StubGraph:
    def __init__(self):
        self.get_calls = []
        self.put_calls = []
        self.site_id = "contoso.sharepoint.com,abc123,def456"
        self.encoded_site_id = quote(self.site_id, safe="")
        self.items_by_id: dict[str, dict[str, str]] = {}

    def get(self, path, params=None):
        self.get_calls.append((path, params))
        if path == "/sites":
            return {
                "value": [
                    {
                        "id": self.site_id,
                        "displayName": "Finance",
                        "name": "Finance",
                        "webUrl": "https://contoso.sharepoint.com/sites/Finance",
                    }
                ]
            }
        if path == f"/sites/{self.encoded_site_id}":
            return {
                "id": self.site_id,
                "displayName": "Finance",
                "name": "Finance",
                "webUrl": "https://contoso.sharepoint.com/sites/Finance",
            }
        if path == f"/sites/{self.encoded_site_id}/drive":
            return {"id": "drive-id", "name": "Documents"}
        if path.startswith(f"/sites/{self.encoded_site_id}/drive/items/"):
            item_id = unquote(path.rsplit("/", maxsplit=1)[-1])
            return self.items_by_id[item_id]
        raise AssertionError(f"Unexpected GET path: {path}")

    def put(self, path, data=None, content_type=None):
        self.put_calls.append((path, data, content_type))
        if not path.startswith(f"/sites/{self.encoded_site_id}/drive/root:/"):
            raise AssertionError(f"Unexpected PUT path: {path}")

        raw_drive_path = path.split("/drive/root:/", maxsplit=1)[1].rsplit(":/content", maxsplit=1)[0]
        filename = unquote(raw_drive_path.rsplit("/", maxsplit=1)[-1])
        item_id = f"item-{len(self.put_calls)}"
        self.items_by_id[item_id] = {
            "id": item_id,
            "name": filename,
            "webUrl": f"https://contoso.sharepoint.com/item/{item_id}",
        }
        return {"id": item_id}


def test_sharepoint_deployer_happy_path_uploads_and_verifies_files():
    graph = StubGraph()
    deployer = SharePointDeployer(graph, _template())

    result = deployer.deploy("Finance")

    assert result["type"] == "sharepoint"
    assert result["site_name"] == "Finance"
    assert result["uploaded_count"] == "1"
    assert "bonus_plan.txt" in result["uploaded_files"]
    assert result["verified"] == "true"
    assert len(graph.put_calls) == 1
    assert graph.put_calls[0][0] == f"/sites/{graph.encoded_site_id}/drive/root:/Canary/bonus_plan.txt:/content"
    assert graph.put_calls[0][2] == "text/plain; charset=utf-8"
    assert b"Canary file: bonus_plan.txt" == graph.put_calls[0][1]


def test_sharepoint_deployer_normalizes_documents_prefix_in_folder_path():
    graph = StubGraph()
    deployer = SharePointDeployer(graph, _template())

    deployer.deploy("Finance", folder_path="Documents/HR/Restricted")

    assert graph.put_calls[0][0] == f"/sites/{graph.encoded_site_id}/drive/root:/HR/Restricted/bonus_plan.txt:/content"


def test_sharepoint_deployer_wraps_graph_errors():
    class ErrorGraph:
        def get(self, path, params=None):
            raise GraphApiError("Denied", status_code=403)

    deployer = SharePointDeployer(ErrorGraph(), _template())

    with pytest.raises(DeploymentError, match="SharePoint deployment failed"):
        deployer.deploy("Finance")


def test_sharepoint_deployer_requires_unambiguous_site_match():
    class AmbiguousGraph(StubGraph):
        def get(self, path, params=None):
            if path == "/sites":
                return {
                    "value": [
                        {
                            "id": "contoso.sharepoint.com,site-a,123",
                            "displayName": "Finance Operations",
                            "name": "finance-operations",
                        },
                        {
                            "id": "contoso.sharepoint.com,site-b,456",
                            "displayName": "Finance Projects",
                            "name": "finance-projects",
                        },
                    ]
                }
            return super().get(path, params)

    deployer = SharePointDeployer(AmbiguousGraph(), _template())

    with pytest.raises(DeploymentError, match="returned multiple results"):
        deployer.deploy("Finance")


def test_sharepoint_deployer_prefers_exact_site_name_match_when_many_results():
    class MultiResultGraph(StubGraph):
        def get(self, path, params=None):
            if path == "/sites":
                return {
                    "value": [
                        {
                            "id": "contoso.sharepoint.com,site-a,123",
                            "displayName": "Finance Operations",
                            "name": "finance-operations",
                        },
                        {
                            "id": self.site_id,
                            "displayName": "Finance",
                            "name": "Finance",
                            "webUrl": "https://contoso.sharepoint.com/sites/Finance",
                        },
                    ]
                }
            return super().get(path, params)

    graph = MultiResultGraph()
    deployer = SharePointDeployer(graph, _template())

    result = deployer.deploy("Finance")

    assert result["site_id"] == graph.site_id


def test_sharepoint_deployer_rejects_invalid_filenames():
    deployer = SharePointDeployer(StubGraph(), _template())

    with pytest.raises(DeploymentError, match="must not contain path separators"):
        deployer.deploy("Finance", filenames=["bad/path.txt"])


def test_sharepoint_deployer_rejects_multiple_filenames():
    deployer = SharePointDeployer(StubGraph(), _template())

    with pytest.raises(DeploymentError, match="supports exactly one filename"):
        deployer.deploy("Finance", filenames=["bonus_plan.txt", "salary_map.txt"])


def test_sharepoint_deployer_can_resolve_site_by_site_id():
    graph = StubGraph()
    deployer = SharePointDeployer(graph, _template())

    result = deployer.deploy("Finance", site_id=graph.site_id)

    assert result["site_id"] == graph.site_id
    assert graph.get_calls[0][0] == f"/sites/{graph.encoded_site_id}"
    assert not any(path == "/sites" for path, _ in graph.get_calls)


# --- New sharepoint coverage tests ---


def test_sharepoint_deployer_raises_when_site_name_empty():
    deployer = SharePointDeployer(StubGraph(), _template())

    with pytest.raises(DeploymentError, match="site name is required"):
        deployer.deploy("")


def test_sharepoint_deployer_raises_when_folder_path_normalizes_to_empty():
    deployer = SharePointDeployer(StubGraph(), _template())

    with pytest.raises(DeploymentError, match="folder path is required"):
        deployer.deploy("Finance", folder_path="Shared Documents")


def test_sharepoint_deployer_raises_when_put_response_missing_id():
    class NoItemIdGraph(StubGraph):
        def put(self, path, data=None, content_type=None):
            self.put_calls.append((path, data, content_type))
            return {}

    deployer = SharePointDeployer(NoItemIdGraph(), _template())

    with pytest.raises(DeploymentError, match="missing file id"):
        deployer.deploy("Finance")


def test_sharepoint_deployer_raises_when_site_not_found_empty_list():
    class EmptyGraph:
        def get(self, path, params=None):
            if path == "/sites":
                return {"value": []}
            raise AssertionError(f"Unexpected GET: {path}")

    deployer = SharePointDeployer(EmptyGraph(), _template())

    with pytest.raises(DeploymentError, match="site not found"):
        deployer.deploy("Finance")


def test_sharepoint_deployer_raises_when_all_candidates_non_dict():
    class NonDictCandidatesGraph:
        def get(self, path, params=None):
            if path == "/sites":
                return {"value": ["not-a-dict", 42, None]}
            raise AssertionError(f"Unexpected GET: {path}")

    deployer = SharePointDeployer(NonDictCandidatesGraph(), _template())

    with pytest.raises(DeploymentError, match="site not found"):
        deployer.deploy("Finance")


def test_sharepoint_deployer_raises_when_multiple_exact_matches():
    class MultiExactGraph(StubGraph):
        def get(self, path, params=None):
            if path == "/sites":
                return {
                    "value": [
                        {"id": "id-a", "displayName": "Finance", "name": "Finance"},
                        {"id": "id-b", "displayName": "Finance", "name": "Finance"},
                    ]
                }
            return super().get(path, params)

    deployer = SharePointDeployer(MultiExactGraph(), _template())

    with pytest.raises(DeploymentError, match="multiple exact matches"):
        deployer.deploy("Finance")


def test_sharepoint_deployer_accepts_single_fuzzy_match():
    graph = StubGraph()

    class FuzzyMatchGraph(StubGraph):
        def get(self, path, params=None):
            if path == "/sites":
                return {
                    "value": [
                        {
                            "id": graph.site_id,
                            "displayName": "Finance Group",
                            "name": "finance-group",
                            "webUrl": "https://contoso.sharepoint.com/sites/Finance",
                        }
                    ]
                }
            return super().get(path, params)

    deployer = SharePointDeployer(FuzzyMatchGraph(), _template())
    result = deployer.deploy("Finance")

    assert result["type"] == "sharepoint"


def test_sharepoint_deployer_raises_when_resolved_site_missing_id():
    class MissingIdGraph:
        def get(self, path, params=None):
            if path == "/sites":
                return {"value": [{"displayName": "Finance", "name": "finance"}]}
            raise AssertionError(f"Unexpected GET: {path}")

    deployer = SharePointDeployer(MissingIdGraph(), _template())

    with pytest.raises(DeploymentError, match="invalid site id"):
        deployer.deploy("Finance")


def test_sharepoint_deployer_raises_when_site_by_id_returns_404():
    class NotFoundGraph:
        def get(self, path, params=None):
            raise GraphApiError("Not Found", status_code=404)

    deployer = SharePointDeployer(NotFoundGraph(), _template())

    with pytest.raises(DeploymentError, match="site not found"):
        deployer.deploy("Finance", site_id="bad-site-id")


def test_sharepoint_deployer_raises_when_site_by_id_non_dict_response():
    class NonDictResponseGraph:
        def get(self, path, params=None):
            return ["not-a-dict"]

    deployer = SharePointDeployer(NonDictResponseGraph(), _template())

    with pytest.raises(DeploymentError, match="invalid site response"):
        deployer.deploy("Finance", site_id="site-123")


def test_sharepoint_deployer_raises_when_rendered_content_empty():
    from anglerfish.models import SharePointTemplate as SPTemplate

    template = SPTemplate(
        name="Test",
        description="Test",
        site_name="Finance",
        folder_path="Canary",
        filenames=["file.txt"],
        content_text="   ",
        variables=[],
    )
    deployer = SharePointDeployer(StubGraph(), template)

    with pytest.raises(DeploymentError, match="file content is empty"):
        deployer.deploy("Finance")


def test_sharepoint_deployer_verify_retries_on_404_then_succeeds(monkeypatch: pytest.MonkeyPatch):
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
    monkeypatch.setattr("anglerfish.deployers.sharepoint.time.sleep", lambda *_: None)

    deployer = SharePointDeployer(graph, _template())
    result = deployer.deploy("Finance")

    assert result["verified"] == "true"


def test_sharepoint_deployer_raises_when_item_id_mismatch():
    class WrongIdGraph(StubGraph):
        def get(self, path, params=None):
            if "/drive/items/" in path:
                return {"id": "wrong-id", "name": "bonus_plan.txt"}
            return super().get(path, params)

    deployer = SharePointDeployer(WrongIdGraph(), _template())

    with pytest.raises(DeploymentError, match="id mismatch"):
        deployer.deploy("Finance")


def test_sharepoint_deployer_raises_when_item_name_mismatch():
    class WrongNameGraph(StubGraph):
        def get(self, path, params=None):
            if "/drive/items/" in path:
                raw_item_id = unquote(path.rsplit("/", 1)[-1])
                return {"id": raw_item_id, "name": "wrong_name.txt"}
            return super().get(path, params)

    deployer = SharePointDeployer(WrongNameGraph(), _template())

    with pytest.raises(DeploymentError, match="name mismatch"):
        deployer.deploy("Finance")


def test_sharepoint_deployer_raises_when_filenames_not_a_list():
    deployer = SharePointDeployer(StubGraph(), _template())

    with pytest.raises(DeploymentError, match="must be provided as a list"):
        deployer.deploy("Finance", filenames="bonus_plan.txt")


def test_sharepoint_deployer_raises_when_filename_is_empty_string():
    deployer = SharePointDeployer(StubGraph(), _template())

    with pytest.raises(DeploymentError, match="cannot be empty"):
        deployer.deploy("Finance", filenames=[""])


def test_sharepoint_deployer_raises_when_filenames_list_is_empty():
    deployer = SharePointDeployer(StubGraph(), _template())

    with pytest.raises(DeploymentError, match="At least one"):
        deployer.deploy("Finance", filenames=[])


def test_sharepoint_deployer_docx_filename_triggers_docx_content_type():
    graph = StubGraph()
    template = SharePointTemplate(
        name="Test",
        description="Test",
        site_name="Finance",
        folder_path="Board/Minutes",
        filenames=["Board_Minutes.docx"],
        content_text="Board meeting minutes content",
        variables=[],
    )
    deployer = SharePointDeployer(graph, template)

    deployer.deploy("Finance")

    assert graph.put_calls[0][2] == "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


def test_sharepoint_deployer_xlsx_filename_triggers_xlsx_content_type():
    graph = StubGraph()
    template = SharePointTemplate(
        name="Test",
        description="Test",
        site_name="Finance",
        folder_path="Compensation/Analysis",
        filenames=["Compensation.xlsx"],
        content_text="Header\nRow 1\nRow 2",
        variables=[],
    )
    deployer = SharePointDeployer(graph, template)

    deployer.deploy("Finance")

    assert graph.put_calls[0][2] == "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def test_sharepoint_deployer_txt_filename_still_uses_text_plain():
    graph = StubGraph()
    deployer = SharePointDeployer(graph, _template())

    deployer.deploy("Finance")

    assert graph.put_calls[0][2] == "text/plain; charset=utf-8"


def test_sharepoint_describe_candidate_returns_label_when_names_match():
    from anglerfish.deployers.sharepoint import _describe_candidate

    result = _describe_candidate({"displayName": "Finance", "name": "Finance", "id": "abc"})

    assert result == "Finance"


# ---------------------------------------------------------------------------
# Path traversal protection tests
# ---------------------------------------------------------------------------


class TestNormalizeFolderPathTraversalProtection:
    """_normalize_folder_path() must reject path traversal attempts."""

    def _call(self, path: str) -> str:
        from anglerfish.deployers._paths import normalize_folder_path

        return normalize_folder_path(path, strip_library_prefix=True)

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
        # Dots inside a filename-like segment are fine; only standalone ".." is rejected.
        result = self._call("Finance/Q1.Reports")
        assert result == "Finance/Q1.Reports"

    def test_allows_shared_documents_prefix_stripped(self):
        result = self._call("Shared Documents/HR/Restricted")
        assert result == "HR/Restricted"


# ---------------------------------------------------------------------------
# item_id in deploy return dict
# ---------------------------------------------------------------------------


def test_sharepoint_deployer_deploy_includes_item_id():
    graph = StubGraph()
    deployer = SharePointDeployer(graph, _template())

    result = deployer.deploy("Finance")

    assert "item_id" in result
    assert result["item_id"]  # non-empty


# ---------------------------------------------------------------------------
# remove_canary() tests
# ---------------------------------------------------------------------------


class _DelGraph:
    def __init__(self):
        self.delete_calls: list[str] = []
        self.get_calls: list[tuple[str, object]] = []
        self._get_response: dict | None = None

    def delete(self, path: str) -> None:
        self.delete_calls.append(path)

    def get(self, path: str, params=None) -> dict:
        self.get_calls.append((path, params))
        if self._get_response is not None:
            return self._get_response
        raise AssertionError(f"Unexpected GET: {path}")


def test_sharepoint_remove_canary_with_item_id():
    graph = _DelGraph()
    site_id = "contoso.sharepoint.com,abc123,def456"
    record = {"site_id": site_id, "item_id": "item-1"}

    result = remove_canary(graph, record)

    assert result["removed"] == "true"
    assert result["site_id"] == site_id
    assert result["item_id"] == "item-1"
    encoded_site = quote(site_id, safe="")
    encoded_item = quote("item-1", safe="")
    assert graph.delete_calls == [f"/sites/{encoded_site}/drive/items/{encoded_item}"]
    assert graph.get_calls == []  # no path-based lookup needed


def test_sharepoint_remove_canary_without_item_id_resolves_by_path():
    graph = _DelGraph()
    graph._get_response = {"id": "resolved-item-id"}
    site_id = "contoso.sharepoint.com,abc123,def456"
    record = {
        "site_id": site_id,
        "folder_path": "HR/Restricted",
        "uploaded_files": "bonus_plan.txt",
    }

    result = remove_canary(graph, record)

    assert result["removed"] == "true"
    assert result["item_id"] == "resolved-item-id"
    assert len(graph.get_calls) == 1
    assert len(graph.delete_calls) == 1
    encoded_site = quote(site_id, safe="")
    encoded_item = quote("resolved-item-id", safe="")
    assert graph.delete_calls[0] == f"/sites/{encoded_site}/drive/items/{encoded_item}"


def test_sharepoint_remove_canary_raises_when_site_id_missing():
    with pytest.raises(DeploymentError, match="missing 'site_id'"):
        remove_canary(_DelGraph(), {"item_id": "item-1"})


def test_sharepoint_remove_canary_raises_when_no_item_id_and_no_path():
    with pytest.raises(DeploymentError, match="Cannot resolve file to delete"):
        remove_canary(_DelGraph(), {"site_id": "s1"})


def test_sharepoint_remove_canary_raises_when_path_lookup_returns_no_id():
    graph = _DelGraph()
    graph._get_response = {}  # no "id" field
    with pytest.raises(DeploymentError, match="could not resolve file item ID"):
        remove_canary(
            graph,
            {
                "site_id": "s1",
                "folder_path": "HR/Restricted",
                "uploaded_files": "bonus.txt",
            },
        )


def test_sharepoint_remove_canary_delete_wraps_graph_error():
    class ErrorGraph:
        def delete(self, path: str) -> None:
            raise GraphApiError("Denied", status_code=403)

    with pytest.raises(DeploymentError, match="SharePoint cleanup failed"):
        remove_canary(ErrorGraph(), {"site_id": "s1", "item_id": "i1"})


def test_sharepoint_remove_canary_path_lookup_wraps_graph_error():
    class ErrorGraph:
        def get(self, path: str, params=None) -> dict:
            raise GraphApiError("Not Found", status_code=404)

    with pytest.raises(DeploymentError, match="SharePoint cleanup failed"):
        remove_canary(
            ErrorGraph(),
            {
                "site_id": "s1",
                "folder_path": "HR/Restricted",
                "uploaded_files": "bonus.txt",
            },
        )
