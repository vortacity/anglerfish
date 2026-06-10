"""Registry of canary types: the single dispatch point for lifecycle operations.

Adding a new canary surface means implementing :class:`~.base.CanaryType`
and registering an instance here. The CLI, monitor, verify, and cleanup
paths consult the registry instead of hardcoding type names.
"""

from __future__ import annotations

from ..exceptions import DeploymentError
from .base import CanaryType
from .outlook import OutlookCanaryType

_REGISTRY: dict[str, CanaryType] = {}


def register(canary_type: CanaryType) -> None:
    _REGISTRY[canary_type.name] = canary_type


def supported_canary_types() -> tuple[str, ...]:
    """Registered type names, in registration order."""
    return tuple(_REGISTRY)


def get_canary_type(name: str) -> CanaryType:
    """Look up a canary type by name. Raises DeploymentError for unknown names."""
    canary_type = find_canary_type(name)
    if canary_type is None:
        supported = ", ".join(supported_canary_types())
        raise DeploymentError(f"Unsupported canary type '{name}'. Supported types: {supported}.")
    return canary_type


def find_canary_type(name: str) -> CanaryType | None:
    """Look up a canary type by name, returning ``None`` for unknown names."""
    return _REGISTRY.get(str(name or "").strip().lower())


def all_audit_content_types() -> tuple[str, ...]:
    """Union of audit content types needed by all registered canary types."""
    seen: list[str] = []
    for canary_type in _REGISTRY.values():
        for content_type in canary_type.audit_content_types:
            if content_type not in seen:
                seen.append(content_type)
    return tuple(seen)


register(OutlookCanaryType())
