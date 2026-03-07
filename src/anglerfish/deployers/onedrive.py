"""OneDrive canary deployment implementation."""

from __future__ import annotations

import re
import time
from string import Template as StringTemplate
from urllib.parse import quote, unquote

from ..exceptions import DeploymentError, GraphApiError
from ..models import OneDriveTemplate
from .base import BaseDeployer
from .content import render_file_content

_VERIFY_ATTEMPTS = 3
# Percent-encoded slash (%2f), backslash (%5c), and dot (%2e) sequences used in traversal attacks.
_TRAVERSAL_ENCODED_RE = re.compile(r"%2[ef]|%5c", re.IGNORECASE)


class OneDriveDeployer(BaseDeployer):
    def __init__(self, graph, template: OneDriveTemplate):
        super().__init__(graph, template)

    def deploy(self, target_user: str, **kwargs) -> dict[str, str]:
        upn = str(target_user).strip()
        if not upn or "@" not in upn:
            raise DeploymentError("Target user must be a valid UPN or email address containing '@'.")

        folder_path = _normalize_folder_path(str(kwargs.get("folder_path", self.template.folder_path)))
        filenames = _normalize_filenames(kwargs.get("filenames", self.template.filenames))

        encoded_upn = _path_segment(upn)

        try:
            uploaded_names: list[str] = []
            uploaded_urls: list[str] = []
            item_id = ""
            for filename in filenames:
                path = _encode_drive_path(folder_path, filename)
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
        encoded_item_id = _path_segment(item_id)

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


def _normalize_filenames(raw: object) -> list[str]:
    if not isinstance(raw, list):
        raise DeploymentError("OneDrive filenames must be provided as a list.")

    filenames: list[str] = []
    for entry in raw:
        name = str(entry).strip()
        if not name:
            raise DeploymentError("OneDrive filenames cannot be empty.")
        if "/" in name or "\\" in name:
            raise DeploymentError("OneDrive filenames must not contain path separators.")
        filenames.append(name)

    if not filenames:
        raise DeploymentError("At least one OneDrive filename is required.")
    if len(filenames) != 1:
        raise DeploymentError("OneDrive deployment currently supports exactly one filename.")
    return filenames


def _normalize_folder_path(raw_path: str) -> str:
    segments: list[str] = []
    for raw_segment in raw_path.strip().strip("/").split("/"):
        value = raw_segment.strip()
        if value:
            segments.append(value)

    if not segments:
        return ""

    # Path traversal protection: reject dangerous segments.
    for segment in segments:
        decoded = unquote(segment)
        # Reject null bytes (in raw or decoded form).
        if "\x00" in segment or "\x00" in decoded:
            raise DeploymentError(f"Invalid folder path segment '{segment}': null bytes are not permitted.")
        # Reject percent-encoded slashes, backslashes, or dots first — this check
        # runs before the decoded-value checks so the error message is accurate.
        if _TRAVERSAL_ENCODED_RE.search(segment):
            raise DeploymentError(
                f"Invalid folder path segment '{segment}': percent-encoded traversal "
                "sequences (%2e, %2f, %5c) are not permitted."
            )
        # Reject raw backslashes — not valid in OneDrive URL paths and used
        # for Windows-style traversal (e.g. "..\..\" sequences).
        if "\\" in segment:
            raise DeploymentError(
                f"Invalid folder path segment '{segment}': "
                "backslashes are not permitted (path traversal is not permitted)."
            )
        # Reject traversal dot sequences (e.g. "..", "../").
        if decoded.strip() in ("..", "."):
            raise DeploymentError(f"Invalid folder path segment '{segment}': path traversal is not permitted.")

    return "/".join(segments)


def _encode_drive_path(folder_path: str, filename: str) -> str:
    segments: list[str] = []
    for segment in folder_path.split("/"):
        value = segment.strip()
        if value:
            segments.append(value)
    segments.append(filename.strip())
    return "/".join(quote(segment, safe="") for segment in segments)


def _path_segment(value: str) -> str:
    return quote(value, safe="")


def remove_canary(graph, record: dict[str, str]) -> dict[str, str]:
    """Remove a deployed OneDrive canary file."""
    target_user = record.get("target_user", "").strip()
    item_id = record.get("item_id", "").strip()

    if not target_user:
        raise DeploymentError("Deployment record missing 'target_user'.")
    if not item_id:
        raise DeploymentError("Deployment record missing 'item_id'.")

    encoded_upn = _path_segment(target_user)
    encoded_item_id = _path_segment(item_id)

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
