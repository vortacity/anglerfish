"""SharePoint canary deployment implementation."""

from __future__ import annotations

import re
import time
from string import Template as StringTemplate
from urllib.parse import quote, unquote

from ..exceptions import DeploymentError, GraphApiError
from ..models import SharePointTemplate
from .base import BaseDeployer
from .content import render_file_content

_VERIFY_ATTEMPTS = 3
_SHAREPOINT_LIBRARY_PREFIXES = {"shared documents", "documents"}
# Percent-encoded slash (%2f), backslash (%5c), and dot (%2e) sequences used in traversal attacks.
_TRAVERSAL_ENCODED_RE = re.compile(r"%2[ef]|%5c", re.IGNORECASE)


class SharePointDeployer(BaseDeployer):
    def __init__(self, graph, template: SharePointTemplate):
        super().__init__(graph, template)

    def deploy(self, target_user: str, **kwargs) -> dict[str, str]:
        site_name = str(target_user).strip()
        if not site_name:
            raise DeploymentError("Target SharePoint site name is required.")
        site_id = str(kwargs.get("site_id", "")).strip()

        folder_path = _normalize_folder_path(str(kwargs.get("folder_path", self.template.folder_path)))
        if not folder_path:
            raise DeploymentError(
                "Target SharePoint folder path is required (example: 'HR/Restricted'). "
                "Do not include 'Shared Documents/'."
            )

        filenames = _normalize_filenames(kwargs.get("filenames", self.template.filenames))

        try:
            encoded_site_id, site = self._resolve_site(site_name, site_id=site_id)
            drive = self.graph.get(f"/sites/{encoded_site_id}/drive")
            drive_name = str(drive.get("name", "Documents")).strip() or "Documents"

            uploaded_names: list[str] = []
            uploaded_urls: list[str] = []
            for filename in filenames:
                path = _encode_drive_path(folder_path, filename)
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

        return _path_segment(site_id), site

    def _resolve_site_by_id(self, *, site_name: str, site_id: str) -> tuple[str, dict]:
        encoded_site_id = _path_segment(site_id)
        try:
            site = self.graph.get(f"/sites/{encoded_site_id}")
        except GraphApiError as exc:
            if exc.status_code == 404:
                raise DeploymentError(f"SharePoint site not found: {site_name}") from exc
            raise

        if not isinstance(site, dict):
            raise DeploymentError("SharePoint site lookup returned an invalid site response.")

        resolved_site_id = str(site.get("id", "")).strip() or site_id
        return _path_segment(resolved_site_id), site

    def _render_content(self, filename: str) -> str:
        rendered = StringTemplate(self.template.content_text).safe_substitute({"filename": filename}).strip()
        if not rendered:
            raise DeploymentError(f"SharePoint file content is empty for '{filename}'.")
        return rendered

    def _verify_uploaded_item(self, encoded_site_id: str, item_id: str, expected_name: str) -> dict:
        encoded_item_id = _path_segment(item_id)

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


def _normalize_filenames(raw: object) -> list[str]:
    if not isinstance(raw, list):
        raise DeploymentError("SharePoint filenames must be provided as a list.")

    filenames: list[str] = []
    for entry in raw:
        name = str(entry).strip()
        if not name:
            raise DeploymentError("SharePoint filenames cannot be empty.")
        if "/" in name or "\\" in name:
            raise DeploymentError("SharePoint filenames must not contain path separators.")
        filenames.append(name)

    if not filenames:
        raise DeploymentError("At least one SharePoint filename is required.")
    if len(filenames) != 1:
        raise DeploymentError("SharePoint deployment currently supports exactly one filename.")
    return filenames


def _normalize_folder_path(raw_path: str) -> str:
    segments: list[str] = []
    for raw_segment in raw_path.strip().strip("/").split("/"):
        value = raw_segment.strip()
        if value:
            segments.append(value)

    if not segments:
        return ""

    first_segment = unquote(segments[0]).strip().casefold()
    if first_segment in _SHAREPOINT_LIBRARY_PREFIXES:
        segments = segments[1:]

    # Path traversal protection: reject dangerous segments after stripping the
    # optional library prefix so we validate the actual user-supplied path.
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
        # Reject raw backslashes — not valid in SharePoint URL paths and used
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

    encoded_site_id = _path_segment(site_id)

    # If item_id not in record (old record), resolve by path
    if not item_id:
        folder_path = record.get("folder_path", "").strip()
        filename = record.get("uploaded_files", "").strip()
        if not folder_path or not filename:
            raise DeploymentError(
                "Deployment record missing 'item_id', 'folder_path', and 'uploaded_files'. "
                "Cannot resolve file to delete."
            )
        path = _encode_drive_path(folder_path, filename)
        try:
            item = graph.get(f"/sites/{encoded_site_id}/drive/root:/{path}")
        except GraphApiError as exc:
            raise DeploymentError(f"SharePoint cleanup failed: {exc}") from exc
        item_id = str(item.get("id", "")).strip()
        if not item_id:
            raise DeploymentError("SharePoint cleanup failed: could not resolve file item ID.")

    encoded_item_id = _path_segment(item_id)
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
