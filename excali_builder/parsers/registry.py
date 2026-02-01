"""Parser registry for format-based parser selection."""

from typing import Dict, Type, Optional
from .base import BaseParser


class ParserRegistry:
    """Registry for managing parsers by format name."""

    def __init__(self):
        self.parsers: Dict[str, Type[BaseParser]] = {}

    def register(self, format_name: str, parser_class: Type[BaseParser]):
        """Register a parser for a format name."""
        self.parsers[format_name] = parser_class

    def get_parser(self, format_name: str) -> Optional[Type[BaseParser]]:
        """Get parser class for a format name."""
        return self.parsers.get(format_name)

