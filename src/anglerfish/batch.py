"""Batch manifest parsing and deployment orchestration."""

from __future__ import annotations

import dataclasses
import datetime
import logging
from pathlib import Path

import yaml

from .deployers.onedrive import OneDriveDeployer
from .deployers.outlook import OutlookDeployer
from .deployers.sharepoint import SharePointDeployer
from .exceptions import DeploymentError
from .inventory import write_deployment_record
from .models import CanarySpec, OneDriveTemplate, SharePointTemplate
from .templates import find_template_by_name as _find_template_by_name, load_template, render_template

logger = logging.getLogger(__name__)

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
        raise DeploymentError(f"Manifest '{path}' must contain at least one entry in 'canaries'.")

    default_vars: dict[str, str] = {}
    defaults = data.get("defaults")
    if isinstance(defaults, dict):
        raw_vars = defaults.get("vars")
        if isinstance(raw_vars, dict):
            for k, v in raw_vars.items():
                val = str(v)
                if len(val) > 500:
                    raise DeploymentError(f"Default variable value for '{k}' exceeds 500 characters.")
                default_vars[str(k)] = val

    specs: list[CanarySpec] = []
    for i, entry in enumerate(canaries_raw):
        if not isinstance(entry, dict):
            raise DeploymentError(f"Canary entry {i + 1} must be a mapping.")

        missing = [f for f in _REQUIRED_ENTRY_FIELDS if f not in entry]
        if missing:
            raise DeploymentError(f"Canary entry {i + 1} is missing required fields: {', '.join(missing)}")

        canary_type = str(entry["canary_type"]).strip().lower()
        if canary_type not in _VALID_CANARY_TYPES:
            raise DeploymentError(
                f"Canary entry {i + 1} has invalid canary_type '{canary_type}'. "
                f"Valid types: {', '.join(sorted(_VALID_CANARY_TYPES))}"
            )

        entry_vars: dict[str, str] = {}
        raw_entry_vars = entry.get("vars")
        if isinstance(raw_entry_vars, dict):
            for k, v in raw_entry_vars.items():
                val = str(v)
                if len(val) > 500:
                    raise DeploymentError(f"Canary entry {i + 1}: variable value for '{k}' exceeds 500 characters.")
                entry_vars[str(k)] = val

        merged_vars = {**default_vars, **entry_vars}

        specs.append(
            CanarySpec(
                canary_type=canary_type,
                template=str(entry["template"]).strip(),
                target=str(entry["target"]).strip(),
                delivery_mode=(str(entry["delivery_mode"]).strip() if "delivery_mode" in entry else None),
                folder_path=(str(entry["folder_path"]).strip() if "folder_path" in entry else None),
                filename=(str(entry["filename"]).strip() if "filename" in entry else None),
                vars=merged_vars,
            )
        )

    return specs


def run_batch(
    specs: list[CanarySpec],
    *,
    graph: object,
    output_dir: str | Path,
    dry_run: bool = False,
) -> list[dict]:
    """Deploy a batch of canary specs and return one result dict per spec."""
    output_path = Path(output_dir)
    results: list[dict] = []

    for index, spec in enumerate(specs):
        result: dict = {
            "index": index,
            "canary_type": spec.canary_type,
            "target": spec.target,
            "template": spec.template,
        }

        try:
            # 1. Resolve template by name
            template_path = _find_template_by_name(spec.canary_type, spec.template)

            # 2. Load template
            template = load_template(template_path)

            # 3. Render template with spec vars
            rendered = render_template(template, spec.vars)

            # 4. Apply overrides from spec for SharePoint/OneDrive
            if isinstance(rendered, (SharePointTemplate, OneDriveTemplate)):
                overrides: dict = {}
                if spec.folder_path is not None:
                    overrides["folder_path"] = spec.folder_path
                if spec.filename is not None:
                    overrides["filenames"] = [spec.filename]
                if overrides:
                    rendered = dataclasses.replace(rendered, **overrides)

            # 5. Dry run: skip deployment
            if dry_run:
                result["success"] = True
                result["dry_run"] = True
                results.append(result)
                continue

            # 6. Deploy
            if spec.canary_type == "outlook":
                deployer = OutlookDeployer(graph, rendered)
                deploy_result = deployer.deploy(
                    spec.target,
                    delivery_mode=spec.delivery_mode or "draft",
                )
            elif spec.canary_type == "sharepoint":
                deployer = SharePointDeployer(graph, rendered)
                deploy_result = deployer.deploy(
                    spec.target,
                    folder_path=rendered.folder_path,
                    filenames=rendered.filenames,
                )
            elif spec.canary_type == "onedrive":
                deployer = OneDriveDeployer(graph, rendered)
                deploy_result = deployer.deploy(
                    spec.target,
                    folder_path=rendered.folder_path,
                    filenames=rendered.filenames,
                )
            else:
                raise DeploymentError(f"Unsupported canary type: {spec.canary_type}")

            # Write deployment record
            safe_target = spec.target.replace("@", "-").replace(".", "-")
            timestamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
            record_filename = f"{spec.canary_type}-{safe_target}-{timestamp}.json"
            record_path = output_path / record_filename

            record = {
                "canary_type": spec.canary_type,
                "template": spec.template,
                "target": spec.target,
                **deploy_result,
            }
            write_deployment_record(record_path, record)

            result["success"] = True
            result["record_path"] = str(record_path)

        except Exception as exc:
            logger.error(
                "Batch deploy failed for spec %d (%s -> %s): %s",
                index,
                spec.canary_type,
                spec.target,
                exc,
            )
            result["success"] = False
            result["error"] = str(exc)

        results.append(result)

    return results
