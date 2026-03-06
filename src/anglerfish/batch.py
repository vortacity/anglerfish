"""Batch manifest parsing and deployment orchestration."""

from __future__ import annotations

from pathlib import Path

import yaml

from .exceptions import DeploymentError
from .models import CanarySpec

_VALID_CANARY_TYPES = {"outlook", "sharepoint", "onedrive"}
_REQUIRED_ENTRY_FIELDS = ("canary_type", "template", "target")


def parse_manifest(path: str | Path) -> list[CanarySpec]:
    """Parse a batch manifest YAML file and return a list of CanarySpec entries."""
    manifest_path = Path(path)
    if not manifest_path.is_file():
        raise DeploymentError(f"Manifest file not found: {path}")

    try:
        raw = manifest_path.read_text(encoding="utf-8")
    except OSError as exc:
        raise DeploymentError(f"Failed to read manifest '{path}': {exc}") from exc

    try:
        data = yaml.safe_load(raw)
    except yaml.YAMLError as exc:
        raise DeploymentError(f"Failed to parse manifest YAML '{path}': {exc}") from exc

    if not isinstance(data, dict):
        raise DeploymentError(f"Manifest '{path}' must be a YAML mapping.")

    if "canaries" not in data:
        raise DeploymentError(f"Manifest '{path}' is missing required key 'canaries'.")

    canaries_raw = data["canaries"]
    if not isinstance(canaries_raw, list) or len(canaries_raw) == 0:
        raise DeploymentError(
            f"Manifest '{path}' must contain at least one entry in 'canaries'."
        )

    default_vars: dict[str, str] = {}
    defaults = data.get("defaults")
    if isinstance(defaults, dict):
        raw_vars = defaults.get("vars")
        if isinstance(raw_vars, dict):
            default_vars = {str(k): str(v) for k, v in raw_vars.items()}

    specs: list[CanarySpec] = []
    for i, entry in enumerate(canaries_raw):
        if not isinstance(entry, dict):
            raise DeploymentError(f"Canary entry {i + 1} must be a mapping.")

        missing = [f for f in _REQUIRED_ENTRY_FIELDS if f not in entry]
        if missing:
            raise DeploymentError(
                f"Canary entry {i + 1} is missing required fields: {', '.join(missing)}"
            )

        canary_type = str(entry["canary_type"]).strip().lower()
        if canary_type not in _VALID_CANARY_TYPES:
            raise DeploymentError(
                f"Canary entry {i + 1} has invalid canary_type '{canary_type}'. "
                f"Valid types: {', '.join(sorted(_VALID_CANARY_TYPES))}"
            )

        entry_vars: dict[str, str] = {}
        raw_entry_vars = entry.get("vars")
        if isinstance(raw_entry_vars, dict):
            entry_vars = {str(k): str(v) for k, v in raw_entry_vars.items()}

        merged_vars = {**default_vars, **entry_vars}

        specs.append(
            CanarySpec(
                canary_type=canary_type,
                template=str(entry["template"]).strip(),
                target=str(entry["target"]).strip(),
                delivery_mode=(
                    str(entry["delivery_mode"]).strip()
                    if "delivery_mode" in entry
                    else None
                ),
                folder_path=(
                    str(entry["folder_path"]).strip()
                    if "folder_path" in entry
                    else None
                ),
                filename=(
                    str(entry["filename"]).strip() if "filename" in entry else None
                ),
                vars=merged_vars,
            )
        )

    return specs
