"""Deployer exports."""

from __future__ import annotations

from importlib import import_module
from typing import Any

__all__ = ["OutlookDeployer"]


def __getattr__(name: str) -> Any:
    if name == "OutlookDeployer":
        return import_module(".outlook", __name__).OutlookDeployer
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
