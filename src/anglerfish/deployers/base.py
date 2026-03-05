"""Base deployer interface."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from ..graph import GraphClient


class BaseDeployer(ABC):
    def __init__(self, graph: GraphClient, template: Any):
        self.graph = graph
        self.template = template

    @abstractmethod
    def deploy(self, target_user: str, **kwargs: Any) -> dict[str, str]:
        """Deploy canary artifact and return summary metadata."""
