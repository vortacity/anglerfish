"""Canary lifecycle contract: deployer, audit matcher, and canary type."""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime
from typing import TYPE_CHECKING, Any, ClassVar, Sequence

from ..models import CanaryAlert, VerifyResult

if TYPE_CHECKING:
    from ..graph import GraphClient
    from ..inventory import DeploymentRecord


class BaseDeployer(ABC):
    def __init__(self, graph: GraphClient, template: Any):
        self.graph = graph
        self.template = template

    @abstractmethod
    def deploy(self, target_user: str, **kwargs: Any) -> dict[str, str]:
        """Deploy canary artifact and return summary metadata."""


class CanaryMatcher(ABC):
    """Per-type audit-event matcher built from deployment records."""

    @property
    @abstractmethod
    def count(self) -> int:
        """Number of indexed canaries."""

    @abstractmethod
    def match(self, event: dict, *, now: datetime | None = None) -> CanaryAlert | None:
        """Return an alert when an audit event hits one of this type's canaries."""


class CanaryType(ABC):
    """Full lifecycle contract for one canary surface.

    Implementing this class (and registering it in ``deployers.registry``) is
    everything a new canary surface needs: the CLI, monitor, verify, and
    cleanup paths all dispatch through it instead of hardcoding type names.
    """

    #: Registry key and the value stored in deployment records.
    name: ClassVar[str]
    #: Management Activity API content types this surface needs subscribed.
    audit_content_types: ClassVar[tuple[str, ...]] = ()

    @abstractmethod
    def create_deployer(self, graph: GraphClient, template: Any) -> BaseDeployer:
        """Construct the deployer used by the deploy flow."""

    @abstractmethod
    def remove(self, graph: GraphClient, record: DeploymentRecord) -> dict[str, str]:
        """Remove the deployed artifact described by *record*."""

    @abstractmethod
    def trigger_access(self, graph: GraphClient, record: DeploymentRecord) -> dict[str, str]:
        """Read the canary through the API to generate authorized audit evidence."""

    @abstractmethod
    def verify(self, graph: GraphClient, record: DeploymentRecord) -> VerifyResult:
        """Check that the deployed artifact still exists."""

    def preflight_verify(self, record: DeploymentRecord) -> VerifyResult | None:
        """Return a terminal result when verification cannot reach the API.

        Lets callers screen malformed or unverifiable records *before*
        authenticating. ``None`` means an API check is required.
        """
        return None

    @abstractmethod
    def build_matcher(self, records: Sequence[tuple[str, DeploymentRecord]]) -> CanaryMatcher:
        """Build an audit-event matcher over this type's deployment records."""
