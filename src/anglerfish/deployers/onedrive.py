"""OneDrive canary deployment implementation."""

from __future__ import annotations

import time
from string import Template as StringTemplate

from ..exceptions import DeploymentError, GraphApiError
from ..models import OneDriveTemplate
from .base import BaseDeployer
from .content import render_file_content
from ._paths import encode_drive_path, normalize_filenames, normalize_folder_path, path_segment

_VERIFY_ATTEMPTS = 3


class OneDriveDeployer(BaseDeployer):
    def __init__(self, graph, template: OneDriveTemplate):
        super().__init__(graph, template)

    def deploy(self, target_user: str, **kwargs) -> dict[str, str]:
        upn = str(target_user).strip()
        if not upn or "@" not in upn:
            raise DeploymentError("Target user must be a valid UPN or email address containing '@'.")

        folder_path = normalize_folder_path(str(kwargs.get("folder_path", self.template.folder_path)))
        filenames = normalize_filenames(kwargs.get("filenames", self.template.filenames), label="OneDrive")

        encoded_upn = path_segment(upn)

        try:
            uploaded_names: list[str] = []
            uploaded_urls: list[str] = []
            item_id = ""
            for filename in filenames:
                path = encode_drive_path(folder_path, filename)
                rendered_text = self._render_content(filename)
                content, content_type = render_file_content(rendered_text, filename)
                item = self.graph.put(
                    f"/users/{encoded_upn}/drive/root:/{path}:/content",
                    data=content,
                    content_type=content_type,
                )
                item_id = str(item.get("id", "")).strip()
                if not item_id:
                    raise DeploymentError(f"Graph response missing file id for '{filename}'.")

                verified_item = self._verify_uploaded_item(encoded_upn, item_id, filename)
                uploaded_names.append(filename)
                uploaded_urls.append(str(verified_item.get("webUrl", "")).strip())

            return {
                "type": "onedrive",
                "target_user": upn,
                "folder_path": folder_path,
                "uploaded_count": str(len(uploaded_names)),
                "uploaded_files": ", ".join(uploaded_names),
                "uploaded_urls": ", ".join([url for url in uploaded_urls if url]),
                "item_id": item_id,
                "verified": "true",
            }
        except GraphApiError as exc:
            msg = str(exc)
            if getattr(exc, "status_code", None) == 404 and "/drive/" in (getattr(exc, "path", "") or ""):
                msg = f"OneDrive deployment failed: {exc}. Check that OneDrive is provisioned for the target user."
            else:
                msg = f"OneDrive deployment failed: {exc}"
            raise DeploymentError(msg) from exc

    def _render_content(self, filename: str) -> str:
        rendered = StringTemplate(self.template.content_text).safe_substitute({"filename": filename}).strip()
        if not rendered:
            raise DeploymentError(f"OneDrive file content is empty for '{filename}'.")
        return rendered

    def _verify_uploaded_item(self, encoded_upn: str, item_id: str, expected_name: str) -> dict:
        encoded_item_id = path_segment(item_id)

        for attempt in range(_VERIFY_ATTEMPTS):
            try:
                item = self.graph.get(f"/users/{encoded_upn}/drive/items/{encoded_item_id}")
            except GraphApiError as exc:
                if exc.status_code == 404 and attempt < _VERIFY_ATTEMPTS - 1:
                    time.sleep(attempt + 1)
                    continue
                raise DeploymentError(f"OneDrive verification failed: {exc}") from exc

            if str(item.get("id", "")).strip() != item_id:
                raise DeploymentError("OneDrive verification failed: uploaded file id mismatch.")
            if str(item.get("name", "")).strip() != expected_name:
                raise DeploymentError("OneDrive verification failed: uploaded file name mismatch.")
            return item

        raise DeploymentError("OneDrive verification failed: uploaded files were not readable after retries.")


def remove_canary(graph, record: dict[str, str]) -> dict[str, str]:
    """Remove a deployed OneDrive canary file."""
    target_user = record.get("target_user", "").strip()
    item_id = record.get("item_id", "").strip()

    if not target_user:
        raise DeploymentError("Deployment record missing 'target_user'.")
    if not item_id:
        raise DeploymentError("Deployment record missing 'item_id'.")

    encoded_upn = path_segment(target_user)
    encoded_item_id = path_segment(item_id)

    try:
        graph.delete(f"/users/{encoded_upn}/drive/items/{encoded_item_id}")
    except GraphApiError as exc:
        raise DeploymentError(f"OneDrive cleanup failed: {exc}") from exc

    return {
        "type": "onedrive",
        "target_user": target_user,
        "item_id": item_id,
        "removed": "true",
    }
