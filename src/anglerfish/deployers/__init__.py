"""Deployer exports."""

from __future__ import annotations

from importlib import import_module
from typing import Any

__all__ = ["OneDriveDeployer", "OutlookDeployer", "SharePointDeployer"]


def __getattr__(name: str) -> Any:
    if name == "OutlookDeployer":
        return import_module(".outlook", __name__).OutlookDeployer
    if name == "SharePointDeployer":
        return import_module(".sharepoint", __name__).SharePointDeployer
    if name == "OneDriveDeployer":
        return import_module(".onedrive", __name__).OneDriveDeployer
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
