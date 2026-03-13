"""Shared path encoding and validation utilities for deployers."""

from __future__ import annotations

import re
from urllib.parse import quote, unquote

from ..exceptions import DeploymentError

# Percent-encoded slash (%2f), backslash (%5c), and dot (%2e) sequences used in traversal attacks.
TRAVERSAL_ENCODED_RE = re.compile(r"%2[ef]|%5c", re.IGNORECASE)

# SharePoint default library prefixes that should be stripped from user-supplied paths.
SHAREPOINT_LIBRARY_PREFIXES = {"shared documents", "documents"}


def path_segment(value: str) -> str:
    """URL-encode a single path segment for Graph API URLs."""
    return quote(value, safe="")


def encode_drive_path(folder_path: str, filename: str) -> str:
    """Encode a folder-path/filename combination for Graph drive API paths."""
    segments: list[str] = []
    for segment in folder_path.split("/"):
        value = segment.strip()
        if value:
            segments.append(value)
    segments.append(filename.strip())
    return "/".join(quote(segment, safe="") for segment in segments)


def validate_folder_segments(segments: list[str]) -> None:
    """Validate folder path segments against traversal attacks.

    Raises DeploymentError if any segment contains dangerous patterns.
    """
    for segment in segments:
        decoded = unquote(segment)
        # Reject null bytes (in raw or decoded form).
        if "\x00" in segment or "\x00" in decoded:
            raise DeploymentError(f"Invalid folder path segment '{segment}': null bytes are not permitted.")
        # Reject percent-encoded slashes, backslashes, or dots first — this check
        # runs before the decoded-value checks so the error message is accurate.
        if TRAVERSAL_ENCODED_RE.search(segment):
            raise DeploymentError(
                f"Invalid folder path segment '{segment}': percent-encoded traversal "
                "sequences (%2e, %2f, %5c) are not permitted."
            )
        # Reject raw backslashes — not valid in URL paths and used
        # for Windows-style traversal (e.g. "..\..\" sequences).
        if "\\" in segment:
            raise DeploymentError(
                f"Invalid folder path segment '{segment}': "
                "backslashes are not permitted (path traversal is not permitted)."
            )
        # Reject traversal dot sequences (e.g. "..", "../").
        if decoded.strip() in ("..", "."):
            raise DeploymentError(f"Invalid folder path segment '{segment}': path traversal is not permitted.")


def normalize_folder_path(raw_path: str, *, strip_library_prefix: bool = False) -> str:
    """Parse and validate a folder path, optionally stripping SharePoint library prefixes."""
    segments: list[str] = []
    for raw_segment in raw_path.strip().strip("/").split("/"):
        value = raw_segment.strip()
        if value:
            segments.append(value)

    if not segments:
        return ""

    if strip_library_prefix:
        first_segment = unquote(segments[0]).strip().casefold()
        if first_segment in SHAREPOINT_LIBRARY_PREFIXES:
            segments = segments[1:]

    # Path traversal protection: reject dangerous segments after stripping the
    # optional library prefix so we validate the actual user-supplied path.
    validate_folder_segments(segments)
    return "/".join(segments)


def normalize_filenames(raw: object, *, label: str) -> list[str]:
    """Validate and normalize a list of filenames for deployment.

    Args:
        raw: Expected to be a list of filename strings.
        label: Type label for error messages (e.g. "SharePoint", "OneDrive").
    """
    if not isinstance(raw, list):
        raise DeploymentError(f"{label} filenames must be provided as a list.")

    filenames: list[str] = []
    for entry in raw:
        name = str(entry).strip()
        if not name:
            raise DeploymentError(f"{label} filenames cannot be empty.")
        if "/" in name or "\\" in name:
            raise DeploymentError(f"{label} filenames must not contain path separators.")
        filenames.append(name)

    if not filenames:
        raise DeploymentError(f"At least one {label} filename is required.")
    if len(filenames) != 1:
        raise DeploymentError(f"{label} deployment currently supports exactly one filename.")
    return filenames
