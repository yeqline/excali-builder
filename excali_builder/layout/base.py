"""Abstract base class for layout algorithms."""

from abc import ABC, abstractmethod
from typing import Dict
from ..core.graph import Graph


class BaseLayout(ABC):
    """Abstract base class for layout algorithms."""

    @abstractmethod
    def apply_layout(self, graph: Graph, config: Dict) -> None:
        """Apply layout algorithm to graph nodes."""
        pass

