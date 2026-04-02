"""Data models for deployment templates."""

from dataclasses import dataclass, field


@dataclass(frozen=True)
class OutlookTemplate:
    name: str
    description: str
    folder_name: str
    subject: str
    body_html: str
    sender_name: str
    sender_email: str
    variables: list[dict[str, str]] = field(default_factory=list)
