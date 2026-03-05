"""Data models for deployment templates."""

import dataclasses
from dataclasses import dataclass


@dataclass(frozen=True)
class OutlookTemplate:
    name: str
    description: str
    folder_name: str
    subject: str
    body_html: str
    sender_name: str
    sender_email: str
    variables: list[dict[str, str]] = dataclasses.field(default_factory=list)


@dataclass(frozen=True)
class SharePointTemplate:
    name: str
    description: str
    site_name: str
    folder_path: str
    filenames: list[str]
    content_text: str
    variables: list[dict[str, str]] = dataclasses.field(default_factory=list)


@dataclass(frozen=True)
class OneDriveTemplate:
    name: str
    description: str
    folder_path: str
    filenames: list[str]
    content_text: str
    variables: list[dict[str, str]] = dataclasses.field(default_factory=list)


@dataclass(frozen=True)
class TeamsTemplate:
    name: str
    description: str
    subject: str
    body_html: str
    variables: list[dict[str, str]] = dataclasses.field(default_factory=list)
