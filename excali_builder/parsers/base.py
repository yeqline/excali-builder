"""Abstract base parser for converting source files to graphs."""

from abc import ABC, abstractmethod
from pathlib import Path
from typing import Dict, Any, List
from ..core.graph import Graph


class BaseParser(ABC):
    """Abstract base class for parsers that convert source files to graphs."""

    @abstractmethod
    def parse(self, path: Path, options: Dict[str, Any]) -> Graph:
        """Parse source files and return a Graph. Must produce stable node_id values."""
        pass

    @abstractmethod
    def get_supported_formats(self) -> List[str]:
        """Return list of supported file extensions."""
        pass

