"""Shared path encoding utilities for deployers."""

from __future__ import annotations

from urllib.parse import quote


def path_segment(value: str) -> str:
    """URL-encode a single path segment for Graph API URLs."""
    return quote(value, safe="")
