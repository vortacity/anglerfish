"""Template discovery and validation."""

from __future__ import annotations

import dataclasses
import os
from importlib import resources
from pathlib import Path
from string import Template as StringTemplate

import yaml

from .config import (
    TEMPLATE_KIND_ONEDRIVE,
    TEMPLATE_KIND_OUTLOOK,
    TEMPLATE_KIND_SHAREPOINT,
    TEMPLATES_ENV_VAR,
)
from .exceptions import TemplateError
from .models import OneDriveTemplate, OutlookTemplate, SharePointTemplate

_PACKAGE_PATH_PREFIX = "pkg://"
_SUPPORTED_TEMPLATE_TYPES = (
    TEMPLATE_KIND_OUTLOOK,
    TEMPLATE_KIND_SHAREPOINT,
    TEMPLATE_KIND_ONEDRIVE,
)
_REQUIRED_OUTLOOK_FIELDS = (
    "name",
    "description",
    "folder_name",
    "subject",
    "body_html",
    "sender_name",
    "sender_email",
)
_REQUIRED_SHAREPOINT_FIELDS = (
    "name",
    "description",
    "site_name",
    "folder_path",
    "filenames",
    "content_text",
)
_REQUIRED_ONEDRIVE_FIELDS = (
    "name",
    "description",
    "folder_path",
    "filenames",
    "content_text",
)


def list_templates(canary_type: str) -> list[dict[str, str]]:
    """List available templates with metadata and load path."""
    if canary_type not in _SUPPORTED_TEMPLATE_TYPES:
        supported = ", ".join(_SUPPORTED_TEMPLATE_TYPES)
        raise TemplateError(f"Unsupported canary type: {canary_type}. Supported types: {supported}")

    custom_root = os.environ.get(TEMPLATES_ENV_VAR, "").strip()
    if custom_root:
        return _list_custom_templates(Path(custom_root), canary_type)

    return _list_packaged_templates(canary_type)


def find_template_by_name(canary_type: str, template_name: str) -> str:
    """Find a template path by name (case-insensitive). Raises TemplateError on failure."""
    available = list_templates(canary_type)
    if not available:
        raise TemplateError(f"No {canary_type} templates found.")
    name_lower = template_name.casefold()
    matches = [t for t in available if t["name"].casefold() == name_lower]
    if not matches:
        names = ", ".join(repr(t["name"]) for t in available)
        raise TemplateError(f"Template {template_name!r} not found for {canary_type}. Available: {names}")
    if len(matches) > 1:
        raise TemplateError(f"Multiple templates named {template_name!r} found for {canary_type}.")
    return matches[0]["path"]


def load_template(path: str) -> OutlookTemplate | SharePointTemplate | OneDriveTemplate:
    """Load and validate a template from package or filesystem."""
    data = _load_template_data(path)

    template_type = str(data.get("type", TEMPLATE_KIND_OUTLOOK)).strip().lower()
    if template_type == TEMPLATE_KIND_OUTLOOK:
        return _load_outlook_template(data)
    if template_type == TEMPLATE_KIND_SHAREPOINT:
        return _load_sharepoint_template(data)
    if template_type == TEMPLATE_KIND_ONEDRIVE:
        return _load_onedrive_template(data)

    supported = ", ".join(_SUPPORTED_TEMPLATE_TYPES)
    raise TemplateError(f"Template type must be one of: {supported}. Found '{template_type}'")


def _load_outlook_template(data: dict) -> OutlookTemplate:
    missing = [field for field in _REQUIRED_OUTLOOK_FIELDS if not str(data.get(field, "")).strip()]
    if missing:
        raise TemplateError(f"Template missing required fields: {', '.join(missing)}")

    variables = _parse_variables(data.get("variables"))

    return OutlookTemplate(
        name=str(data["name"]),
        description=str(data["description"]),
        folder_name=str(data["folder_name"]),
        subject=str(data["subject"]),
        body_html=str(data["body_html"]),
        sender_name=str(data["sender_name"]),
        sender_email=str(data["sender_email"]),
        variables=variables,
    )


def _load_sharepoint_template(data: dict) -> SharePointTemplate:
    missing = [field for field in _REQUIRED_SHAREPOINT_FIELDS if field not in data]
    if missing:
        raise TemplateError(f"Template missing required fields: {', '.join(missing)}")
    if not str(data.get("name", "")).strip() or not str(data.get("description", "")).strip():
        raise TemplateError("Template missing required fields: name, description")
    if not str(data.get("site_name", "")).strip():
        raise TemplateError("Template missing required fields: site_name")
    if not str(data.get("folder_path", "")).strip():
        raise TemplateError("Template missing required fields: folder_path")
    if not str(data.get("content_text", "")).strip():
        raise TemplateError("Template missing required fields: content_text")

    filenames = _parse_filenames(data.get("filenames"))
    variables = _parse_variables(data.get("variables"))

    return SharePointTemplate(
        name=str(data["name"]),
        description=str(data["description"]),
        site_name=str(data["site_name"]),
        folder_path=str(data["folder_path"]),
        filenames=filenames,
        content_text=str(data["content_text"]),
        variables=variables,
    )


def _load_onedrive_template(data: dict) -> OneDriveTemplate:
    missing = [field for field in _REQUIRED_ONEDRIVE_FIELDS if field not in data]
    if missing:
        raise TemplateError(f"Template missing required fields: {', '.join(missing)}")
    if not str(data.get("name", "")).strip() or not str(data.get("description", "")).strip():
        raise TemplateError("Template missing required fields: name, description")
    if not str(data.get("content_text", "")).strip():
        raise TemplateError("Template missing required fields: content_text")

    filenames = _parse_filenames(data.get("filenames"))
    variables = _parse_variables(data.get("variables"))

    return OneDriveTemplate(
        name=str(data["name"]),
        description=str(data["description"]),
        folder_path=str(data.get("folder_path", "")),
        filenames=filenames,
        content_text=str(data["content_text"]),
        variables=variables,
    )


def _list_custom_templates(root: Path, canary_type: str) -> list[dict[str, str]]:
    directory = root / canary_type
    if not directory.is_dir():
        return []

    templates: list[dict[str, str]] = []
    for path in sorted(directory.glob("*.y*ml")):
        data = _read_yaml_from_path(path)
        templates.append(
            {
                "name": str(data.get("name", path.stem)),
                "description": str(data.get("description", "")),
                "path": str(path),
            }
        )

    return templates


def _list_packaged_templates(canary_type: str) -> list[dict[str, str]]:
    directory = resources.files("anglerfish").joinpath("templates", canary_type)
    if not directory.is_dir():
        return []

    templates: list[dict[str, str]] = []
    for child in sorted(directory.iterdir(), key=lambda item: item.name):
        if not child.is_file() or not child.name.endswith((".yaml", ".yml")):
            continue

        with child.open("r", encoding="utf-8") as handle:
            data = _parse_yaml(handle.read(), source=f"package template {child.name}")

        templates.append(
            {
                "name": str(data.get("name", Path(child.name).stem)),
                "description": str(data.get("description", "")),
                "path": f"{_PACKAGE_PATH_PREFIX}{canary_type}/{child.name}",
            }
        )

    return templates


def _load_template_data(path: str) -> dict:
    if path.startswith(_PACKAGE_PATH_PREFIX):
        relative = path[len(_PACKAGE_PATH_PREFIX) :]
        parts = relative.split("/", maxsplit=1)
        if len(parts) != 2:
            raise TemplateError(f"Invalid package template path: {path}")

        canary_type, filename = parts
        target = resources.files("anglerfish").joinpath("templates", canary_type, filename)
        if not target.is_file():
            raise TemplateError(f"Template not found: {path}")

        with target.open("r", encoding="utf-8") as handle:
            return _parse_yaml(handle.read(), source=path)

    target_path = Path(path)
    if not target_path.is_file():
        raise TemplateError(f"Template file not found: {path}")

    return _read_yaml_from_path(target_path)


def _read_yaml_from_path(path: Path) -> dict:
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise TemplateError(f"Failed to read template '{path}': {exc}") from exc

    return _parse_yaml(raw, source=str(path))


def _parse_yaml(raw: str, source: str) -> dict:
    try:
        parsed = yaml.safe_load(raw)
    except yaml.YAMLError as exc:
        raise TemplateError(f"Failed to parse YAML for '{source}': {exc}") from exc

    if not isinstance(parsed, dict):
        raise TemplateError(f"Template '{source}' must be a YAML mapping/object.")

    return parsed


def _parse_variables(raw: object) -> list[dict[str, str]]:
    if raw is None:
        return []
    if not isinstance(raw, list):
        raise TemplateError("'variables' must be a list")
    variables: list[dict[str, str]] = []
    for entry in raw:
        if not isinstance(entry, dict) or "name" not in entry:
            raise TemplateError("Each variable must be a mapping with at least a 'name' key")
        variables.append({k: str(v) for k, v in entry.items()})
    return variables


def _parse_filenames(raw: object) -> list[str]:
    if not isinstance(raw, list):
        raise TemplateError("'filenames' must be a list")

    filenames: list[str] = []
    for entry in raw:
        name = str(entry).strip()
        if not name:
            raise TemplateError("Each entry in 'filenames' must be a non-empty string")
        filenames.append(name)

    if not filenames:
        raise TemplateError("'filenames' must include at least one value")
    if len(filenames) != 1:
        raise TemplateError("'filenames' must include exactly one value")

    return filenames


_OUTLOOK_RENDER_FIELDS = ("subject", "body_html", "sender_name", "sender_email", "folder_name")


def render_template(
    template: OutlookTemplate | SharePointTemplate | OneDriveTemplate,
    values: dict[str, str],
) -> OutlookTemplate | SharePointTemplate | OneDriveTemplate:
    """Substitute template variables and return a new template instance."""
    # Build defaults from variable definitions
    defaults: dict[str, str] = {}
    for var in template.variables:
        if "default" in var:
            defaults[var["name"]] = var["default"]

    merged = {**defaults, **values}

    # Validate all required variables are provided
    missing = [var["name"] for var in template.variables if "default" not in var and var["name"] not in values]
    if missing:
        raise TemplateError(f"Missing required template variables: {', '.join(missing)}")

    if isinstance(template, OutlookTemplate):
        updates: dict[str, str] = {}
        for field in _OUTLOOK_RENDER_FIELDS:
            original = getattr(template, field)
            updates[field] = StringTemplate(original).safe_substitute(merged)
        return dataclasses.replace(template, **updates)

    if isinstance(template, SharePointTemplate):
        site_name = StringTemplate(template.site_name).safe_substitute(merged).strip()
        folder_path = StringTemplate(template.folder_path).safe_substitute(merged).strip()
        filenames = [StringTemplate(filename).safe_substitute(merged).strip() for filename in template.filenames]
        content_text = StringTemplate(template.content_text).safe_substitute(merged).strip()
        if not site_name:
            raise TemplateError("Rendered template produced an empty site_name")
        if not folder_path:
            raise TemplateError("Rendered template produced an empty folder_path")
        if not all(filenames):
            raise TemplateError("Rendered template produced empty filename entries")
        if len(filenames) != 1:
            raise TemplateError("Rendered template produced multiple filenames; exactly one is required")
        if not content_text:
            raise TemplateError("Rendered template produced empty content_text")
        return dataclasses.replace(
            template,
            site_name=site_name,
            folder_path=folder_path,
            filenames=filenames,
            content_text=content_text,
        )

    if isinstance(template, OneDriveTemplate):
        folder_path = StringTemplate(template.folder_path).safe_substitute(merged).strip()
        filenames = [StringTemplate(filename).safe_substitute(merged).strip() for filename in template.filenames]
        content_text = StringTemplate(template.content_text).safe_substitute(merged).strip()
        if not all(filenames):
            raise TemplateError("Rendered template produced empty filename entries")
        if len(filenames) != 1:
            raise TemplateError("Rendered template produced multiple filenames; exactly one is required")
        if not content_text:
            raise TemplateError("Rendered template produced empty content_text")
        return dataclasses.replace(
            template,
            folder_path=folder_path,
            filenames=filenames,
            content_text=content_text,
        )

    raise TemplateError("Unsupported template object")
