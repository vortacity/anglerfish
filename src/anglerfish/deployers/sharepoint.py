"""SharePoint canary deployment implementation."""

from __future__ import annotations

import time
from string import Template as StringTemplate

from ..exceptions import DeploymentError, GraphApiError
from ..models import SharePointTemplate
from .base import BaseDeployer
from .content import render_file_content
from ._paths import encode_drive_path, normalize_filenames, normalize_folder_path, path_segment

_VERIFY_ATTEMPTS = 3


class SharePointDeployer(BaseDeployer):
    def __init__(self, graph, template: SharePointTemplate):
        super().__init__(graph, template)

    def deploy(self, target_user: str, **kwargs) -> dict[str, str]:
        site_name = str(target_user).strip()
        if not site_name:
            raise DeploymentError("Target SharePoint site name is required.")
        site_id = str(kwargs.get("site_id", "")).strip()

        folder_path = normalize_folder_path(
            str(kwargs.get("folder_path", self.template.folder_path)), strip_library_prefix=True
        )
        if not folder_path:
            raise DeploymentError(
                "Target SharePoint folder path is required (example: 'HR/Restricted'). "
                "Do not include 'Shared Documents/'."
            )

        filenames = normalize_filenames(kwargs.get("filenames", self.template.filenames), label="SharePoint")

        try:
            encoded_site_id, site = self._resolve_site(site_name, site_id=site_id)
            drive = self.graph.get(f"/sites/{encoded_site_id}/drive")
            drive_name = str(drive.get("name", "Documents")).strip() or "Documents"

            uploaded_names: list[str] = []
            uploaded_urls: list[str] = []
            for filename in filenames:
                path = encode_drive_path(folder_path, filename)
                rendered_text = self._render_content(filename)
                content, content_type = render_file_content(rendered_text, filename)
                item = self.graph.put(
                    f"/sites/{encoded_site_id}/drive/root:/{path}:/content",
                    data=content,
                    content_type=content_type,
                )
                item_id = str(item.get("id", "")).strip()
                if not item_id:
                    raise DeploymentError(f"Graph response missing file id for '{filename}'.")

                verified_item = self._verify_uploaded_item(encoded_site_id, item_id, filename)
                uploaded_names.append(filename)
                uploaded_urls.append(str(verified_item.get("webUrl", "")).strip())

            return {
                "type": "sharepoint",
                "site_name": site_name,
                "site_id": str(site.get("id", "")),
                "site_web_url": str(site.get("webUrl", "")),
                "drive_name": drive_name,
                "folder_path": folder_path,
                "uploaded_count": str(len(uploaded_names)),
                "uploaded_files": ", ".join(uploaded_names),
                "uploaded_urls": ", ".join([url for url in uploaded_urls if url]),
                "item_id": item_id,
                "verified": "true",
            }
        except GraphApiError as exc:
            raise DeploymentError(f"SharePoint deployment failed: {exc}") from exc

    def _resolve_site(self, site_name: str, *, site_id: str = "") -> tuple[str, dict]:
        if site_id:
            return self._resolve_site_by_id(site_name=site_name, site_id=site_id)

        response = self.graph.get("/sites", params={"search": site_name})
        raw_candidates = response.get("value", [])
        if not isinstance(raw_candidates, list) or not raw_candidates:
            raise DeploymentError(f"SharePoint site not found: {site_name}")

        candidates = [candidate for candidate in raw_candidates if isinstance(candidate, dict)]
        if not candidates:
            raise DeploymentError(f"SharePoint site not found: {site_name}")

        desired = site_name.casefold()
        exact_matches = [
            candidate
            for candidate in candidates
            if str(candidate.get("displayName", "")).strip().casefold() == desired
            or str(candidate.get("name", "")).strip().casefold() == desired
        ]
        if len(exact_matches) == 1:
            site = exact_matches[0]
        elif len(exact_matches) > 1:
            options = ", ".join(_describe_candidate(site) for site in exact_matches[:5])
            raise DeploymentError(
                f"SharePoint site search for '{site_name}' returned multiple exact matches: "
                f"{options}. Use a unique site name."
            )
        elif len(candidates) == 1:
            site = candidates[0]
        else:
            options = ", ".join(_describe_candidate(site) for site in candidates[:5])
            raise DeploymentError(
                f"SharePoint site search for '{site_name}' returned multiple results: "
                f"{options}. Use an exact site name."
            )

        site_id = str(site.get("id", "")).strip()
        if not site_id:
            raise DeploymentError("SharePoint site lookup returned an invalid site id.")

        return path_segment(site_id), site

    def _resolve_site_by_id(self, *, site_name: str, site_id: str) -> tuple[str, dict]:
        encoded_site_id = path_segment(site_id)
        try:
            site = self.graph.get(f"/sites/{encoded_site_id}")
        except GraphApiError as exc:
            if exc.status_code == 404:
                raise DeploymentError(f"SharePoint site not found: {site_name}") from exc
            raise

        if not isinstance(site, dict):
            raise DeploymentError("SharePoint site lookup returned an invalid site response.")

        resolved_site_id = str(site.get("id", "")).strip() or site_id
        return path_segment(resolved_site_id), site

    def _render_content(self, filename: str) -> str:
        rendered = StringTemplate(self.template.content_text).safe_substitute({"filename": filename}).strip()
        if not rendered:
            raise DeploymentError(f"SharePoint file content is empty for '{filename}'.")
        return rendered

    def _verify_uploaded_item(self, encoded_site_id: str, item_id: str, expected_name: str) -> dict:
        encoded_item_id = path_segment(item_id)

        for attempt in range(_VERIFY_ATTEMPTS):
            try:
                item = self.graph.get(f"/sites/{encoded_site_id}/drive/items/{encoded_item_id}")
            except GraphApiError as exc:
                if exc.status_code == 404 and attempt < _VERIFY_ATTEMPTS - 1:
                    time.sleep(attempt + 1)
                    continue
                raise DeploymentError(f"SharePoint verification failed: {exc}") from exc

            if str(item.get("id", "")).strip() != item_id:
                raise DeploymentError("SharePoint verification failed: uploaded file id mismatch.")
            if str(item.get("name", "")).strip() != expected_name:
                raise DeploymentError("SharePoint verification failed: uploaded file name mismatch.")
            return item

        raise DeploymentError("SharePoint verification failed: uploaded files were not readable after retries.")


def _describe_candidate(candidate: dict) -> str:
    display_name = str(candidate.get("displayName", "")).strip()
    short_name = str(candidate.get("name", "")).strip()
    site_id = str(candidate.get("id", "")).strip()

    label = display_name or short_name or site_id or "unknown"
    if short_name and short_name != display_name:
        return f"{label} ({short_name})"
    return label


def remove_canary(graph, record: dict[str, str]) -> dict[str, str]:
    """Remove a deployed SharePoint canary file."""
    site_id = record.get("site_id", "").strip()
    item_id = record.get("item_id", "").strip()

    if not site_id:
        raise DeploymentError("Deployment record missing 'site_id'.")

    encoded_site_id = path_segment(site_id)

    # If item_id not in record (old record), resolve by path
    if not item_id:
        folder_path = record.get("folder_path", "").strip()
        filename = record.get("uploaded_files", "").strip()
        if not folder_path or not filename:
            raise DeploymentError(
                "Deployment record missing 'item_id', 'folder_path', and 'uploaded_files'. "
                "Cannot resolve file to delete."
            )
        path = encode_drive_path(folder_path, filename)
        try:
            item = graph.get(f"/sites/{encoded_site_id}/drive/root:/{path}")
        except GraphApiError as exc:
            raise DeploymentError(f"SharePoint cleanup failed: {exc}") from exc
        item_id = str(item.get("id", "")).strip()
        if not item_id:
            raise DeploymentError("SharePoint cleanup failed: could not resolve file item ID.")

    encoded_item_id = path_segment(item_id)
    try:
        graph.delete(f"/sites/{encoded_site_id}/drive/items/{encoded_item_id}")
    except GraphApiError as exc:
        raise DeploymentError(f"SharePoint cleanup failed: {exc}") from exc

    return {
        "type": "sharepoint",
        "site_id": site_id,
        "item_id": item_id,
        "removed": "true",
    }
